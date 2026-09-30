from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class Observation:
    pick_id: int
    station_code: str
    phase: Literal["P", "S"]
    x: float
    y: float
    z: float
    observed_offset_s: float | None
    status: str
    note: str


@dataclass
class CandidateResult:
    label: str
    method: str
    x: float
    y: float
    z: float
    origin_offset_s: float
    depth_fixed: bool
    used: list[bool]
    residuals: list[float | None]
    predicted: list[float | None]
    distances: list[float | None]
    rms: float
    max_abs: float
    condition_number: float | None
    rank: int
    azimuthal_gap: float | None
    coverage_rating: str
    semi_major: float | None
    semi_minor: float | None
    rotation: float | None


def travel_time(source: np.ndarray, station: np.ndarray, velocity: float) -> float:
    return float(np.linalg.norm(source - station) / velocity)


def geometry_metrics(stations: np.ndarray, dimensionality: int = 2) -> tuple[float | None, int, float | None, str]:
    """Return condition number, rank, azimuthal gap, and teaching rating."""
    coords = stations[:, :dimensionality]
    if len(coords) < 2:
        return None, len(coords), None, "insufficient"

    centered = coords - np.mean(coords, axis=0)
    singular = np.linalg.svd(centered, compute_uv=False)
    positive = singular[singular > 1e-9]
    rank = int(positive.size)
    condition = float(singular[0] / singular[-1]) if positive.size else None

    if len(stations) < 3:
        gap = None
        rating = "insufficient"
    else:
        horizontal = stations[:, :2] - np.mean(stations[:, :2], axis=0)
        angles = np.sort(np.degrees(np.arctan2(horizontal[:, 1], horizontal[:, 0])) % 360.0)
        gaps = np.diff(angles)
        gaps = np.append(gaps, angles[0] + 360.0 - angles[-1])
        gap = float(np.max(gaps))
        condition_value = condition or math.inf
        if gap > 180.0 or condition_value > 30.0:
            rating = "poor"
        elif gap > 120.0 or condition_value > 10.0:
            rating = "fair"
        else:
            rating = "good"
    return condition, rank, gap, rating


def _initial_guess(obs: list[Observation], velocity: float, fixed_z: float | None) -> np.ndarray:
    observed = [o for o in obs if o.observed_offset_s is not None]
    xs = np.array([[o.x, o.y, o.z] for o in observed], dtype=float)
    ts = np.array([o.observed_offset_s for o in observed], dtype=float)
    centroid = xs.mean(axis=0)
    if fixed_z is not None:
        centroid[2] = fixed_z
    t0 = float(
        np.mean(
            [
                t - np.linalg.norm(centroid - np.array([o.x, o.y, o.z])) / velocity
                for o, t in zip(observed, ts)
            ]
        )
    )
    return np.array([centroid[0], centroid[1], centroid[2], t0], dtype=float)


def _predict_all(params: np.ndarray, obs: list[Observation], velocity: float) -> np.ndarray:
    source = params[:3]
    return np.array(
        [
            params[3]
            + np.linalg.norm(source - np.array([o.x, o.y, o.z])) / velocity
            for o in obs
        ]
    )


def _residuals(params: np.ndarray, obs: list[Observation], velocity: float) -> np.ndarray:
    predicted = _predict_all(params, obs, velocity)
    observed = np.array(
        [np.nan if o.observed_offset_s is None else o.observed_offset_s for o in obs],
        dtype=float,
    )
    return observed - predicted


def _observed_indices(obs: list[Observation]) -> list[int]:
    return [i for i, o in enumerate(obs) if o.observed_offset_s is not None]


def _fit(
    obs: list[Observation],
    velocity: float,
    *,
    fixed_z: float | None,
    robust: bool,
    label: str,
    method: str,
    outlier_threshold_s: float,
) -> CandidateResult | None:
    observed_idx = _observed_indices(obs)
    minimum = 3 if fixed_z is not None else 4
    if len(observed_idx) < minimum:
        return None

    p0 = _initial_guess(obs, velocity, fixed_z)
    bounds_lower = [-100.0, -100.0, 0.0, -60.0]
    bounds_upper = [100.0, 100.0, 40.0, 60.0]
    if fixed_z is not None:
        # Freeze z by setting identical lower and upper bounds.
        bounds_lower[2] = fixed_z
        bounds_upper[2] = fixed_z

    def fit_residuals(free_params: np.ndarray) -> np.ndarray:
        params = p0.copy()
        if fixed_z is None:
            params[:4] = free_params
        else:
            params[:2] = free_params[:2]
            params[3] = free_params[2]
        all_res = _residuals(params, obs, velocity)
        return all_res[observed_idx]

    x0 = p0.copy()
    if fixed_z is None:
        free0 = x0
    else:
        free0 = np.array([x0[0], x0[1], x0[3]])

    try:
        result = least_squares(
            fit_residuals,
            free0,
            bounds=(
                np.array([bounds_lower[0], bounds_lower[1], bounds_lower[3]]),
                np.array([bounds_upper[0], bounds_upper[1], bounds_upper[3]]),
            )
            if fixed_z is not None
            else (np.array(bounds_lower), np.array(bounds_upper)),
            loss="soft_l1" if robust else "linear",
            f_scale=outlier_threshold_s,
            max_nfev=1000,
        )
    except ValueError:
        return None

    params = p0.copy()
    if fixed_z is None:
        params[:4] = result.x
    else:
        params[:2] = result.x[:2]
        params[2] = fixed_z
        params[3] = result.x[2]

    predicted = _predict_all(params, obs, velocity)
    raw_residuals = _residuals(params, obs, velocity)
    used = [o.observed_offset_s is not None for o in obs]
    residual_values: list[float | None] = []
    for i, o in enumerate(obs):
        if o.observed_offset_s is None:
            # Preserve the slot without inventing an observed residual.
            predicted[i] = np.nan
            residual_values.append(None)
            continue
        value = float(raw_residuals[i])
        residual_values.append(value)
        if o.status == "outlier":
            # Explicit bad picks never enter reported RMS; the candidate can still
            # show the large residual that demonstrates ordinary-fit sensitivity.
            used[i] = False
        elif robust and abs(value) > outlier_threshold_s:
            # The robust solution may additionally down-weight/reject a newly
            # discovered residual beyond the teaching threshold.
            used[i] = False

    used_points = np.array(
        [[obs[i].x, obs[i].y, obs[i].z] for i in observed_idx if used[i]], dtype=float
    )
    condition, _station_rank, gap, rating = (
        geometry_metrics(used_points, dimensionality=2)
        if len(used_points)
        else (None, 0, None, "insufficient")
    )

    # Linearized Jacobian is the actual rank check: it includes t0 and, when
    # requested, depth, rather than just station coordinate geometry.
    selected_indices = [i for i in observed_idx if used[i]]
    jacobian = []
    source = params[:3]
    for i in selected_indices:
        station = np.array([obs[i].x, obs[i].y, obs[i].z])
        delta = source - station
        distance = max(float(np.linalg.norm(delta)), 1e-6)
        spatial = delta / (distance * velocity)
        if fixed_z is not None:
            jacobian.append([spatial[0], spatial[1], 1.0])
        else:
            jacobian.append([spatial[0], spatial[1], spatial[2], 1.0])
    j = np.array(jacobian, dtype=float)
    jacobian_rank = int(np.linalg.matrix_rank(j))
    if jacobian_rank < j.shape[1]:
        return None

    used_residuals = np.array(
        [raw_residuals[i] for i in observed_idx if used[i]], dtype=float
    )
    rms = float(np.sqrt(np.mean(used_residuals**2))) if used_residuals.size else math.nan
    max_abs = float(np.max(np.abs(used_residuals))) if used_residuals.size else math.nan

    # Linearized covariance from the Jacobian built above.
    semi_major = semi_minor = rotation = None
    if j.shape[0] > j.shape[1] and jacobian_rank == j.shape[1]:
        dof = max(j.shape[0] - j.shape[1], 1)
        variance = float(np.sum(used_residuals**2) / dof)
        covariance = variance * np.linalg.pinv(j.T @ j)
        xy_cov = covariance[:2, :2]
        eigvals, eigvecs = np.linalg.eigh(xy_cov)
        positive = np.maximum(eigvals, 0.0)
        axes = np.sqrt(positive)
        semi_major = float(max(axes[0], axes[1]))
        semi_minor = float(min(axes[0], axes[1]))
        major_vector = eigvecs[:, 1] if axes[1] >= axes[0] else eigvecs[:, 0]
        rotation = float(np.degrees(np.arctan2(major_vector[1], major_vector[0])))

    distances: list[float | None] = []
    for i, o in enumerate(obs):
        distances.append(
            float(np.linalg.norm(params[:3] - np.array([o.x, o.y, o.z])))
        )

    return CandidateResult(
        label=label,
        method=method,
        x=float(params[0]),
        y=float(params[1]),
        z=float(params[2]),
        origin_offset_s=float(params[3]),
        depth_fixed=fixed_z is not None,
        used=used,
        residuals=residual_values,
        predicted=[float(v) if not np.isnan(v) else None for v in predicted],
        distances=distances,
        rms=rms,
        max_abs=max_abs,
        condition_number=condition,
        rank=jacobian_rank,
        azimuthal_gap=gap,
        coverage_rating=rating,
        semi_major=semi_major,
        semi_minor=semi_minor,
        rotation=rotation,
    )


def solve_candidates(
    obs: list[Observation],
    velocity: float,
    fixed_depth_km: float | None,
    outlier_threshold_s: float,
    include_free_depth: bool,
) -> tuple[list[CandidateResult], list[str]]:
    reasons: list[str] = []
    observed_count = sum(o.observed_offset_s is not None for o in obs)
    observed_points = np.array(
        [[o.x, o.y, o.z] for o in obs if o.observed_offset_s is not None], dtype=float
    )
    if observed_count:
        condition, geometry_rank, gap, rating = geometry_metrics(
            observed_points, dimensionality=2
        )
    else:
        condition, geometry_rank, gap, rating = None, 0, None, "insufficient"

    if observed_count < 3:
        reasons.append(
            f"同一震相仅有 {observed_count} 个有效到时；固定深度至少需要 3 个，自由深度至少需要 4 个。"
        )
    if fixed_depth_km is None and observed_count < 4:
        reasons.append(
            f"自由深度至少需要 4 个同一震相到时；当前为 {observed_count} 个。"
        )

    # Near-collinear layouts can still produce a numerical answer, so retain the
    # candidates for comparison while making the geometry warning explicit.
    if observed_count >= 3 and rating == "poor":
        reasons.append(
            "台站几何覆盖很差（近似共线或方位空挡过大）；候选解可能对微小拾取误差极敏感，不能报告唯一精确坐标。"
        )

    candidates: list[CandidateResult] = []
    if observed_count >= 3 and geometry_rank >= 2 and fixed_depth_km is not None:
        robust = _fit(
            obs,
            velocity,
            fixed_z=fixed_depth_km,
            robust=True,
            label=f"稳健拟合 · 深度固定 {fixed_depth_km:g} km",
            method="soft_l1_fixed_depth",
            outlier_threshold_s=outlier_threshold_s,
        )
        if robust:
            candidates.append(robust)
        ordinary = _fit(
            obs,
            velocity,
            fixed_z=fixed_depth_km,
            robust=False,
            label=f"普通最小二乘 · 深度固定 {fixed_depth_km:g} km",
            method="linear_least_squares_fixed_depth",
            outlier_threshold_s=outlier_threshold_s,
        )
        if ordinary:
            candidates.append(ordinary)

    if include_free_depth and observed_count >= 4:
        free = _fit(
            obs,
            velocity,
            fixed_z=None,
            robust=True,
            label="稳健拟合 · 深度自由",
            method="soft_l1_free_depth",
            outlier_threshold_s=outlier_threshold_s,
        )
        if free:
            candidates.append(free)
        elif observed_count >= 4:
            reasons.append("自由深度解未通过线性化秩检查；深度—发震时刻权衡无法由当前几何稳定约束。")

    return candidates, reasons


def make_input_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def candidate_sort_key(candidate: CandidateResult) -> tuple[int, float, float]:
    rejected = sum(not used for used in candidate.used)
    # Prefer robust fixed-depth solutions as the teaching default; free-depth
    # results are shown for comparison but not promoted merely by a lower RMS.
    method_preference = {
        "soft_l1_fixed_depth": 0,
        "linear_least_squares_fixed_depth": 1,
        "soft_l1_free_depth": 2,
    }.get(candidate.method, 9)
    return (rejected, method_preference, candidate.rms)


def origin_time_for(candidate: CandidateResult, scenario_origin_time):
    return scenario_origin_time + timedelta(seconds=candidate.origin_offset_s)

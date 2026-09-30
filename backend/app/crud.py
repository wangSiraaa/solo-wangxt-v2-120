from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from .location import (
    Observation,
    candidate_sort_key,
    geometry_metrics,
    make_input_hash,
    origin_time_for,
    solve_candidates,
)
from .models import (
    LocationCandidate,
    LocationRun,
    Pick,
    PickResidual,
    PickSet,
    Scenario,
    Station,
)
from .schemas import (
    CandidateOut,
    LocationRunOut,
    PickOut,
    PickSetOut,
    ResidualOut,
    ScenarioDetail,
    ScenarioSummary,
    StationOut,
)


def serialize_pick(pick: Pick) -> PickOut:
    return PickOut(
        id=pick.id,
        station_id=pick.station_id,
        station_code=pick.station.code,
        phase=pick.phase,
        pick_time=pick.pick_time,
        arrival_time_offset_s=pick.arrival_time_offset_s,
        quality=pick.quality,
        status=pick.status,
        note=pick.note,
    )


def serialize_pick_set(pick_set: PickSet) -> PickSetOut:
    ordered = sorted(pick_set.picks, key=lambda item: (item.phase, item.station.code))
    return PickSetOut(
        id=pick_set.id,
        kind=pick_set.kind,
        version=pick_set.version,
        parent_set_id=pick_set.parent_set_id,
        note=pick_set.note,
        created_at=pick_set.created_at,
        picks=[serialize_pick(pick) for pick in ordered],
    )


def serialize_station(station: Station) -> StationOut:
    return StationOut(
        id=station.id,
        code=station.code,
        name=station.name,
        x_km=station.x_km,
        y_km=station.y_km,
        elevation_km=station.elevation_km,
    )


def serialize_summary(scenario: Scenario) -> ScenarioSummary:
    return ScenarioSummary(
        id=scenario.id,
        name=scenario.name,
        description=scenario.description,
        data_version=scenario.data_version,
        station_count=len(scenario.stations),
        expected_teaching_note=scenario.expected_teaching_note,
    )


def serialize_detail(scenario: Scenario, reveal_truth: bool) -> ScenarioDetail:
    summary = serialize_summary(scenario)
    return ScenarioDetail(
        **summary.model_dump(by_alias=True),
        origin_time=scenario.origin_time,
        source_x_km=scenario.source_x_km if reveal_truth else None,
        source_y_km=scenario.source_y_km if reveal_truth else None,
        source_z_km=scenario.source_z_km if reveal_truth else None,
        reveal_truth=reveal_truth,
        stations=[serialize_station(station) for station in scenario.stations],
        pick_sets=[serialize_pick_set(pick_set) for pick_set in scenario.pick_sets],
    )


def get_scenario(db: Session, scenario_id: str) -> Scenario | None:
    return (
        db.query(Scenario)
        .options(
            joinedload(Scenario.stations),
            joinedload(Scenario.pick_sets).joinedload(PickSet.picks).joinedload(Pick.station),
        )
        .filter(Scenario.id == scenario_id)
        .one_or_none()
    )


def list_scenarios(db: Session) -> list[Scenario]:
    return (
        db.query(Scenario)
        .options(joinedload(Scenario.stations))
        .order_by(Scenario.id)
        .all()
    )


def resolve_pick_set(db: Session, scenario: Scenario, pick_set_id: int | None) -> PickSet:
    if pick_set_id is None:
        manual = next((item for item in scenario.pick_sets if item.kind == "manual"), None)
        return manual or next(item for item in scenario.pick_sets if item.kind == "raw")
    pick_set = db.get(PickSet, pick_set_id)
    if pick_set is None or pick_set.scenario_id != scenario.id:
        raise ValueError("拾取集不属于该案例。")
    return pick_set


def create_manual_revision(
    db: Session,
    scenario: Scenario,
    base_pick_set_id: int | None,
    phase: str,
    revisions,
    note: str,
) -> PickSet:
    base = resolve_pick_set(db, scenario, base_pick_set_id)
    existing_manual_count = (
        db.query(PickSet)
        .filter(PickSet.scenario_id == scenario.id, PickSet.kind == "manual")
        .count()
    )
    version = f"manual-review-v{existing_manual_count + 1}.0"
    pick_set = PickSet(
        scenario_id=scenario.id,
        parent_set_id=base.id,
        kind="manual",
        version=version,
        note=note,
    )
    db.add(pick_set)
    db.flush()

    revision_map = {(item.station_code, item.phase): item for item in revisions}
    for pick in base.picks:
        revised = revision_map.pop((pick.station.code, phase), None) if pick.phase == phase else None
        if revised is None:
            db.add(
                Pick(
                    pick_set_id=pick_set.id,
                    station_id=pick.station_id,
                    phase=pick.phase,
                    pick_time=pick.pick_time,
                    arrival_time_offset_s=pick.arrival_time_offset_s,
                    quality=pick.quality,
                    status=pick.status,
                    note=pick.note,
                )
            )
        else:
            offset = revised.arrival_time_offset_s
            pick_time = None
            if offset is not None:
                pick_time = scenario.origin_time + timedelta(seconds=offset)
            db.add(
                Pick(
                    pick_set_id=pick_set.id,
                    station_id=pick.station_id,
                    phase=phase,
                    pick_time=pick_time,
                    arrival_time_offset_s=offset,
                    quality="manual" if offset is not None else "missing",
                    status=revised.status if offset is not None else "missing",
                    note=revised.note,
                )
            )
    if revision_map:
        codes = ", ".join(f"{station}/{p}" for station, p in revision_map)
        raise ValueError(f"未找到对应台站或震相：{codes}")

    db.commit()
    db.refresh(pick_set)
    return pick_set


def _build_observations(
    picks: list[Pick], phase: str
) -> list[Observation]:
    phase_picks = [pick for pick in picks if pick.phase == phase]
    return [
        Observation(
            pick_id=pick.id,
            station_code=pick.station.code,
            phase=pick.phase,
            x=pick.station.x_km,
            y=pick.station.y_km,
            z=-pick.station.elevation_km,
            observed_offset_s=pick.arrival_time_offset_s,
            status=pick.status,
            note=pick.note,
        )
        for pick in phase_picks
    ]


def _serialize_candidate(
    run: LocationRun, candidate: LocationCandidate, scenario_origin_time
) -> CandidateOut:
    residuals = sorted(candidate.residuals, key=lambda item: (item.phase, item.station_code))
    return CandidateOut(
        id=candidate.id,
        label=candidate.label,
        method=candidate.method,
        x_km=candidate.x_km,
        y_km=candidate.y_km,
        z_km=candidate.z_km,
        origin_time=candidate.origin_time,
        origin_time_offset_s=(candidate.origin_time - scenario_origin_time).total_seconds(),
        rms_residual_s=candidate.rms_residual_s,
        max_abs_residual_s=candidate.max_abs_residual_s,
        used_pick_count=candidate.used_pick_count,
        rejected_pick_count=candidate.rejected_pick_count,
        coverage_rating=candidate.coverage_rating,
        azimuthal_gap_deg=candidate.azimuthal_gap_deg,
        condition_number=candidate.condition_number,
        rank=candidate.rank,
        uncertainty_semi_major_km=candidate.uncertainty_semi_major_km,
        uncertainty_semi_minor_km=candidate.uncertainty_semi_minor_km,
        uncertainty_rotation_deg=candidate.uncertainty_rotation_deg,
        depth_fixed=candidate.depth_fixed,
        selected=candidate.selected,
        residuals=[
            ResidualOut(
                pick_id=residual.pick_id,
                station_code=residual.station_code,
                phase=residual.phase,
                observed_offset_s=residual.observed_offset_s,
                predicted_offset_s=residual.predicted_offset_s,
                residual_s=residual.residual_s,
                distance_km=residual.distance_km,
                used=residual.used,
                status=residual.status,
                note=residual.note,
            )
            for residual in residuals
        ],
    )


def serialize_run(run: LocationRun) -> LocationRunOut:
    origin_time = run.scenario.origin_time
    candidates = sorted(run.candidates, key=lambda item: item.id)
    return LocationRunOut(
        id=run.id,
        scenario_id=run.scenario_id,
        pick_set_id=run.pick_set_id,
        model_name=run.model_name,
        model_version=run.model_version,
        data_version=run.data_version,
        picks_version=run.picks_version,
        phase=run.phase,
        fixed_depth_km=run.fixed_depth_km,
        input_hash=run.input_hash,
        locatable=run.locatable,
        reason=run.reason,
        warning=run.warning,
        selected_candidate_id=run.selected_candidate_id,
        created_at=run.created_at,
        candidates=[
            _serialize_candidate(run, candidate, origin_time)
            for candidate in candidates
        ],
    )


def run_location(
    db: Session,
    scenario: Scenario,
    pick_set: PickSet,
    *,
    phase: str,
    fixed_depth_km: float | None,
    outlier_threshold_s: float,
    include_free_depth: bool,
    model_name: str,
    model_version: str,
    p_velocity: float,
    s_velocity: float,
) -> LocationRun:
    if fixed_depth_km is not None and fixed_depth_km < 0:
        raise ValueError("固定深度不能为负值。")
    observations = _build_observations(pick_set.picks, phase)
    if not observations:
        raise ValueError(f"拾取集中不存在 {phase} 震相。")

    velocity = p_velocity if phase == "P" else s_velocity
    chosen_depth = fixed_depth_km if fixed_depth_km is not None else None
    input_payload = {
        "scenario_id": scenario.id,
        "data_version": scenario.data_version,
        "pick_set_id": pick_set.id,
        "picks_version": pick_set.version,
        "phase": phase,
        "fixed_depth_km": chosen_depth,
        "outlier_threshold_s": outlier_threshold_s,
        "include_free_depth": include_free_depth,
        "model_version": model_version,
        "velocity": velocity,
        "picks": [
            {
                "pick_id": item.pick_id,
                "station": item.station_code,
                "offset_s": item.observed_offset_s,
                "status": item.status,
            }
            for item in sorted(observations, key=lambda item: item.station_code)
        ],
    }
    input_hash = make_input_hash(input_payload)
    candidates, reasons = solve_candidates(
        observations,
        velocity,
        chosen_depth,
        outlier_threshold_s,
        include_free_depth,
    )

    # Geometry diagnostics are also useful when no numerical candidate is retained.
    observed_points = [
        (item.x, item.y) for item in observations if item.observed_offset_s is not None
    ]
    warnings: list[str] = []
    if observed_points:
        import numpy as np

        condition, _rank, gap, rating = geometry_metrics(np.array(observed_points))
        if rating in {"poor", "fair"}:
            warnings.append(
                f"原始有效台站覆盖为 {rating}；方位空挡 "
                f"{gap:.1f}°，条件数 {condition:.1f}。"
            )

    run = LocationRun(
        scenario_id=scenario.id,
        pick_set_id=pick_set.id,
        model_name=model_name,
        model_version=model_version,
        data_version=scenario.data_version,
        picks_version=pick_set.version,
        phase=phase,
        fixed_depth_km=chosen_depth,
        input_hash=input_hash,
        locatable=bool(candidates),
        reason="；".join(reasons),
        warning="；".join(warnings),
    )
    db.add(run)
    db.flush()

    selected = min(candidates, key=candidate_sort_key) if candidates else None
    for index, result in enumerate(sorted(candidates, key=candidate_sort_key)):
        origin_time = origin_time_for(result, scenario.origin_time)
        candidate = LocationCandidate(
            run_id=run.id,
            label=result.label,
            method=result.method,
            x_km=result.x,
            y_km=result.y,
            z_km=result.z,
            origin_time=origin_time,
            rms_residual_s=result.rms,
            max_abs_residual_s=result.max_abs,
            used_pick_count=sum(result.used),
            rejected_pick_count=sum(not used for used in result.used),
            coverage_rating=result.coverage_rating,
            azimuthal_gap_deg=result.azimuthal_gap,
            condition_number=result.condition_number,
            rank=result.rank,
            uncertainty_semi_major_km=result.semi_major,
            uncertainty_semi_minor_km=result.semi_minor,
            uncertainty_rotation_deg=result.rotation,
            depth_fixed=result.depth_fixed,
            selected=result is selected,
        )
        db.add(candidate)
        db.flush()

        for observation, predicted, residual, distance, used in zip(
            observations,
            result.predicted,
            result.residuals,
            result.distances,
            result.used,
        ):
            db.add(
                PickResidual(
                    candidate_id=candidate.id,
                    pick_id=observation.pick_id,
                    station_code=observation.station_code,
                    phase=observation.phase,
                    observed_offset_s=observation.observed_offset_s,
                    predicted_offset_s=predicted,
                    residual_s=residual,
                    distance_km=distance,
                    used=used and observation.observed_offset_s is not None,
                    status=(
                        "missing"
                        if observation.observed_offset_s is None
                        else "outlier"
                        if not used
                        else observation.status
                    ),
                    note=observation.note,
                )
            )
        if result is selected:
            run.selected_candidate_id = candidate.id

    db.commit()
    db.refresh(run)
    return run


def list_runs(db: Session, scenario_id: str):
    return (
        db.query(LocationRun)
        .filter(LocationRun.scenario_id == scenario_id)
        .order_by(LocationRun.created_at.desc(), LocationRun.id.desc())
        .all()
    )


def get_run(db: Session, run_id: int) -> LocationRun | None:
    return (
        db.query(LocationRun)
        .options(
            joinedload(LocationRun.candidates).joinedload(LocationCandidate.residuals)
        )
        .filter(LocationRun.id == run_id)
        .one_or_none()
    )

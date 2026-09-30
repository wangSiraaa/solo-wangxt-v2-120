from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from obspy import Stream, Trace, UTCDateTime


@dataclass(frozen=True)
class StationSpec:
    code: str
    name: str
    x: float
    y: float
    elevation_km: float = 0.0


@dataclass(frozen=True)
class PickSpec:
    station_code: str
    phase: str
    offset_s: float | None  # None means an explicit missing/missed pick
    status: str = "observed"
    quality: str = "automatic"
    note: str = ""


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    name: str
    description: str
    data_version: str
    origin_time: datetime
    source: tuple[float, float, float]
    stations: tuple[StationSpec, ...]
    raw_picks: tuple[PickSpec, ...]
    manual_picks: tuple[PickSpec, ...] | None
    manual_note: str
    teaching_note: str


MODEL_VERSION = "homogeneous-halfspace-v1"
P_VELOCITY = 6.0
S_VELOCITY = 3.5
ORIGIN = datetime(2026, 9, 30, 8, 0, 0, tzinfo=timezone.utc)


def scenario_specs() -> list[ScenarioSpec]:
    good_stations = (
        StationSpec("ST01", "北平台", 0.0, 25.0),
        StationSpec("ST02", "东港台", 28.0, -8.0),
        StationSpec("ST03", "南西站", -18.0, -24.0),
        StationSpec("ST04", "西山台", -26.0, 10.0),
        StationSpec("ST05", "远东台", 34.0, 22.0),
    )
    source = (2.0, 1.0, 8.0)

    def make_pick(stations: tuple[StationSpec, ...], phase: str, overrides=None):
        overrides = overrides or {}
        velocity = P_VELOCITY if phase == "P" else S_VELOCITY
        picks = []
        rng_seed = 100 if phase == "P" else 200
        for index, station in enumerate(stations):
            if station.code in overrides:
                value = overrides[station.code]
                if value is None:
                    picks.append(
                        PickSpec(
                            station.code,
                            phase,
                            None,
                            status="missing",
                            quality="missing",
                            note="未拾取到该震相",
                        )
                    )
                else:
                    picks.append(
                        PickSpec(
                            station.code,
                            phase,
                            value[0],
                            status=value[1],
                            quality=value[2],
                            note=value[3],
                        )
                    )
                continue
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(source, (station.x, station.y, -station.elevation_km)))
            )
            rng = np.random.default_rng(rng_seed + index)
            noise = rng.normal(0.0, 0.05 if phase == "P" else 0.09)
            picks.append(PickSpec(station.code, phase, distance / velocity + noise))
        return tuple(picks)

    good_p = make_pick(good_stations, "P")
    good_s = make_pick(good_stations, "S")
    controlled_raw = good_p + good_s

    # One grossly late P and one omitted P show residual/outlier handling.
    true_p = {p.station_code: p for p in good_p}
    outlier_p = list(good_p)
    st02 = true_p["ST02"]
    outlier_p[1] = PickSpec(
        "ST02",
        "P",
        st02.offset_s + 3.2,
        status="outlier",
        quality="suspect",
        note="合成离群到时：晚到 3.2 s",
    )
    outlier_p[3] = PickSpec(
        "ST04",
        "P",
        None,
        status="missing",
        quality="missing",
        note="合成缺测 P 到时",
    )
    outlier_raw = tuple(outlier_p) + good_s

    # Manual set keeps all five P, correcting the late ST02 and restoring ST04.
    manual_p = (
        PickSpec("ST01", "P", true_p["ST01"].offset_s, note="沿用原始 P"),
        PickSpec(
            "ST02",
            "P",
            true_p["ST02"].offset_s,
            status="revised",
            quality="manual",
            note="人工剔除 3.2 s 偏差并改回",
        ),
        PickSpec("ST03", "P", true_p["ST03"].offset_s, note="沿用原始 P"),
        PickSpec(
            "ST04",
            "P",
            true_p["ST04"].offset_s,
            status="revised",
            quality="manual",
            note="人工补拾 ST04 P 波",
        ),
        PickSpec("ST05", "P", true_p["ST05"].offset_s, note="沿用原始 P"),
    )
    outlier_manual = manual_p + good_s

    collinear_stations = (
        StationSpec("CL1", "共线 1", -30.0, 0.0),
        StationSpec("CL2", "共线 2", -15.0, 0.05),
        StationSpec("CL3", "共线 3", 5.0, -0.04),
        StationSpec("CL4", "共线 4", 20.0, 0.03),
        StationSpec("CL5", "共线 5", 35.0, -0.02),
    )
    collinear_p = make_pick(collinear_stations, "P")
    collinear_s = make_pick(collinear_stations, "S")

    sparse_stations = (
        StationSpec("SP1", "稀疏台 1", -12.0, 0.0),
        StationSpec("SP2", "稀疏台 2", 18.0, 2.0),
    )
    sparse_p = make_pick(sparse_stations, "P")
    sparse_s = make_pick(sparse_stations, "S")

    return [
        ScenarioSpec(
            "controlled-known",
            "已知源：良好几何覆盖",
            "5 个方位分布较好的合成台站；源位置在教学界面中可揭示。",
            "synthetic-v1.0",
            ORIGIN,
            source,
            good_stations,
            controlled_raw,
            None,
            "",
            "基准案例：比较候选解、残差和线性化不确定度；候选坐标不是唯一真值。",
        ),
        ScenarioSpec(
            "outlier-manual-demo",
            "离群到时、缺测与人工修订",
            "5 个台站，其中 ST02 的 P 到时晚 3.2 s，ST04 缺测 P；另有人工修订集。",
            "synthetic-v1.0",
            ORIGIN,
            source,
            good_stations,
            outlier_raw,
            outlier_manual,
            "人工修订原始拾取：修正 ST02、补拾 ST04；原始数据不会被覆盖。",
            "观察稳健拟合如何标记离群值，再切换人工修订集比较结果。",
        ),
        ScenarioSpec(
            "near-collinear",
            "台站几乎共线",
            "5 个台站沿一条近直线布设，震中在垂直方向上缺少几何约束。",
            "synthetic-v1.0",
            ORIGIN,
            source,
            collinear_stations,
            collinear_p + collinear_s,
            None,
            "",
            "几何病态案例：条件数和方位空挡应提示不可稳定定位。",
        ),
        ScenarioSpec(
            "too-few-stations",
            "台站不足：不可定位",
            "仅有 2 个台站；无论波形多清晰，都不能恢复完整事件位置。",
            "synthetic-v1.0",
            ORIGIN,
            source,
            sparse_stations,
            sparse_p + sparse_s,
            None,
            "",
            "明确报告数据不足，不输出伪精确坐标。",
        ),
    ]


def _wavelet(times: np.ndarray, arrival: float, frequency: float, amplitude: float) -> np.ndarray:
    tau = times - arrival
    envelope = np.exp(-((tau / 0.22) ** 2))
    return amplitude * envelope * np.sin(2.0 * np.pi * frequency * tau)


def make_trace(spec: ScenarioSpec, station: StationSpec, sample_dir: Path) -> dict:
    sampling_rate = 50.0
    duration = 40.0
    times = np.arange(0.0, duration, 1.0 / sampling_rate)
    rng = np.random.default_rng(abs(hash((spec.id, station.code))) % (2**32))
    data = rng.normal(0.0, 0.015, times.size)

    distance_3d = math.sqrt(
        (spec.source[0] - station.x) ** 2
        + (spec.source[1] - station.y) ** 2
        + (spec.source[2] + station.elevation_km) ** 2
    )
    p_arrival = distance_3d / P_VELOCITY
    s_arrival = distance_3d / S_VELOCITY
    data += _wavelet(times, p_arrival, 3.0, 1.0)
    data += _wavelet(times, s_arrival, 1.6, 0.75)

    # Subtle, deterministic cultural noise helps students see why picks have uncertainty.
    data += 0.025 * np.sin(2.0 * np.pi * 0.4 * times + station.x)
    counts = (data * 1e5).astype(np.float32)

    start = UTCDateTime(spec.origin_time)
    trace = Trace(data=counts)
    trace.stats.network = "TEACH"
    trace.stats.station = station.code
    trace.stats.channel = "HHZ"
    trace.stats.sampling_rate = sampling_rate
    trace.stats.starttime = start
    stream = Stream(traces=[trace])

    sample_dir.mkdir(parents=True, exist_ok=True)
    path = sample_dir / f"{spec.id}_{station.code}.mseed"
    stream.write(str(path), format="MSEED")

    return {
        "file": str(path),
        "start_time": spec.origin_time.isoformat(),
        "sampling_rate_hz": sampling_rate,
        "true_p_arrival_s": p_arrival,
        "true_s_arrival_s": s_arrival,
    }


def write_all_waveforms(sample_dir: Path) -> dict[str, dict]:
    manifest = {}
    sample_dir.mkdir(parents=True, exist_ok=True)
    for spec in scenario_specs():
        for station in spec.stations:
            manifest[f"{spec.id}:{station.code}"] = make_trace(spec, station, sample_dir)
    (sample_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def load_trace(path: str, max_points: int = 2400):
    from obspy import read

    stream = read(path, format="MSEED")
    trace = stream[0]
    step = max(1, int(trace.data.size // max_points))
    times = trace.times()[::step].astype(float).tolist()
    counts = trace.data[::step].astype(float).tolist()
    start = trace.stats.starttime.datetime.replace(tzinfo=timezone.utc)
    return trace, times, counts, start

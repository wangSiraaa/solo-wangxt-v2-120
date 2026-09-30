from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .crud import (
    create_manual_revision,
    get_run,
    get_scenario,
    list_runs,
    list_scenarios,
    resolve_pick_set,
    run_location,
    serialize_detail,
    serialize_pick,
    serialize_pick_set,
    serialize_run,
    serialize_summary,
)
from .database import get_db
from .models import Pick, PickSet
from .schemas import (
    LocationRequest,
    LocationRunOut,
    PickSetOut,
    RevisionRequest,
    RevisionResponse,
    RunSummary,
    ScenarioDetail,
    ScenarioSummary,
    TraceOut,
    VelocityModelOut,
    WaveformResponse,
)
from .seed import initialize_database
from .synthetic import load_trace


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database(reseed=False)
    yield


app = FastAPI(
    title="Geophysical Teaching Location Service",
    description=(
        "教学用波形到时定位演示。模型和数据版本显式绑定；不用于真实地震预警或业务定位。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "geophysics-teaching"}


@app.get("/api/model", response_model=VelocityModelOut)
def velocity_model():
    return VelocityModelOut(
        name=settings.model_name,
        version=settings.model_version,
        description=(
            "显式简化的均匀半空间模型；震源和台站均位于局部 km 笛卡尔坐标，走时按直达波直线路径计算。"
            "定位时只能选择 P 或 S 单一震相，不做 P/S 混合反演。"
        ),
        p_velocity_km_s=settings.p_velocity_km_s,
        s_velocity_km_s=settings.s_velocity_km_s,
        fixed_default_depth_km=settings.default_depth_km,
        assumptions=[
            f"P 波速度恒定为 {settings.p_velocity_km_s:g} km/s。",
            f"S 波速度恒定为 {settings.s_velocity_km_s:g} km/s。",
            "忽略地壳分层、速度横向变化、台站校正、椭球和高程校正。",
            "走时 = 三维欧氏距离 / 所选震相速度。",
            "一次定位请求只使用同一震相；P 与 S 不混用。",
            "默认固定深度 8 km 用于教学；也可请求自由深度候选以观察权衡。",
        ],
    )


@app.get("/api/scenarios", response_model=list[ScenarioSummary])
def scenarios(db: Session = Depends(get_db)):
    return [serialize_summary(item) for item in list_scenarios(db)]


@app.get("/api/scenarios/{scenario_id}", response_model=ScenarioDetail)
def scenario_detail(
    scenario_id: str,
    reveal_truth: bool = Query(False, description="教学开关：揭示已知合成源位置。"),
    db: Session = Depends(get_db),
):
    scenario = get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="案例不存在。")
    return serialize_detail(scenario, reveal_truth=reveal_truth)


@app.get("/api/scenarios/{scenario_id}/waveforms", response_model=WaveformResponse)
def waveforms(
    scenario_id: str,
    pick_set_id: int | None = Query(None),
    phase: str = Query("P", pattern="^[PS]$"),
    db: Session = Depends(get_db),
):
    scenario = get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="案例不存在。")
    try:
        pick_set = resolve_pick_set(db, scenario, pick_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pick_by_station = {}
    for pick in pick_set.picks:
        if pick.phase == phase:
            pick_by_station[pick.station.code] = pick

    traces = []
    for station in sorted(scenario.stations, key=lambda item: item.code):
        path = Path(station.waveform_file)
        if not path.exists():
            raise HTTPException(
                status_code=500, detail=f"波形文件不存在：{path.name}，请重新生成示例数据。"
            )
        _trace, times, counts, start_time = load_trace(str(path))
        pick = pick_by_station.get(station.code)
        traces.append(
            TraceOut(
                station_code=station.code,
                station_name=station.name,
                x_km=station.x_km,
                y_km=station.y_km,
                start_time=start_time,
                sampling_rate_hz=float(_trace.stats.sampling_rate),
                times_s=times,
                counts=counts,
                picks=[serialize_pick(pick)] if pick else [],
            )
        )
    return WaveformResponse(scenario_id=scenario_id, traces=traces)


@app.post(
    "/api/scenarios/{scenario_id}/revisions",
    response_model=RevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_revision(
    scenario_id: str,
    payload: RevisionRequest,
    db: Session = Depends(get_db),
):
    scenario = get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="案例不存在。")
    try:
        pick_set = create_manual_revision(
            db,
            scenario,
            payload.base_pick_set_id,
            payload.phase,
            payload.revisions,
            payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RevisionResponse(
        pick_set_id=pick_set.id,
        version=pick_set.version,
        copied_pick_count=len(pick_set.picks),
        revised_pick_count=len(payload.revisions),
    )


@app.get(
    "/api/scenarios/{scenario_id}/pick-sets/{pick_set_id}",
    response_model=PickSetOut,
)
def pick_set_detail(scenario_id: str, pick_set_id: int, db: Session = Depends(get_db)):
    scenario = get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="案例不存在。")
    pick_set = db.get(PickSet, pick_set_id)
    if pick_set is None or pick_set.scenario_id != scenario.id:
        raise HTTPException(status_code=404, detail="拾取集不存在。")
    return serialize_pick_set(pick_set)


@app.post(
    "/api/scenarios/{scenario_id}/locate",
    response_model=LocationRunOut,
    status_code=status.HTTP_201_CREATED,
)
def locate(
    scenario_id: str,
    payload: LocationRequest,
    db: Session = Depends(get_db),
):
    scenario = get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="案例不存在。")
    pick_set = (
        db.query(PickSet)
        .options(joinedload(PickSet.picks).joinedload(Pick.station))
        .filter(PickSet.id == payload.pick_set_id, PickSet.scenario_id == scenario_id)
        .one_or_none()
    )
    if pick_set is None:
        raise HTTPException(status_code=404, detail="拾取集不存在。")
    try:
        run = run_location(
            db,
            scenario,
            pick_set,
            phase=payload.phase,
            fixed_depth_km=payload.fixed_depth_km,
            outlier_threshold_s=payload.outlier_threshold_s,
            include_free_depth=payload.include_free_depth,
            model_name=settings.model_name,
            model_version=settings.model_version,
            p_velocity=settings.p_velocity_km_s,
            s_velocity=settings.s_velocity_km_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_run(get_run(db, run.id))


@app.get("/api/scenarios/{scenario_id}/runs", response_model=list[RunSummary])
def runs(scenario_id: str, db: Session = Depends(get_db)):
    scenario = get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="案例不存在。")
    return list_runs(db, scenario_id)


@app.get("/api/runs/{run_id}", response_model=LocationRunOut)
def run_detail(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="定位结果不存在。")
    return serialize_run(run)

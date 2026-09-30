from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StationOut(BaseModel):
    id: int
    code: str
    name: str
    x_km: float
    y_km: float
    elevation_km: float


class PickOut(BaseModel):
    id: int
    station_id: int
    station_code: str
    phase: Literal["P", "S"]
    pick_time: datetime | None
    arrival_time_offset_s: float | None
    quality: str
    status: str
    note: str


class PickSetOut(BaseModel):
    id: int
    kind: Literal["raw", "manual"]
    version: str
    parent_set_id: int | None
    note: str
    created_at: datetime
    picks: list[PickOut]


class ScenarioSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    data_version: str
    station_count: int
    teaching_note: str = Field(serialization_alias="expected_teaching_note")


class ScenarioDetail(ScenarioSummary):
    origin_time: datetime
    source_x_km: float | None = None
    source_y_km: float | None = None
    source_z_km: float | None = None
    reveal_truth: bool = False
    stations: list[StationOut]
    pick_sets: list[PickSetOut]


class VelocityModelOut(BaseModel):
    name: str
    version: str
    description: str
    p_velocity_km_s: float
    s_velocity_km_s: float
    fixed_default_depth_km: float
    assumptions: list[str]


class TraceOut(BaseModel):
    station_code: str
    station_name: str
    x_km: float
    y_km: float
    start_time: datetime
    sampling_rate_hz: float
    times_s: list[float]
    counts: list[float]
    picks: list[PickOut]


class WaveformResponse(BaseModel):
    scenario_id: str
    traces: list[TraceOut]


class PickRevision(BaseModel):
    station_code: str
    phase: Literal["P", "S"]
    arrival_time_offset_s: float | None = Field(
        default=None, description="Null marks an explicit missing/unusable pick."
    )
    status: Literal["observed", "missing", "outlier", "revised"] = "revised"
    note: str = "人工修订"


class RevisionRequest(BaseModel):
    base_pick_set_id: int | None = None
    phase: Literal["P", "S"]
    note: str = "人工修订拾取集"
    revisions: list[PickRevision]


class RevisionResponse(BaseModel):
    pick_set_id: int
    version: str
    copied_pick_count: int
    revised_pick_count: int


class LocationRequest(BaseModel):
    pick_set_id: int
    phase: Literal["P", "S"]
    fixed_depth_km: float | None = 8.0
    outlier_threshold_s: float = 1.5
    include_free_depth: bool = True


class ResidualOut(BaseModel):
    pick_id: int
    station_code: str
    phase: str
    observed_offset_s: float | None
    predicted_offset_s: float | None
    residual_s: float | None
    distance_km: float | None
    used: bool
    status: str
    note: str


class CandidateOut(BaseModel):
    id: int
    label: str
    method: str
    x_km: float
    y_km: float
    z_km: float
    origin_time: datetime
    origin_time_offset_s: float
    rms_residual_s: float | None
    max_abs_residual_s: float | None
    used_pick_count: int
    rejected_pick_count: int
    coverage_rating: str
    azimuthal_gap_deg: float | None
    condition_number: float | None
    rank: int | None
    uncertainty_semi_major_km: float | None
    uncertainty_semi_minor_km: float | None
    uncertainty_rotation_deg: float | None
    depth_fixed: bool
    selected: bool
    residuals: list[ResidualOut]


class LocationRunOut(BaseModel):
    id: int
    scenario_id: str
    pick_set_id: int
    model_name: str
    model_version: str
    data_version: str
    picks_version: str
    phase: str
    fixed_depth_km: float | None
    input_hash: str
    locatable: bool
    reason: str
    warning: str
    selected_candidate_id: int | None
    created_at: datetime
    candidates: list[CandidateOut]


class RunSummary(BaseModel):
    id: int
    scenario_id: str
    pick_set_id: int
    model_version: str
    data_version: str
    picks_version: str
    phase: str
    locatable: bool
    reason: str
    created_at: datetime

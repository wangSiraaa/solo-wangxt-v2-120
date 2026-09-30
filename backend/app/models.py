from __future__ import annotations

from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    origin_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_x_km: Mapped[float] = mapped_column(Float, nullable=False)
    source_y_km: Mapped[float] = mapped_column(Float, nullable=False)
    source_z_km: Mapped[float] = mapped_column(Float, nullable=False)
    source_geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINTZ", srid=0, dimension=3), nullable=False
    )
    expected_teaching_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    stations: Mapped[list[Station]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", order_by="Station.code"
    )
    pick_sets: Mapped[list[PickSet]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class Station(Base):
    __tablename__ = "stations"
    __table_args__ = (UniqueConstraint("scenario_id", "code", name="uq_station_scenario_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    x_km: Mapped[float] = mapped_column(Float, nullable=False)
    y_km: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINTZ", srid=0, dimension=3), nullable=False
    )
    waveform_file: Mapped[str] = mapped_column(String(512), nullable=False)

    scenario: Mapped[Scenario] = relationship(back_populates="stations")
    picks: Mapped[list[Pick]] = relationship(
        back_populates="station", cascade="all, delete-orphan"
    )


class PickSet(Base):
    __tablename__ = "pick_sets"
    __table_args__ = (
        UniqueConstraint("scenario_id", "kind", "version", name="uq_pickset_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    parent_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("pick_sets.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # raw | manual
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="pick_sets")
    picks: Mapped[list[Pick]] = relationship(
        back_populates="pick_set", cascade="all, delete-orphan"
    )
    runs: Mapped[list[LocationRun]] = relationship(back_populates="pick_set")


class Pick(Base):
    __tablename__ = "picks"
    __table_args__ = (
        UniqueConstraint(
            "pick_set_id", "station_id", "phase", name="uq_pick_station_phase"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pick_set_id: Mapped[int] = mapped_column(ForeignKey("pick_sets.id", ondelete="CASCADE"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(2), nullable=False)  # P | S, never mixed
    pick_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrival_time_offset_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[str] = mapped_column(String(32), default="automatic", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="observed", nullable=False)
    # observed/missing/outlier/revised. Missing rows preserve the expected slot explicitly.
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    pick_set: Mapped[PickSet] = relationship(back_populates="picks")
    station: Mapped[Station] = relationship(back_populates="picks")
    residuals: Mapped[list[PickResidual]] = relationship(
        back_populates="pick", cascade="all, delete-orphan"
    )


class LocationRun(Base):
    __tablename__ = "location_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    pick_set_id: Mapped[int] = mapped_column(ForeignKey("pick_sets.id", ondelete="CASCADE"))
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    picks_version: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(2), nullable=False)
    fixed_depth_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    locatable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    warning: Mapped[str] = mapped_column(Text, default="", nullable=False)
    selected_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "location_candidates.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_location_runs_selected_candidate",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario: Mapped[Scenario] = relationship()
    pick_set: Mapped[PickSet] = relationship(back_populates="runs")
    candidates: Mapped[list[LocationCandidate]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        foreign_keys="LocationCandidate.run_id",
    )


class LocationCandidate(Base):
    __tablename__ = "location_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("location_runs.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    x_km: Mapped[float] = mapped_column(Float, nullable=False)
    y_km: Mapped[float] = mapped_column(Float, nullable=False)
    z_km: Mapped[float] = mapped_column(Float, nullable=False)
    origin_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rms_residual_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_abs_residual_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    used_pick_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_pick_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coverage_rating: Mapped[str] = mapped_column(String(32), nullable=False)
    azimuthal_gap_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uncertainty_semi_major_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_semi_minor_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_rotation_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_fixed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[LocationRun] = relationship(
        back_populates="candidates", foreign_keys=[run_id]
    )
    residuals: Mapped[list[PickResidual]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class PickResidual(Base):
    __tablename__ = "pick_residuals"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "pick_id", name="uq_residual_candidate_pick"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("location_candidates.id", ondelete="CASCADE")
    )
    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id", ondelete="CASCADE"))
    station_code: Mapped[str] = mapped_column(String(16), nullable=False)
    phase: Mapped[str] = mapped_column(String(2), nullable=False)
    observed_offset_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_offset_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    used: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    candidate: Mapped[LocationCandidate] = relationship(back_populates="residuals")
    pick: Mapped[Pick] = relationship(back_populates="residuals")

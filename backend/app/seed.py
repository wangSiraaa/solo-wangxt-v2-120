from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, engine
from .models import Pick, PickSet, Scenario, Station
from .synthetic import scenario_specs, write_all_waveforms


def point_z(x: float, y: float, z: float) -> WKTElement:
    # SRID 0 deliberately denotes a local Cartesian teaching coordinate frame in km,
    # not geographic longitude/latitude.
    return WKTElement(f"POINT Z ({x} {y} {z})", srid=0)


def reset_database(db: Session, sample_dir: Path) -> None:
    write_all_waveforms(sample_dir)

    # Ordered delete is explicit even though ORM cascades cover most rows.
    db.execute(text("TRUNCATE pick_residuals, location_candidates, location_runs, picks, pick_sets, stations, scenarios RESTART IDENTITY CASCADE"))
    db.commit()

    for spec in scenario_specs():
        scenario = Scenario(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            data_version=spec.data_version,
            origin_time=spec.origin_time,
            source_x_km=spec.source[0],
            source_y_km=spec.source[1],
            source_z_km=spec.source[2],
            source_geom=point_z(spec.source[0], spec.source[1], spec.source[2]),
            expected_teaching_note=spec.teaching_note,
        )
        db.add(scenario)
        db.flush()

        station_by_code: dict[str, Station] = {}
        for station_spec in spec.stations:
            waveform_file = str(sample_dir / f"{spec.id}_{station_spec.code}.mseed")
            if not Path(waveform_file).exists():
                raise RuntimeError(f"Missing generated waveform: {waveform_file}")
            station = Station(
                scenario_id=spec.id,
                code=station_spec.code,
                name=station_spec.name,
                x_km=station_spec.x,
                y_km=station_spec.y,
                elevation_km=station_spec.elevation_km,
                geom=point_z(
                    station_spec.x,
                    station_spec.y,
                    -station_spec.elevation_km,
                ),
                waveform_file=waveform_file,
            )
            db.add(station)
            db.flush()
            station_by_code[station_spec.code] = station

        def add_pick_set(kind: str, version: str, pick_specs, parent_id: int | None, note: str):
            pick_set = PickSet(
                scenario_id=spec.id,
                parent_set_id=parent_id,
                kind=kind,
                version=version,
                note=note,
            )
            db.add(pick_set)
            db.flush()
            for pick_spec in pick_specs:
                station = station_by_code[pick_spec.station_code]
                pick_time = None
                if pick_spec.offset_s is not None:
                    pick_time = spec.origin_time + timedelta(
                        seconds=pick_spec.offset_s
                    )
                db.add(
                    Pick(
                        pick_set_id=pick_set.id,
                        station_id=station.id,
                        phase=pick_spec.phase,
                        pick_time=pick_time,
                        arrival_time_offset_s=pick_spec.offset_s,
                        quality=pick_spec.quality,
                        status=pick_spec.status,
                        note=pick_spec.note,
                    )
                )
            db.flush()
            return pick_set

        raw_set = add_pick_set(
            "raw",
            "raw-synthetic-v1.0",
            spec.raw_picks,
            None,
            "由合成数据自动生成的原始拾取；缺测和离群均保留审计痕迹。",
        )
        if spec.manual_picks:
            add_pick_set(
                "manual",
                "manual-review-v1.0",
                spec.manual_picks,
                raw_set.id,
                spec.manual_note,
            )
        db.commit()


def initialize_database(reseed: bool = False) -> None:
    settings = get_settings()
    sample_dir = Path(settings.sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)

    max_attempts = int(os.getenv("DB_STARTUP_MAX_ATTEMPTS", "60"))
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                Base.metadata.create_all(bind=connection)
            break
        except Exception as exc:  # pragma: no cover - exercised during container startup
            last_error = exc
            if attempt == max_attempts:
                raise
            time.sleep(1.0)
    else:  # pragma: no cover - defensive loop guard
        raise last_error or RuntimeError("Database initialization failed.")

    with Session(engine) as db:
        existing = db.query(Scenario).count()
        if reseed or existing == 0:
            reset_database(db, sample_dir)

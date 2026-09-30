import math

import numpy as np

from app.location import Observation, geometry_metrics, solve_candidates

VP = 6.0
SOURCE = (2.0, 1.0, 8.0)


def observation(code, x, y, z=0.0, *, pick_id=1, offset=None, status="observed", note=""):
    distance = math.sqrt(
        (SOURCE[0] - x) ** 2 + (SOURCE[1] - y) ** 2 + (SOURCE[2] - z) ** 2
    )
    return Observation(
        pick_id=pick_id,
        station_code=code,
        phase="P",
        x=x,
        y=y,
        z=z,
        observed_offset_s=distance / VP if offset is None else offset,
        status=status,
        note=note,
    )


def test_well_distributed_picks_recover_candidate_and_zero_residuals():
    obs = [
        observation("ST01", 0.0, 25.0, pick_id=1),
        observation("ST02", 28.0, -8.0, pick_id=2),
        observation("ST03", -18.0, -24.0, pick_id=3),
        observation("ST04", -26.0, 10.0, pick_id=4),
    ]
    candidates, reasons = solve_candidates(obs, VP, 8.0, 1.5, True)

    assert candidates
    robust = next(item for item in candidates if item.method == "soft_l1_fixed_depth")
    assert robust.rms < 1e-4
    assert math.hypot(robust.x - SOURCE[0], robust.y - SOURCE[1]) < 0.01
    assert all(used for used in robust.used)
    assert reasons == []


def test_too_few_stations_is_explicitly_unlocatable():
    obs = [observation("SP1", -12.0, 0.0), observation("SP2", 18.0, 2.0)]
    candidates, reasons = solve_candidates(obs, VP, 8.0, 1.5, True)

    assert candidates == []
    assert any("2 个有效到时" in reason for reason in reasons)


def test_outlier_remains_visible_but_is_excluded_from_rms():
    obs = [
        observation("ST01", 0.0, 25.0),
        observation("ST02", 28.0, -8.0, offset=99.0, status="outlier", note="bad"),
        observation("ST03", -18.0, -24.0),
        observation("ST04", -26.0, 10.0),
    ]
    candidates, _ = solve_candidates(obs, VP, 8.0, 1.5, False)
    robust = next(item for item in candidates if item.method == "soft_l1_fixed_depth")
    outlier_index = 1

    assert robust.used[outlier_index] is False
    assert robust.residuals[outlier_index] is not None
    assert abs(robust.residuals[outlier_index]) > 1.0
    assert robust.used_pick_count == 3
    assert robust.rejected_pick_count == 1


def test_near_collinear_layout_is_flagged_as_poor_geometry():
    stations = [(-30.0, 0.0), (-15.0, 0.05), (5.0, -0.04), (20.0, 0.03)]
    obs = [observation(f"CL{i}", x, y) for i, (x, y) in enumerate(stations)]
    _condition, _rank, gap, rating = geometry_metrics(
        np.array([[x, y, 0.0] for x, y in stations])
    )

    assert rating == "poor"
    assert gap > 180.0

    candidates, reasons = solve_candidates(obs, VP, 8.0, 1.5, False)
    assert candidates
    assert any("几何覆盖很差" in reason for reason in reasons)

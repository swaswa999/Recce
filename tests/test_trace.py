"""Timing callouts from a recorded ride.

This exists because a rendered track is open-loop. The modelled profile predicts
an 80 km/h average on the Tail of the Dragon against a 48 km/h posted limit, and
riding it legally puts the track 40 s out of sync inside a minute — 3 s being one
callout's worth of lead. A fixed track is only trustworthy when its timing came
from how the road was actually ridden.
"""
from datetime import datetime, timedelta

import numpy as np
import pytest

from geometry import resample, signed_radius, smooth_radius, SEG_SPACING
from trace import (load_gpx, time_profile_from_trace, speed_from_time_profile,
                   project_onto_road)
from synth_road import build_road


def write_gpx(path, lon, lat, times):
    pts = "".join(
        f'<trkpt lat="{la:.7f}" lon="{lo:.7f}">'
        f"<time>{t.isoformat()}Z</time></trkpt>"
        for lo, la, t in zip(lon, lat, times))
    path.write_text(
        '<?xml version="1.0"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{pts}</trkseg></trk></gpx>")
    return str(path)


@pytest.fixture(scope="module")
def road():
    x, y, z, _, _ = build_road()
    s, xi, yi, _ = resample(x, y, None, spacing=SEG_SPACING)
    return {"x": xi, "y": yi, "s": s}


def synth_trace(road, kmh=50.0, every=4):
    """A trace that follows the road at a constant pace, in lon/lat-ish units."""
    xi, yi, s = road["x"], road["y"], road["s"]
    idx = np.arange(0, len(s), every)
    # invert the projection used by lonlat_to_xy closely enough for a test:
    # treat metres as degrees scaled, since time_profile_from_trace re-centres
    lon = xi[idx] / (111320.0 * np.cos(np.radians(35.0)))
    lat = yi[idx] / 111320.0
    t0 = datetime(2026, 7, 29, 9, 0, 0)
    times = [t0 + timedelta(seconds=float(si / (kmh / 3.6))) for si in s[idx]]
    return lon, lat, times


# --- GPX parsing ----------------------------------------------------------

def test_load_gpx_roundtrip(tmp_path, road):
    lon, lat, times = synth_trace(road)
    p = write_gpx(tmp_path / "r.gpx", lon, lat, times)
    glon, glat, gt = load_gpx(p)
    assert len(glon) == len(lon)
    assert gt[0] == 0.0
    assert gt[-1] == pytest.approx((times[-1] - times[0]).total_seconds(), abs=1)


def test_gpx_without_timestamps_is_rejected(tmp_path):
    (tmp_path / "n.gpx").write_text(
        '<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">'
        '<trk><trkseg><trkpt lat="35.0" lon="-84.0"/></trkseg></trk></gpx>')
    with pytest.raises(SystemExit):
        load_gpx(str(tmp_path / "n.gpx"))


def test_gpx_points_are_sorted_by_time(tmp_path, road):
    """Some loggers interleave segments; timing must not run backwards."""
    lon, lat, times = synth_trace(road)
    order = np.arange(len(lon))[::-1]  # write them reversed
    p = write_gpx(tmp_path / "rev.gpx", lon[order], lat[order],
                  [times[i] for i in order])
    _, _, gt = load_gpx(p)
    assert np.all(np.diff(gt) >= 0), "trace times are not monotonic"


# --- projection and time profile -----------------------------------------

def test_projection_recovers_arc_length(road):
    """A point ON the road must project to its own arc-length position."""
    xi, yi, s = road["x"], road["y"], road["s"]
    pick = np.arange(10, len(s) - 10, 37)
    got = project_onto_road(xi, yi, s, xi[pick], yi[pick])
    assert np.allclose(got, s[pick], atol=SEG_SPACING)


def test_time_profile_is_monotonic(tmp_path, road):
    """The scheduler must never see time run backwards along the road."""
    lon, lat, times = synth_trace(road)
    p = write_gpx(tmp_path / "r.gpx", lon, lat, times)
    glon, glat, gt = load_gpx(p)
    t, rep = time_profile_from_trace(road["s"], road["x"], road["y"],
                                     glon, glat, gt)
    assert len(t) == len(road["s"])
    assert np.all(np.diff(t) >= 0), "time went backwards"
    assert rep["used"] > 0


def test_trace_on_a_different_road_is_refused(road):
    """A logger left running elsewhere must not anchor the timeline."""
    s = road["s"]
    n = 50
    lon = np.linspace(-120.0, -119.9, n)   # nowhere near the road
    lat = np.linspace(40.0, 40.1, n)
    t = np.arange(n, dtype=float) * 5
    with pytest.raises(SystemExit):
        time_profile_from_trace(s, road["x"], road["y"], lon, lat, t)


def test_report_flags_partial_coverage(tmp_path, road):
    """Callouts outside the traced stretch are extrapolated, not validated."""
    lon, lat, times = synth_trace(road)
    half = len(lon) // 2
    p = write_gpx(tmp_path / "h.gpx", lon[:half], lat[:half], times[:half])
    glon, glat, gt = load_gpx(p)
    _, rep = time_profile_from_trace(road["s"], road["x"], road["y"],
                                     glon, glat, gt)
    assert rep["covered_m"] < 0.8 * rep["road_m"]


# --- speed from a trace ---------------------------------------------------

def test_speed_from_trace_matches_the_pace_ridden(road):
    s = road["s"]
    kmh = 45.0
    t = s / (kmh / 3.6)
    v = speed_from_time_profile(s, t)
    assert np.median(v) * 3.6 == pytest.approx(kmh, rel=0.05)


def test_flat_time_regions_do_not_divide_by_zero(road):
    """A stopped rider, or a stretch the trace never covered."""
    s = road["s"]
    t = np.maximum.accumulate(np.where(s < 500, 0.0, (s - 500) / 12.0))
    v = speed_from_time_profile(s, t)
    assert np.all(np.isfinite(v)), "non-finite speed from a flat time region"
    assert np.all(v > 0), "speed must stay positive for the timing model"


def test_grip_clamp_removes_impossible_corner_speed(road):
    """Projection jitter over a short interval implies absurd speed.

    On a real trace this produced 216 km/h and a 65 degree lean through the
    Dragon. The clamp uses the corner radius, so it only removes what is
    physically impossible rather than flattening a fast rider.
    """
    x, y, z, _, _ = build_road()
    _, xi, yi, _ = resample(x, y, None, spacing=SEG_SPACING)
    r = smooth_radius(signed_radius(xi, yi, window=3), k=5)
    s = road["s"]
    t = s / 12.0
    # inject a spike: one interval traversed implausibly fast
    hairpin = int(np.argmin(np.abs(np.abs(r) - np.abs(r).min())))
    t[hairpin + 1:] -= 3.0
    t = np.maximum.accumulate(t)
    unclamped = speed_from_time_profile(s, t, spike_filter=0)
    clamped = speed_from_time_profile(s, t, radius=r, spike_filter=0)
    grip = np.sqrt(9.0 * np.abs(r[hairpin]))
    assert clamped[hairpin] <= grip + 1e-6, (
        f"speed {clamped[hairpin]:.1f} m/s exceeds the {grip:.1f} m/s grip "
        f"limit for a {abs(r[hairpin]):.1f} m radius"
    )
    assert clamped.max() <= unclamped.max() + 1e-9

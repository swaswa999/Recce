"""Time callouts from a RECORDED ride instead of a modelled speed profile.

Why this exists. A rendered track is open-loop: it assumes a speed profile, so
any difference between that and how you actually ride compounds into drift. On
the Tail of the Dragon the model predicts an 80 km/h average against a 48 km/h
posted limit — riding it legally puts you 40 s out of sync inside a minute, and
3 s is one callout's worth of lead. The track is useless as a live copilot.

The cheap honest validation is therefore record-then-review, which is what
"Phase 1 — audio validation" in the roadmap always meant:

  1. Ride the road with any GPS logger running.
  2. Feed the trace in here. Callouts get timed to how you ACTUALLY rode.
  3. Listen afterwards and judge whether each call was right and well-timed.

That separates "are the callouts correct" from "is the speed model right", and
needs no live sync, no app, and no second pass on the bike.

Live GPS-matched playback is the iOS app (Phase E).
"""
import xml.etree.ElementTree as ET
from datetime import datetime

import numpy as np

from geometry import lonlat_to_xy


def load_gpx(path):
    """Read a GPX track. Returns (lon, lat, t_seconds_from_start).

    Accepts any namespace, since exporters vary. Points without a timestamp are
    dropped — timing is the whole point of loading a trace.
    """
    root = ET.parse(path).getroot()
    pts = []
    for el in root.iter():
        if not el.tag.endswith("trkpt"):
            continue
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            continue
        tstamp = None
        for child in el:
            if child.tag.endswith("time") and child.text:
                tstamp = child.text.strip()
                break
        if tstamp is None:
            continue
        pts.append((float(lon), float(lat), _parse_time(tstamp)))
    if len(pts) < 2:
        raise SystemExit(f"{path}: fewer than 2 timestamped track points")
    pts.sort(key=lambda p: p[2])
    lon = np.array([p[0] for p in pts])
    lat = np.array([p[1] for p in pts])
    t0 = pts[0][2]
    t = np.array([(p[2] - t0).total_seconds() for p in pts])
    return lon, lat, t


def _parse_time(s):
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def project_onto_road(road_x, road_y, road_s, trace_x, trace_y, chunk=512):
    """Arc-length position along the road for each trace point.

    Nearest-point projection. Chunked so a long trace against a long road does
    not allocate a full trace x road distance matrix.
    """
    out = np.empty(len(trace_x))
    for i in range(0, len(trace_x), chunk):
        tx = trace_x[i:i + chunk, None]
        ty = trace_y[i:i + chunk, None]
        d2 = (tx - road_x[None, :]) ** 2 + (ty - road_y[None, :]) ** 2
        out[i:i + chunk] = road_s[np.argmin(d2, axis=1)]
    return out


def time_profile_from_trace(road_s, road_x, road_y, trace_lon, trace_lat,
                            trace_t, max_offroad_m=60.0):
    """Build the road's s -> t mapping from a recorded ride.

    Returns (t_grid, report). t_grid aligns with road_s so it drops straight
    into the scheduler in place of speed.time_profile().

    Trace points further than `max_offroad_m` from the road are discarded —
    a logger that was running before you set off, or on a different road,
    would otherwise anchor the timeline to the wrong place.
    """
    tx, ty = lonlat_to_xy(trace_lon, trace_lat)
    # lonlat_to_xy centres on its own input, so re-centre the trace onto the
    # road's frame using the first road point as a common origin.
    tx = tx - tx[0] + road_x[0]
    ty = ty - ty[0] + road_y[0]

    s_proj = project_onto_road(road_x, road_y, road_s, tx, ty)
    d = np.hypot(tx - np.interp(s_proj, road_s, road_x),
                 ty - np.interp(s_proj, road_s, road_y))
    on = d <= max_offroad_m
    if on.sum() < 10:
        raise SystemExit(
            f"only {on.sum()} of {len(tx)} trace points fall within "
            f"{max_offroad_m:.0f} m of the road — wrong road, or the trace and "
            f"road do not overlap")

    s_on, t_on = s_proj[on], trace_t[on]
    order = np.argsort(s_on)
    s_on, t_on = s_on[order], t_on[order]
    # collapse duplicate positions (stops, GPS jitter) to their mean time, then
    # enforce monotonicity so the scheduler cannot see time run backwards
    uniq, idx = np.unique(np.round(s_on, 1), return_index=True)
    t_uniq = np.maximum.accumulate(t_on[idx])

    t_grid = np.interp(road_s, uniq, t_uniq)
    t_grid = np.maximum.accumulate(t_grid)

    covered = (road_s >= uniq[0]) & (road_s <= uniq[-1])
    dist = np.diff(uniq)
    dt = np.diff(t_uniq)
    moving = dt > 0.1
    speeds = dist[moving] / dt[moving] if moving.any() else np.array([0.0])
    report = {
        "trace_points": int(len(tx)),
        "used": int(on.sum()),
        "discarded_offroad": int((~on).sum()),
        "covered_m": float(np.ptp(road_s[covered])) if covered.any() else 0.0,
        "road_m": float(road_s[-1]),
        "duration_s": float(t_uniq[-1] - t_uniq[0]),
        "mean_kmh": float(np.mean(speeds) * 3.6),
        "max_kmh": float(np.percentile(speeds, 98) * 3.6),
    }
    return t_grid, report


def _median_filter(v, k=5):
    """Kill isolated spikes without flattening genuine acceleration."""
    if k < 3 or len(v) < k:
        return v
    h = k // 2
    padded = np.pad(v, h, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, k), axis=-1)


def speed_from_time_profile(s, t, radius=None, v_floor=0.5, v_ceil=45.0,
                            a_lat_max=9.0, spike_filter=5):
    """Speed implied by an s -> t mapping.

    Computed from finite differences with a guarded denominator rather than
    np.gradient(s, t), which needs a strictly increasing t and divides by zero
    wherever the rider was stopped or the trace had no data to interpolate from.

    Pass `radius` to clamp against what is physically possible. Nearest-point
    projection jitters, and a single jittered point over a short interval implies
    an absurd speed — on a real trace this produced 216 km/h and a 65 degree lean
    angle through the Dragon. `a_lat_max` of 9 m/s^2 (~0.92 g) is beyond normal
    road riding, so the clamp only removes clearly impossible spikes rather than
    flattening a genuinely fast rider.

    The grip clamp cannot help on a straight, where the radius is infinite, so a
    short median filter removes isolated spikes there. Both are needed: the
    filter alone would let a run of jittered points through, and the clamp alone
    left 216 km/h on the straights.
    """
    ds = np.diff(s)
    dt = np.diff(t)
    v_mid = ds / np.maximum(dt, 1e-3)
    v = np.empty_like(s, dtype=float)
    v[0] = v_mid[0]
    v[-1] = v_mid[-1]
    v[1:-1] = 0.5 * (v_mid[:-1] + v_mid[1:])
    v = np.nan_to_num(v, nan=v_floor)
    if spike_filter:
        v = _median_filter(v, spike_filter)
    if radius is not None:
        grip = np.sqrt(a_lat_max * np.abs(np.asarray(radius, dtype=float)))
        grip = np.nan_to_num(grip, nan=v_ceil, posinf=v_ceil)
        v = np.minimum(v, np.maximum(grip, v_floor))
    return np.clip(v, v_floor, v_ceil)


def format_report(rep):
    cover = 100.0 * rep["covered_m"] / max(rep["road_m"], 1.0)
    lines = [
        f"trace: {rep['used']}/{rep['trace_points']} points used "
        f"({rep['discarded_offroad']} discarded as off-road)",
        f"  covers {rep['covered_m'] / 1000:.1f} km of "
        f"{rep['road_m'] / 1000:.1f} km ({cover:.0f}%)",
        f"  {rep['duration_s'] / 60:.1f} min, mean {rep['mean_kmh']:.0f} km/h, "
        f"p98 {rep['max_kmh']:.0f} km/h",
    ]
    if cover < 80:
        lines.append("  *** trace covers less than 80% of the road: callouts "
                     "outside the covered stretch are timed by extrapolation "
                     "and are NOT validated")
    return "\n".join(lines)

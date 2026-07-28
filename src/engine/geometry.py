"""Geometry core: resample a road polyline and compute signed curve radius.

Works in local ENU meters. Input can be lon/lat (WGS84) or already-metric XY.
"""
import numpy as np

EARTH_R = 6371000.0

# Two grids, because segmentation and measurement want opposite things.
#
# SEG_SPACING: finding WHERE corners start and end wants a wide, stable
# estimate. This is the Phase 0 validated value and must not be tuned casually
# — a single estimator doing both jobs fragmented the road into phantom corners
# with false "opens" modifiers.
#
# FINE_SPACING: measuring HOW TIGHT a corner is wants a short window, applied
# only inside a corner already found on the coarse grid.
#
# See docs/ARCHITECTURE.md, "Two-scale curvature estimation".
SEG_SPACING = 5.0
FINE_SPACING = 2.0


def lonlat_to_xy(lon, lat):
    """Equirectangular projection around the centroid. Good enough for a road."""
    lat0 = np.radians(np.mean(lat))
    x = np.radians(lon) * EARTH_R * np.cos(lat0)
    y = np.radians(lat) * EARTH_R
    return x - x[0], y - y[0]


def resample(x, y, z=None, spacing=5.0):
    """Resample polyline to even arc-length spacing (meters)."""
    d = np.hypot(np.diff(x), np.diff(y))
    s = np.concatenate([[0.0], np.cumsum(d)])
    # drop duplicate points
    keep = np.concatenate([[True], np.diff(s) > 1e-6])
    s, x, y = s[keep], x[keep], y[keep]
    if z is not None:
        z = z[keep]
    s_new = np.arange(0.0, s[-1], spacing)
    xi = np.interp(s_new, s, x)
    yi = np.interp(s_new, s, y)
    zi = np.interp(s_new, s, z) if z is not None else None
    return s_new, xi, yi, zi


def signed_radius(x, y, window=3):
    """Signed circumradius at each point using points i-w, i, i+w.

    Positive = left turn, negative = right turn (right-hand traffic frame:
    cross product of travel vectors). Returns radius in meters, inf on straights.
    """
    n = len(x)
    r = np.full(n, np.inf)
    w = window
    ax, ay = x[: n - 2 * w], y[: n - 2 * w]
    bx, by = x[w : n - w], y[w : n - w]
    cx, cy = x[2 * w :], y[2 * w :]
    # side lengths
    a = np.hypot(bx - ax, by - ay)
    b = np.hypot(cx - bx, cy - by)
    c = np.hypot(cx - ax, cy - ay)
    # signed area *2 (cross product)
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    area2 = np.abs(cross)
    with np.errstate(divide="ignore", invalid="ignore"):
        radius = (a * b * c) / (2.0 * area2)
    radius = np.where(area2 < 1e-9, np.inf, radius)
    sign = np.sign(cross)  # + = left
    r[w : n - w] = radius * np.where(sign == 0, 1, sign)
    # copy edge values outward
    r[:w] = r[w]
    r[n - w :] = r[n - w - 1]
    return r


def smooth_radius(r, k=5):
    """Rolling median on curvature (1/r) to kill GPS/geometry noise.

    This is the SEGMENTATION estimator: wide and stable, which is what finding
    corner boundaries needs. It deliberately flattens curvature peaks, so it
    must NOT be used to measure how tight a corner is — that reads optimistic.
    Use confined_arc_profile() for the measurement.
    """
    curv = np.where(np.isinf(r), 0.0, 1.0 / r)
    n = len(curv)
    out = np.copy(curv)
    h = k // 2
    for i in range(n):
        lo, hi = max(0, i - h), min(n, i + h + 1)
        out[i] = np.median(curv[lo:hi])
    with np.errstate(divide="ignore"):
        rs = np.where(np.abs(out) < 1e-9, np.inf, 1.0 / out)
    return rs


def fit_circle_radius(x, y):
    """Least-squares (Kasa) circle fit. Returns radius in meters, inf if the
    points are collinear or too few to constrain a circle.

    More stable than a 3-point circumcircle at short windows, which is what
    makes short-window fitting viable at all.
    """
    n = len(x)
    if n < 4:
        return np.inf
    u = x - x.mean()
    v = y - y.mean()
    Suu = float((u * u).sum())
    Svv = float((v * v).sum())
    Suv = float((u * v).sum())
    b1 = 0.5 * float((u ** 3).sum() + (u * v * v).sum())
    b2 = 0.5 * float((v ** 3).sum() + (v * u * u).sum())
    det = Suu * Svv - Suv * Suv
    if abs(det) < 1e-12:
        return np.inf
    uc = (b1 * Svv - b2 * Suv) / det
    vc = (b2 * Suu - b1 * Suv) / det
    r2 = uc * uc + vc * vc + (Suu + Svv) / n
    return float(np.sqrt(r2)) if r2 > 0 else np.inf


def _turn_sign(x, y, spacing, span=8.0):
    """+1 left, -1 right, from the cross product of travel vectors."""
    n = len(x)
    w = max(1, int(round(span / spacing)))
    sign = np.ones(n)
    if n < 2 * w + 1:
        return sign
    ax, ay = x[: n - 2 * w], y[: n - 2 * w]
    bx, by = x[w : n - w], y[w : n - w]
    cx, cy = x[2 * w :], y[2 * w :]
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    sign[w : n - w] = np.where(cross >= 0, 1.0, -1.0)
    sign[:w] = sign[w]
    sign[n - w :] = sign[n - w - 1]
    return sign


def confined_arc_profile(x, y, spacing, seed, lo, hi, frac=0.12,
                         min_half=10.0, max_half=60.0, min_pts=7):
    """Unsigned radius profile for the slice [lo, hi), measured with short
    least-squares arc fits that NEVER extend outside that slice.

    Why confinement is the whole point: a symmetric window centred near the end
    of a corner reaches into the adjoining straight, where curvature is zero, so
    the fit averages the corner with a straight and reports a radius flatter
    than the road. That boundary bleed — not the rolling median — was the main
    source of the optimistic bias. Clamping the window to the corner's own
    extent removes it, and by construction cannot invent curvature outside a
    corner that segmentation already found.

    `seed` is the coarse, stable radius estimate used only to size windows, so
    the window length never depends on this function's own noisy output. An
    earlier version fed the output back in and diverged: noise -> small radius
    -> shorter window -> more noise.

    `frac` is window half-length as a fraction of local radius; smaller is more
    accurate on clean geometry and more noise-sensitive. See
    docs/ARCHITECTURE.md, "Two-scale curvature estimation".
    """
    span = hi - lo
    out = np.full(max(span, 0), np.inf)
    if span <= 0:
        return out
    need = max(min_pts, 4)
    for j in range(span):
        i = lo + j
        si = abs(seed[i]) if i < len(seed) else np.inf
        half = (max_half if not np.isfinite(si)
                else float(np.clip(frac * si, min_half, max_half)))
        k = max(2, int(round(half / spacing)))
        a, b = max(lo, i - k), min(hi, i + k + 1)
        # widen inside the corner only; never step outside [lo, hi)
        if b - a < need:
            deficit = need - (b - a)
            a = max(lo, a - deficit)
            b = min(hi, b + (need - (b - a)))
        if b - a < 4:
            out[j] = si
            continue
        out[j] = fit_circle_radius(x[a:b], y[a:b])
    return out


def node_spacing_stats(x, y):
    """Spacing of the RAW input nodes, before any resampling.

    Returns (median, p90, max) in meters. The median bounds how much curvature
    detail the geometry can actually support: resampling finer than the survey
    manufactures kinks that a short-window fit reads as real curvature. Used by
    run_real.py to warn on roads too sparse to trust.
    """
    d = np.hypot(np.diff(x), np.diff(y))
    d = d[d > 1e-9]
    if len(d) == 0:
        return 0.0, 0.0, 0.0
    return float(np.median(d)), float(np.percentile(d, 90)), float(np.max(d))

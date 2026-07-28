"""Geometry core: resample a road polyline and compute signed curve radius.

Works in local ENU meters. Input can be lon/lat (WGS84) or already-metric XY.
"""
import numpy as np

EARTH_R = 6371000.0


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
    """Rolling median on curvature (1/r) to kill GPS/geometry noise."""
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

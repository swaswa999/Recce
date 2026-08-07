"""Speed profile along a road, from corner radius.

Callouts are timed in SECONDS ahead, not metres, so the engine has to know how
fast the rider will actually be travelling at each point. "In 200 metres" is
useless at 40 km/h and dangerous at 120.

Standard forward-backward pass: cap speed by lateral grip in each corner, then
limit how fast speed can fall (braking) and rise (drive) between points. Also
yields lean angle, which the app needs for telemetry anyway.
"""
import numpy as np

G = 9.81

# Ridden briskly but not at the limit. 6.5 m/s^2 is ~0.66 g, about 33 degrees of
# lean — a confident road pace on dry tarmac, not a track pace. Deliberately
# conservative: this feeds callout TIMING, and over-estimating speed makes
# callouts arrive late, which is the dangerous direction.
A_LAT = 6.5
A_BRAKE = 6.0
A_DRIVE = 3.0
V_MAX = 27.8  # 100 km/h
V_MIN = 4.0   # don't predict a track-stand in a hairpin


def speed_profile(s, radius, a_lat=A_LAT, a_brake=A_BRAKE, a_drive=A_DRIVE,
                  v_max=V_MAX, v_min=V_MIN):
    """Speed in m/s at each point of `s`, limited by grip then by brakes/drive."""
    r = np.abs(np.asarray(radius, dtype=float))
    with np.errstate(invalid="ignore"):
        v = np.sqrt(a_lat * r)
    v = np.clip(np.nan_to_num(v, nan=v_max, posinf=v_max), v_min, v_max)

    ds = np.diff(s)
    # backward: you must already be slow enough entering a corner
    for i in range(len(v) - 2, -1, -1):
        v[i] = min(v[i], np.sqrt(v[i + 1] ** 2 + 2 * a_brake * ds[i]))
    # forward: you can only accelerate so hard leaving one
    for i in range(1, len(v)):
        v[i] = min(v[i], np.sqrt(v[i - 1] ** 2 + 2 * a_drive * ds[i - 1]))
    return v


def time_profile(s, v):
    """Cumulative time in seconds to reach each point, from a speed profile."""
    ds = np.diff(s)
    v_avg = 0.5 * (v[:-1] + v[1:])
    dt = ds / np.maximum(v_avg, 1e-6)
    return np.concatenate([[0.0], np.cumsum(dt)])


def lean_angle(v, radius):
    """Lean angle in degrees: tan(theta) = v^2 / (g*r).

    This is the v1 lean estimate — derived from geometry and speed, no IMU and
    no mount calibration. Phase E logs it; IMU sensor fusion is deferred.
    """
    r = np.abs(np.asarray(radius, dtype=float))
    with np.errstate(divide="ignore", invalid="ignore"):
        theta = np.degrees(np.arctan((np.asarray(v) ** 2) / (G * r)))
    return np.nan_to_num(theta, nan=0.0, posinf=0.0)


def time_at(s_grid, t_grid, pos):
    """Time at an arbitrary arc-length position."""
    return float(np.interp(pos, s_grid, t_grid))


def pos_at(s_grid, t_grid, t):
    """Inverse: arc-length position at a given time."""
    return float(np.interp(t, t_grid, s_grid))

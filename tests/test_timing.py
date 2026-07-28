"""Callout timing and verbosity.

The dangerous failure in this module is a callout that arrives LATE — a rider
already committing to a corner while still being told what it is. Everything
here is built so late is impossible and early is merely annoying.
"""
import numpy as np
import pytest

from pipeline import analyze
from geometry import resample, signed_radius, smooth_radius, SEG_SPACING
from speed import speed_profile, time_profile, lean_angle, time_at, A_LAT, G
from timing import (build_callouts, schedule, keep_for_mode, Callout,
                    LEAD_SECONDS, MODES)
from synth_road import build_road


@pytest.fixture(scope="module")
def ride():
    x, y, z, _, _ = build_road()
    s, corners, loose = analyze(x, y, z)
    _, xi, yi, _ = resample(x, y, None, spacing=SEG_SPACING)
    r = smooth_radius(signed_radius(xi, yi, window=3), k=5)
    v = speed_profile(s, r)
    t = time_profile(s, v)
    return {"s": s, "t": t, "v": v, "r": r,
            "callouts": build_callouts(corners, loose)}


# --- the core guarantee ----------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_no_callout_ever_finishes_late(ride, mode):
    """Every callout must FINISH at least LEAD_SECONDS before its corner."""
    kept, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    late = []
    for c in kept:
        arrive = time_at(ride["s"], ride["t"], c.anchor_s)
        slack = arrive - c.ends_at
        if slack < LEAD_SECONDS - 1e-6:
            late.append((c.text, round(slack, 2)))
    assert not late, (
        f"mode={mode}: callouts finishing less than {LEAD_SECONDS}s before the "
        f"corner: {late}. A rider hearing the description while already "
        f"committing has been told too late."
    )


def test_faster_ride_triggers_callout_earlier_in_distance(ride):
    """Lead is in seconds, so a faster rider must be warned further back."""
    s, r = ride["s"], ride["r"]
    slow_t = time_profile(s, speed_profile(s, r, v_max=11.0))   # ~40 km/h
    fast_t = time_profile(s, speed_profile(s, r, v_max=33.0))   # ~120 km/h

    slow, _ = schedule(ride["callouts"], s, slow_t)
    fast, _ = schedule(ride["callouts"], s, fast_t)
    by_anchor_slow = {c.anchor_s: c for c in slow}

    compared = 0
    for c in fast:
        sc = by_anchor_slow.get(c.anchor_s)
        if sc is None:
            continue
        slow_pos = np.interp(sc.speak_at, slow_t, s)
        fast_pos = np.interp(c.speak_at, fast_t, s)
        assert fast_pos <= slow_pos + 1e-6, (
            f"{c.text!r}: fast rider warned at {fast_pos:.0f} m but slow rider "
            f"at {slow_pos:.0f} m — fixed-distance behaviour, not seconds-ahead"
        )
        compared += 1
    assert compared >= 3, "test did not actually compare enough callouts"


# --- verbosity must never reduce safety -----------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_verbosity_never_suppresses_a_warning(ride, mode):
    """Quieter must not mean less safe."""
    kept, dropped = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    warns = ("tightens", "don't cut", "over crest", "blind crest")
    lost = [c.text for c in dropped
            if any(w in c.text for w in warns) and c.dropped.startswith("verbosity")]
    assert not lost, f"mode={mode} suppressed warning callouts: {lost}"


@pytest.mark.parametrize("mode", MODES)
def test_verbosity_never_suppresses_a_hazard_or_crest(ride, mode):
    for kind in ("hazard", "crest"):
        c = Callout(anchor_s=500.0, text="caution, gravel", kind=kind)
        assert keep_for_mode(c, mode), f"{kind} dropped in mode={mode}"


def test_guardian_is_quieter_than_full(ride):
    full, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode="full")
    guard, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode="guardian")
    assert len(guard) < len(full), "guardian mode suppressed nothing"


def test_unknown_verbosity_mode_is_an_error(ride):
    with pytest.raises(ValueError):
        keep_for_mode(Callout(anchor_s=0.0, text="right 4", kind="corner",
                              severity=4), "whisper")


# --- priority --------------------------------------------------------------

def test_hazard_preempts_a_colliding_corner_call(ride):
    """Nothing outranks a hazard."""
    s, t = ride["s"], ride["t"]
    corner = Callout(anchor_s=530.0, text="right 3 tightens", kind="corner",
                     severity=3)
    hazard = Callout(anchor_s=531.0, text="caution, gravel", kind="hazard")
    kept, dropped = schedule([corner, hazard], s, t)
    assert any(c.kind == "hazard" for c in kept), "hazard was not spoken"
    if len(kept) == 1:
        assert dropped and dropped[0].kind == "corner"


def test_suppressed_callouts_are_reported_not_silent(ride):
    """A dropped callout must carry a reason — silent loss looks like coverage."""
    _, dropped = schedule(ride["callouts"], ride["s"], ride["t"],
                          mode="guardian")
    assert dropped, "expected guardian to suppress something on this road"
    assert all(c.dropped for c in dropped), "a callout was dropped with no reason"


# --- speed model ----------------------------------------------------------

def test_speed_respects_lateral_grip(ride):
    """Speed in a corner must not exceed sqrt(a_lat * r)."""
    v, r = ride["v"], ride["r"]
    limit = np.sqrt(A_LAT * np.abs(r))
    bad = np.where(v > limit + 1e-6)[0]
    assert len(bad) == 0, f"{len(bad)} points exceed the grip limit"


def test_time_is_monotonic(ride):
    assert np.all(np.diff(ride["t"]) > 0), "time went backwards along the road"


def test_hairpin_is_the_slowest_point(ride):
    """Sanity: the 12 m hairpin should be where speed bottoms out."""
    s, v = ride["s"], ride["v"]
    slowest = s[int(np.argmin(v))]
    assert 940 < slowest < 1040, (
        f"slowest point at {slowest:.0f} m, expected inside the hairpin "
        f"(970-1025 m)"
    )


def test_lean_angle_is_physically_sane(ride):
    """tan(theta) = v^2/(g*r); at the grip limit that is atan(a_lat/g)."""
    lean = lean_angle(ride["v"], ride["r"])
    ceiling = np.degrees(np.arctan(A_LAT / G))
    assert lean.max() <= ceiling + 0.5, (
        f"peak lean {lean.max():.1f} deg exceeds the {ceiling:.1f} deg implied "
        f"by the lateral-grip cap"
    )
    assert lean.max() > 20, "no meaningful lean anywhere on a canyon road"

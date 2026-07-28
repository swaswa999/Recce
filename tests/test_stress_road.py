"""The spiral stress road: realistic geometry, sustained minima.

This road answers the question the answer-key road cannot. Its corners have
transition spirals (as every built road does) and each holds its minimum radius
over a plateau long enough to measure, so radius accuracy here is a property of
the ESTIMATOR rather than of an unresolvable 0.85 m arc.

It also contains a genuinely opening corner, which makes the true-positive check
for "opens" possible for the first time — a modifier that never fires is as
broken as one that fires wrongly, and the answer-key road can only test the
false-positive direction.
"""
import numpy as np
import pytest

from pipeline import analyze
from synth_stress import build_stress_road

# Radius here is measurable, so the ratchet is tight. Contrast the answer-key
# road's 0.15 exception for its unresolvable tightening corner.
RADIUS_TOLERANCE = 0.03


@pytest.fixture(scope="module")
def analyzed():
    x, y, z, truth, road_len = build_stress_road()
    _, corners, loose = analyze(x, y, z)
    return {"corners": corners, "truth": truth, "road_len": road_len}


def matching(corners, t):
    """The detected corner overlapping this designed corner's extent."""
    a, b = t["s_hint"]
    hits = [c for c in corners if c.s1 > a and c.s0 < b]
    assert hits, f"{t['name']}: no corner detected in {a}-{b} m"
    assert len(hits) == 1, (
        f"{t['name']}: {len(hits)} corners detected in {a}-{b} m — fragmented"
    )
    return hits[0]


def test_all_designed_corners_detected(analyzed):
    assert len(analyzed["corners"]) == len(analyzed["truth"]), (
        f"{len(analyzed['truth'])} corners designed, "
        f"{len(analyzed['corners'])} detected"
    )


@pytest.mark.parametrize("idx", range(5))
def test_direction_and_severity(analyzed, idx):
    t = analyzed["truth"][idx]
    c = matching(analyzed["corners"], t)
    assert c.direction == t["direction"], f"{t['name']}: wrong direction"
    assert c.severity == t["severity"], (
        f"{t['name']}: severity {c.severity!r}, designed {t['severity']!r}"
    )


@pytest.mark.parametrize("idx", range(5))
def test_radius_never_optimistic_on_sustained_minimum(analyzed, idx):
    """With a sustained minimum there is no excuse for reading flat."""
    t = analyzed["truth"][idx]
    c = matching(analyzed["corners"], t)
    designed = t["min_radius"]
    limit = designed * (1 + RADIUS_TOLERANCE)
    assert c.min_radius <= limit, (
        f"{t['name']}: measured {c.min_radius:.1f} m against a SUSTAINED "
        f"designed {designed:.1f} m "
        f"(+{100 * (c.min_radius / designed - 1):.1f}%) — this corner holds its "
        f"radius over a plateau, so an optimistic read is an estimator defect, "
        f"not a test-road artifact."
    )


@pytest.mark.parametrize("idx", range(5))
def test_required_modifiers_present(analyzed, idx):
    """Includes the true-positive check for 'opens' — a modifier that never
    fires is as broken as one that fires wrongly."""
    t = analyzed["truth"][idx]
    c = matching(analyzed["corners"], t)
    missing = [m for m in t["modifiers"] if m not in c.modifiers]
    assert not missing, (
        f"{t['name']}: missing {missing}, got {c.modifiers}. A warning that "
        f"never fires leaves the rider unwarned."
    )


@pytest.mark.parametrize("idx", range(5))
def test_forbidden_modifiers_absent(analyzed, idx):
    t = analyzed["truth"][idx]
    c = matching(analyzed["corners"], t)
    wrong = [m for m in t["forbid"] if m in c.modifiers]
    assert not wrong, (
        f"{t['name']}: emitted {wrong}, which contradicts the geometry. "
        f"got {c.modifiers}"
    )


def test_opens_and_tightens_are_not_confused(analyzed):
    """The two shape modifiers must never both fire, and must not swap."""
    for c in analyzed["corners"]:
        assert not ("opens" in c.modifiers and "tightens" in c.modifiers), (
            f"corner at {c.s0:.0f} m claims to both open and tighten"
        )
    tight = matching(analyzed["corners"], analyzed["truth"][1])
    opening = matching(analyzed["corners"], analyzed["truth"][2])
    assert "tightens" in tight.modifiers and "opens" not in tight.modifiers
    assert "opens" in opening.modifiers and "tightens" not in opening.modifiers


def test_every_corner_was_refined(analyzed):
    """No silent fallback to the coarse flattening estimator."""
    unrefined = [round(c.s0) for c in analyzed["corners"] if not c.refined]
    assert not unrefined, f"corners fell back to the coarse estimate at {unrefined} m"


def test_spiral_road_resolves_its_tightening_minimum(analyzed):
    """A sustained decreasing-radius minimum must be measured accurately.

    This localizes the answer-key road's +13.6%: same decreasing-radius shape,
    but holding 45 m over 50 m of arc instead of 0.85 m, and it reads exactly.
    So the error there is about the minimum's ARC EXTENT, not the shape.

    NOT a discriminator between estimators. The pre-Phase-B estimator (wide
    circumradius + rolling median) also reads 45.0 m here, and produces
    identical modifiers on all five corners. That is informative rather than
    disappointing — the old estimator's defect is flattening curvature peaks,
    and the fact that it still resolves a *sustained* peak is what pins the
    answer-key error on the brief minimum.

    The evidence that the new estimator is better lives in
    test_decimated_geometry.py, where the old one produced false "opens" on
    20-50% of phases and this one produces none.
    """
    t = analyzed["truth"][1]
    c = matching(analyzed["corners"], t)
    err = 100 * (c.min_radius / t["min_radius"] - 1)
    assert err <= 3.0, (
        f"sustained tightening corner reads {err:+.1f}% — a corner that holds "
        f"its minimum over 50 m of arc has no excuse for reading flat."
    )

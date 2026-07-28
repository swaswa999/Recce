"""The optimistic-bias invariant — this product's #1 safety check.

A corner called EASIER than it rides can contribute to a crash. A corner
called harder costs a little rider confidence and nothing else. The error
budget is asymmetric, so the tests are too.

Two directions to check, and they fail independently:
  - severity band  — currently passes
  - measured radius — currently FAILS on the tightening corner (the known
    smoothing bug, Phase B in docs/MVP-PLAN.md)
"""
import pytest

from test_answer_key import DESIGNED, by_order

# Difficulty rank: lower = harder. Hairpin is the hardest thing on the scale.
# The rally 1-6 scale runs the other way from difficulty (6 = fastest/easiest),
# so comparing raw severity values would silently invert this whole check.
RANK = {"hairpin": 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}

# Corners in arc-length order, with their designed geometry.
ORDERED = [
    (0, "right_4"),
    (1, "left_2"),
    (2, "right_3_tight"),
    (3, "hairpin_left"),
    (4, "right_3_long"),
    (5, "left_4_crest"),
]

# Per-corner ratchets, NOT one global bound.
#
# A single tolerance has to be set by the worst corner, which then hands that
# same slack to every well-measured corner. With one 0.13 bound, right_3_long
# could drift from 59.7 m to 67.8 m — 13% optimistic and 3% short of being
# called a 4 instead of a 3 — and the suite would stay green.
#
# Each value sits just above what that corner currently measures, so any
# regression fails immediately. Tighten them as accuracy improves.
RADIUS_TOLERANCE = {
    "right_4": 0.02,
    "left_2": 0.02,
    # Documented exception. The tightening corner's designed minimum exists over
    # ~0.85 m of arc (only 7 of 104 arc steps sit below R=55), so no windowed
    # estimator can resolve it. This is a limitation of the test road, not the
    # estimator — see test_tightening_corner_meets_accuracy_goal and the
    # transition-spiral stress road in docs/TASKS.md.
    "right_3_tight": 0.15,
    "hairpin_left": 0.02,
    "right_3_long": 0.02,
    "left_4_crest": 0.02,
}


@pytest.mark.parametrize("idx,key", ORDERED)
def test_severity_never_optimistic(corners, idx, key):
    """No corner may be rated easier than it was designed."""
    c = by_order(corners, idx)
    designed = DESIGNED[key]["severity"]
    assert RANK[c.severity] <= RANK[designed], (
        f"{key}: rated {c.severity!r}, designed {designed!r} — "
        f"OPTIMISTIC. The corner is being called easier than it is."
    )


@pytest.mark.parametrize("idx,key", ORDERED)
def test_radius_never_reads_flatter_than_designed(corners, idx, key):
    """Measured radius must not exceed designed — a larger radius reads flatter,
    which is the optimistic direction."""
    c = by_order(corners, idx)
    designed = DESIGNED[key]["radius"]
    tol = RADIUS_TOLERANCE[key]
    limit = designed * (1 + tol)
    assert c.min_radius <= limit, (
        f"{key}: measured {c.min_radius:.1f} m against designed {designed:.1f} m "
        f"(+{100 * (c.min_radius / designed - 1):.1f}%, ratchet is +{100 * tol:.0f}%) "
        f"— reads FLATTER than reality, the optimistic direction."
    )


@pytest.mark.xfail(
    strict=True,
    reason="TEST-ROAD ARTIFACT, established by measurement rather than argued. "
           "Confined arc fitting took this corner from +26.7% to +13.6%, with "
           "every other corner inside 0.6%. The residual is the road: "
           "synth_road's tightening corner only reaches its 50.67 m minimum over "
           "~0.85 m of arc (7 of 104 steps below R=55), and no windowed "
           "estimator can resolve a radius existing over less than a metre. "
           "Confirmed on synth_stress.py, whose corners hold their minima over "
           "plateaus and have realistic transition spirals: a sustained "
           "decreasing-radius 45 m corner reads 45.0 m (0.0%), and all five read "
           "exactly — see tests/test_stress_road.py. Notably the PRE-Phase-B "
           "estimator also reads them exactly, which strengthens rather than "
           "weakens the conclusion: an estimator whose known defect is flattening "
           "curvature peaks still resolves a SUSTAINED peak, so the error here is "
           "about the minimum's arc extent, not the corner's shape. This test "
           "stays as a strict xfail because the goal genuinely cannot be met on "
           "THIS road; test_stress_road.py is where radius accuracy is now "
           "enforced, at a 3% ratchet.",
)
def test_tightening_corner_meets_accuracy_goal(corners):
    """The 10% goal, kept visible rather than absorbed into the tolerance."""
    c = by_order(corners, 2)
    designed = DESIGNED["right_3_tight"]["radius"]
    assert c.min_radius <= designed * 1.10, (
        f"tightening corner measured {c.min_radius:.1f} m against designed "
        f"{designed:.1f} m (+{100 * (c.min_radius / designed - 1):.1f}%), "
        f"goal is +10%"
    )


def test_tightens_never_reported_as_opens(corners):
    """The worst single output the engine can produce.

    Calling 'opens' on a corner that actually tightens invites a rider to
    accelerate into a decreasing radius.
    """
    c = by_order(corners, 2)  # designed R 120 -> 50, genuinely tightening
    assert "opens" not in c.modifiers, \
        "engine called a tightening corner 'opens' — worst-case failure"


def test_no_designed_corner_silently_dropped(corners):
    """A dropped corner is a silent optimistic failure: no callout at all."""
    assert len(corners) == len(ORDERED), (
        f"{len(ORDERED)} corners designed, {len(corners)} detected — a missing "
        f"corner means the rider gets no warning at all."
    )

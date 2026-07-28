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

# 5 m resampling introduces a few percent of discretization error in measured
# radius. 5% is the observed noise floor on this road; anything beyond it is
# systematic bias, not sampling. Provisional — recalibrate with Phase C real
# road data before trusting this number on OSM geometry.
RADIUS_TOLERANCE = 0.05


@pytest.mark.parametrize("idx,key", ORDERED)
def test_severity_never_optimistic(corners, idx, key):
    """No corner may be rated easier than it was designed."""
    c = by_order(corners, idx)
    designed = DESIGNED[key]["severity"]
    assert RANK[c.severity] <= RANK[designed], (
        f"{key}: rated {c.severity!r}, designed {designed!r} — "
        f"OPTIMISTIC. The corner is being called easier than it is."
    )


@pytest.mark.parametrize("idx,key", [
    (0, "right_4"),
    (1, "left_2"),
    pytest.param(2, "right_3_tight", marks=pytest.mark.xfail(
        strict=True,
        reason="KNOWN BUG (Phase B): rolling-median smoothing under-reads "
               "rapidly tightening corners — measures ~64 m against a designed "
               "50 m. Fix is per-segment arc fitting. When that lands this test "
               "XPASSes, which strict=True turns into a failure, forcing the "
               "marker to be removed and the fix locked in.",
    )),
    (3, "hairpin_left"),
    (4, "right_3_long"),
    (5, "left_4_crest"),
])
def test_radius_never_reads_flatter_than_designed(corners, idx, key):
    """Measured radius must not exceed designed — a larger radius reads flatter,
    which is the optimistic direction."""
    c = by_order(corners, idx)
    designed = DESIGNED[key]["radius"]
    limit = designed * (1 + RADIUS_TOLERANCE)
    assert c.min_radius <= limit, (
        f"{key}: measured {c.min_radius:.1f} m against designed {designed:.1f} m "
        f"(+{100 * (c.min_radius / designed - 1):.1f}%) — reads FLATTER than "
        f"reality, the optimistic direction."
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

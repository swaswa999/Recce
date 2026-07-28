"""Behaviour at realistic OSM node spacing.

The answer-key road is built with a 2 m step — far denser than any traced OSM
way. A suite that only ever sees it is blind to a whole class of defect: a
false-"opens" regression once ran at a 20-50% rate on clean 4-12 m geometry
while 23 tests stayed green.

These tests decimate the road to real node spacing with ZERO position error.
That is *good* OSM data for a mountain road, so anything failing here is a
genuine defect, not a noise-robustness wish.
"""
import numpy as np
import pytest

from pipeline import analyze
from synth_road import build_road
from conftest import decimate

# The answer-key road contains no opening corner anywhere, so any "opens" is
# false by construction. A corner called "opens" when it does not open is the
# worst single output the engine can produce.
EXPECTED_CORNERS = 6
REAL_HAIRPIN_S = (940, 1040)

# Number of decimation phases per spacing. Node PHASE relative to a corner
# matters as much as spacing, so a handful of phases can straddle a failure
# onset and read clean: at 10 phases 12 m looked clean, at 100 it fails 3/100.
# Do not lower this to make the suite faster — undersampling here is exactly how
# a false-"opens" regression reached a green suite twice.
PHASES = 40

# Measured at 100 phases after profile-end trimming: clean 0/100 through 14 m,
# then 3/100 at 16 m, 11/100 at 18 m, 29/100 at 20 m. So 16 m is the onset and
# 4-14 m must stay clean. MAX_TRUSTED_MEDIAN_SPACING is 12 m, keeping margin
# below onset without refusing well-traced roads — a gate that refuses
# everything gets bypassed, which is worse than no gate.
GOOD_SPACINGS = (4.0, 6.0, 8.0, 10.0, 12.0, 14.0)
BEYOND_LIMIT_SPACING = 16.0


def decimated_phase(x, y, z, gap, phase_frac):
    """Decimate starting at a fractional offset, giving distinct roads from one
    source — node phase relative to a corner matters as much as spacing."""
    d = np.hypot(np.diff(x), np.diff(y))
    s = np.concatenate([[0.0], np.cumsum(d)])
    idx = np.unique(np.clip(
        np.searchsorted(s, np.arange(phase_frac * gap, s[-1], gap)),
        0, len(x) - 1))
    return x[idx], y[idx], z[idx]


@pytest.fixture(scope="module")
def road():
    x, y, z, _, _ = build_road()
    return x, y, z


@pytest.mark.parametrize("gap", GOOD_SPACINGS)
def test_corner_count_stable_at_real_node_spacing(road, gap):
    """Segmentation must not fragment or drop corners on well-traced geometry."""
    x, y, z = road
    bad = []
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, gap, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        if len(corners) != EXPECTED_CORNERS:
            bad.append((round(i / PHASES, 3), len(corners)))
    assert not bad, (
        f"{gap:.0f} m nodes: expected {EXPECTED_CORNERS} corners, got "
        f"{bad} (phase, count). Extra corners are phantom callouts; missing "
        f"corners are silent no-warnings."
    )


@pytest.mark.parametrize("gap", GOOD_SPACINGS)
def test_no_false_opens_at_real_node_spacing(road, gap):
    """The road has no opening corner, so any "opens" is a dangerous lie."""
    x, y, z = road
    bad = []
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, gap, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        for c in corners:
            if "opens" in c.modifiers:
                bad.append((round(i / PHASES, 3), round(c.s0), c.severity))
    assert not bad, (
        f"{gap:.0f} m nodes: false 'opens' at {bad} (phase, s0, severity). "
        f"Telling a rider a corner opens when it does not invites them to "
        f"accelerate into it."
    )


@pytest.mark.parametrize("gap", GOOD_SPACINGS)
def test_no_phantom_hairpin_at_real_node_spacing(road, gap):
    """A hairpin call on a straight destroys trust in every other callout."""
    x, y, z = road
    bad = []
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, gap, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        for c in corners:
            if c.severity == "hairpin" and not (REAL_HAIRPIN_S[0] < c.s0 < REAL_HAIRPIN_S[1]):
                bad.append((round(i / PHASES, 3), round(c.s0)))
    assert not bad, f"{gap:.0f} m nodes: phantom hairpins at {bad} (phase, s0)"


@pytest.mark.parametrize("gap", GOOD_SPACINGS)
def test_severity_not_optimistic_at_real_node_spacing(road, gap):
    """Decimation must not make any corner read easier than the dense road."""
    from test_answer_key import DESIGNED, by_order
    from test_severity_bias import RANK, ORDERED

    x, y, z = road
    bad = []
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, gap, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        if len(corners) != EXPECTED_CORNERS:
            continue  # covered by the corner-count test
        for idx, key in ORDERED:
            c = by_order(corners, idx)
            if RANK[c.severity] > RANK[DESIGNED[key]["severity"]]:
                bad.append((round(i / PHASES, 3), key, c.severity,
                            DESIGNED[key]["severity"]))
    assert not bad, (
        f"{gap:.0f} m nodes: OPTIMISTIC severity at "
        f"{bad} (phase, corner, got, designed)"
    )


@pytest.mark.parametrize("gap", GOOD_SPACINGS)
def test_tightens_is_retained_at_real_node_spacing(road, gap):
    """The reverse of the false-opens test: a real warning must not go MISSING.

    Trimming biased profile ends protects against false "opens", but the same
    end bias works against emitting "tightens" at all. Losing it is a silent
    optimistic failure — the rider gets "right 3" for a corner that tightens.
    """
    x, y, z = road
    missing = []
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, gap, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        tightener = [c for c in corners if c.s1 > 520 and c.s0 < 700]
        if not tightener:
            continue  # corner-count test owns this
        if "tightens" not in tightener[0].modifiers:
            missing.append((round(i / PHASES, 3), round(tightener[0].s0)))
    assert not missing, (
        f"{gap:.0f} m nodes: 'tightens' LOST on the decreasing-radius corner at "
        f"{missing} (phase, s0). The rider is told a corner holds its radius "
        f"when it actually tightens."
    )


@pytest.mark.parametrize("gap", GOOD_SPACINGS)
def test_refinement_never_silently_falls_back(road, gap):
    """Every corner must be measured by the refined estimator, not the coarse one.

    refine_corners() keeps the coarse reading if the profile comes back empty or
    reads flatter than the corner threshold. That is the safe direction, but the
    coarse estimator is the one that flattens tight corners — so a silent
    fallback is an unobservable regression to the bug this all replaced.
    """
    x, y, z = road
    fell_back = []
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, gap, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        for c in corners:
            if not c.refined:
                fell_back.append((round(i / PHASES, 3), round(c.s0)))
    assert not fell_back, (
        f"{gap:.0f} m nodes: refinement fell back to the coarse estimate at "
        f"{fell_back} (phase, s0)"
    )


@pytest.mark.xfail(
    strict=True,
    reason="Documents the information limit rather than asserting a fix. 16 m "
           "node spacing is past the limit for this road: the 12 m-radius "
           "hairpin becomes unrepresentable and false 'opens' appear on 3/100 "
           "phases, landing on the real hairpin as 'hairpin, opens'. No "
           "estimator can recover curvature finer than the survey; the "
           "mitigation is refusing such roads, which run_real.py does at 12 m. "
           "strict=True means if this starts passing, the limit moved and this "
           "should be promoted to a real assertion — which is exactly what "
           "happened once already when profile-end trimming moved the onset "
           "from 12 m to 16 m.",
)
def test_beyond_information_limit_is_still_clean(road):
    x, y, z = road
    for i in range(PHASES):
        xn, yn, zn = decimated_phase(x, y, z, BEYOND_LIMIT_SPACING, i / PHASES)
        _, corners, _ = analyze(xn, yn, zn)
        assert not any("opens" in c.modifiers for c in corners), \
            f"false opens at {BEYOND_LIMIT_SPACING} m, phase {i / PHASES}"

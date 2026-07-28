"""Input-data fitness gates.

Both of these were written after first contact with real OSM data. Neither
synthetic road could have found them: synth_road has smooth analytic elevation,
synth_stress has none at all, and both have perfectly uniform node spacing.

The failure they guard is specific. On the Tail of the Dragon, fetched via
Overpass with Open-Elevation heights, the engine emitted "over crest don't cut"
on 28% of 260 corners. The elevation profile had integer-metre resolution and a
p95 gradient of 126% — SRTM at 30 m resolution sampled along a switchbacking
road lands adjacent points in different terrain cells. Those were not crests.
"""
import numpy as np
import pytest

from geometry import (elevation_quality, node_spacing_stats, resample,
                      MAX_PLAUSIBLE_GRADE_P95, MAX_ELEVATION_QUANTUM,
                      SEG_SPACING)
from synth_road import build_road


@pytest.fixture(scope="module")
def road():
    x, y, z, _, _ = build_road()
    return x, y, z


def gridded(x, y, z):
    _, _, _, zi = resample(x, y, z, spacing=SEG_SPACING)
    return zi


# --- elevation fitness ----------------------------------------------------

def test_clean_synthetic_elevation_passes(road):
    x, y, z = road
    quantum, p95, verdict = elevation_quality(z, gridded(x, y, z), SEG_SPACING)
    assert verdict == "ok", f"clean analytic elevation rejected: {verdict}"
    assert p95 < MAX_PLAUSIBLE_GRADE_P95


def test_integer_quantized_elevation_is_rejected(road):
    """Open-Elevation's exact failure mode: heights rounded to whole metres."""
    x, y, z = road
    zq = np.round(z)
    quantum, p95, verdict = elevation_quality(zq, gridded(x, y, zq), SEG_SPACING)
    assert verdict != "ok", (
        f"integer-metre elevation accepted (quantum {quantum:.2f} m, "
        f"p95 grade {p95:.0%}) — this is the profile that produced 'over crest' "
        f"on 28% of a real road's corners"
    )


def test_implausible_gradient_is_rejected(road):
    """A profile with road-impossible gradients is sampling error, not road."""
    x, y, z = road
    rng = np.random.default_rng(0)
    noisy = z + rng.normal(0, 5.0, len(z))  # 5 m of terrain-cell error
    _, p95, verdict = elevation_quality(noisy, gridded(x, y, noisy), SEG_SPACING)
    assert verdict != "ok", f"p95 grade {p95:.0%} accepted"
    assert "gradient" in verdict


def test_quantum_is_measured_on_raw_not_resampled(road):
    """Resampling interpolates, so the grid hides the source's resolution.

    Reading the quantum off the resampled profile reports a reassuring 0.00 m
    for data that is actually integer-metre. That bug shipped briefly.
    """
    x, y, z = road
    zq = np.round(z)
    quantum, _, _ = elevation_quality(zq, gridded(x, y, zq), SEG_SPACING)
    assert quantum >= 1.0 - 1e-9, (
        f"quantum measured as {quantum:.3f} m for integer-metre input — it is "
        f"being read off the interpolated grid, not the raw values"
    )


def test_thresholds_are_physically_motivated():
    """Guard against these being loosened to make a road pass."""
    assert MAX_PLAUSIBLE_GRADE_P95 <= 0.25, (
        "public mountain roads top out around 15% gradient; a p95 ceiling above "
        "25% would admit profiles that are pure sampling error"
    )
    assert MAX_ELEVATION_QUANTUM <= 0.5, (
        "crests are called from a 0.05 grade change over ~30 m, so a 1 m "
        "quantum produces a 0.033 spurious swing — the same order as the signal"
    )


# --- node spacing ---------------------------------------------------------

def test_node_spacing_stats_on_uniform_road(road):
    """The synthetic road is built at a uniform 2 m step."""
    x, y, z = road
    med, p90, mx = node_spacing_stats(x, y)
    assert 1.9 < med < 2.1, f"median {med:.2f} m, expected ~2 m"
    assert p90 >= med and mx >= p90


def test_p90_catches_a_road_the_median_passes():
    """A road can pass on its median and still be mostly untrustworthy.

    The Tail of the Dragon has a 9.7 m median — inside the 12 m gate — while
    40% of its gaps exceed 12 m, p90 is 30 m and the largest is 176 m. Checking
    only the median would ship it.
    """
    # Mirrors the Dragon's shape: most GAPS are fine, a large minority are not.
    # Proportion has to be counted in gaps, not length — 2 km of 40 m gaps is
    # only 50 gaps, which a p90 will not see next to 200 dense ones.
    dense = np.arange(0, 800, 8.0)        # 100 gaps at 8 m
    sparse = np.arange(800, 2800, 30.0)   # ~67 gaps at 30 m -> 40% of gaps
    s = np.concatenate([dense, sparse])
    x, y = s, np.zeros_like(s)
    med, p90, mx = node_spacing_stats(x, y)
    assert med <= 12.0, (
        f"median {med:.1f} m should pass a 12 m gate for this construction"
    )
    assert p90 > 25.0, (
        f"p90 {p90:.1f} m failed to flag a road where 40% of gaps are 30 m — "
        f"the median alone is not a sufficient gate"
    )

"""Shared pipeline fixtures for the synthetic answer-key road."""
import numpy as np
import pytest

from pipeline import analyze_to_script
from synth_road import build_road


@pytest.fixture(scope="session")
def analyzed():
    """Run the canonical pipeline on the synthetic canyon road.

    Uses pipeline.analyze_to_script(), the same entry point run_demo.py calls,
    so the tests can never validate a different pipeline than the demo prints.
    """
    x, y, z, truth, road_len = build_road()
    s, corners, loose, events, script = analyze_to_script(x, y, z)
    return {
        "corners": corners,
        "loose_crests": loose,
        "events": events,
        "script": script,
        "road_len": road_len,
        "truth": truth,
    }


@pytest.fixture(scope="session")
def corners(analyzed):
    return analyzed["corners"]


def decimate(x, y, z, node_gap, sigma=0.0, seed=0):
    """Resample a road down to realistic OSM node spacing, optionally with
    per-node position error.

    The answer-key road is built with a 2 m step, far denser than any traced OSM
    way. Tests that only ever see it cannot detect defects that appear at real
    node spacing — which is exactly how a false-"opens" regression once passed a
    fully green suite.
    """
    d = np.hypot(np.diff(x), np.diff(y))
    s = np.concatenate([[0.0], np.cumsum(d)])
    idx = np.unique(np.clip(
        np.searchsorted(s, np.arange(0.0, s[-1], node_gap)), 0, len(x) - 1))
    xn, yn = x[idx], y[idx]
    if sigma > 0:
        rng = np.random.default_rng(seed)
        xn = xn + rng.normal(0, sigma, len(xn))
        yn = yn + rng.normal(0, sigma, len(yn))
    return xn, yn, (z[idx] if z is not None else None)

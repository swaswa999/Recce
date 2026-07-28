"""Shared pipeline fixtures for the synthetic answer-key road."""
import pytest

from geometry import resample, signed_radius, smooth_radius
from corners import (find_corners, add_shape_modifiers, find_crests,
                     attach_crests, link_corners)
from script_gen import build_script
from synth_road import build_road


@pytest.fixture(scope="session")
def analyzed():
    """Run the full pipeline on the synthetic canyon road.

    Mirrors run_demo.py exactly — if the two drift apart, the tests stop
    validating what the demo shows.
    """
    x, y, z, truth, road_len = build_road()
    s, xi, yi, zi = resample(x, y, z, spacing=5.0)
    r = signed_radius(xi, yi, window=3)
    rs = smooth_radius(r, k=5)

    corners = find_corners(s, rs)
    corners = add_shape_modifiers(corners, s, rs)
    crests = find_crests(s, zi)
    loose = attach_crests(corners, crests)
    corners = link_corners(corners)
    events, script = build_script(corners, loose, road_len)

    return {
        "corners": corners,
        "loose_crests": loose,
        "events": events,
        "script": script,
        "road_len": road_len,
    }


@pytest.fixture(scope="session")
def corners(analyzed):
    return analyzed["corners"]

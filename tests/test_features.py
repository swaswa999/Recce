"""Road furniture: bridges, tunnels, speed bumps.

These come straight from OSM tags, so they carry none of the severity-bias risk
the curvature pipeline does. The risk they do carry is placement — a bump called
late is a bump you hit — plus the usual one of drowning the corner calls.
"""
import numpy as np
import pytest

from features import (road_features, structure_spans, MIN_BRIDGE_M,
                      MERGE_GAP_M, WARNING_TYPES)
from timing import build_callouts, schedule, keep_for_mode, MODES


def node_s(n, spacing=10.0):
    return np.arange(n, dtype=float) * spacing


# --- spans ----------------------------------------------------------------

def test_bridge_span_becomes_one_callout():
    structure = [""] * 5 + ["bridge"] * 6 + [""] * 5
    spans = structure_spans(structure, node_s(16))
    assert len(spans) == 1
    kind, s0, s1 = spans[0]
    assert kind == "bridge"
    assert s0 == 50.0 and s1 == 100.0


def test_culvert_length_bridges_are_ignored():
    """Every culvert is tagged bridge=yes. Calling them is noise, and noise
    costs the rider trust in the whole channel."""
    structure = [""] * 5 + ["bridge", "bridge"] + [""] * 5
    spans = structure_spans(structure, node_s(12, spacing=MIN_BRIDGE_M / 3))
    assert spans == [], f"a {MIN_BRIDGE_M / 3:.0f} m bridge was called"


def test_short_tunnels_are_never_ignored():
    """Length doesn't make a tunnel safe — the eyes still have to adjust."""
    structure = [""] * 5 + ["tunnel", "tunnel"] + [""] * 5
    spans = structure_spans(structure, node_s(12, spacing=2.0))
    assert len(spans) == 1 and spans[0][0] == "tunnel"


def test_adjacent_spans_merge():
    """Two mapped spans a few metres apart are one structure to a rider.

    Spacing chosen so the gap between the spans is comfortably inside
    MERGE_GAP_M rather than sitting on the boundary.
    """
    spacing = 10.0
    gap_nodes = 2                       # 20 m of untagged road between spans
    structure = ["bridge"] * 4 + [""] * gap_nodes + ["bridge"] * 4
    spans = structure_spans(structure, node_s(8 + gap_nodes, spacing))
    assert (gap_nodes + 1) * spacing < MERGE_GAP_M, "test gap is not inside the merge window"
    assert len(spans) == 1, f"got {spans} — should have merged across the gap"


def test_distant_spans_do_not_merge():
    """Two genuinely separate bridges stay two callouts."""
    structure = ["bridge"] * 4 + [""] * 12 + ["bridge"] * 4
    spans = structure_spans(structure, node_s(20, 10.0))
    assert len(spans) == 2, f"merged two bridges {MERGE_GAP_M} m apart: {spans}"


def test_no_structure_data_is_not_an_error():
    assert structure_spans(None, node_s(10)) == []
    assert road_features({}, node_s(10)) == []


# --- features from a road -------------------------------------------------

def test_bumps_are_placed_at_their_node():
    road = {"points": [{"i": 7, "type": "bump"}]}
    feats = road_features(road, node_s(20))
    assert len(feats) == 1
    assert feats[0]["s"] == 70.0
    assert feats[0]["text"] == "bump"


def test_bump_and_tunnel_are_warnings_bridge_is_not():
    road = {"structure": [""] * 3 + ["bridge"] * 6 + [""] * 3 + ["tunnel"] * 4,
            "points": [{"i": 2, "type": "bump"}]}
    feats = {f["type"]: f for f in road_features(road, node_s(16))}
    assert feats["bump"]["warn"] is True
    assert feats["tunnel"]["warn"] is True
    assert feats["bridge"]["warn"] is False
    assert WARNING_TYPES == {"tunnel", "bump"}


def test_out_of_range_point_index_is_dropped():
    road = {"points": [{"i": 999, "type": "bump"}]}
    assert road_features(road, node_s(10)) == []


def test_features_come_back_in_road_order():
    road = {"structure": [""] * 10 + ["bridge"] * 4,
            "points": [{"i": 2, "type": "bump"}]}
    feats = road_features(road, node_s(16))
    assert [f["s"] for f in feats] == sorted(f["s"] for f in feats)


# --- through the callout layer --------------------------------------------

def _feature(s, kind, warn):
    return {"s": s, "type": kind, "text": kind, "warn": warn}


def test_features_reach_the_callout_stream():
    cs = build_callouts([], [], features=[_feature(100.0, "bump", True),
                                          _feature(300.0, "bridge", False)])
    texts = [c.text for c in cs]
    assert "bump" in texts and "bridge" in texts


@pytest.mark.parametrize("mode", MODES)
def test_features_survive_every_verbosity_mode(mode):
    """Even Guardian. They are map facts, not estimates, and they are rare."""
    cs = build_callouts([], [], features=[_feature(100.0, "bump", True),
                                          _feature(300.0, "bridge", False),
                                          _feature(500.0, "tunnel", True)])
    for c in cs:
        assert keep_for_mode(c, mode), f"{c.text!r} suppressed in {mode}"


def test_bump_and_tunnel_count_as_warnings_to_the_scheduler():
    """Their text contains none of the corner-shape warning words, so this only
    works if the feature table drives it rather than string matching."""
    cs = build_callouts([], [], features=[_feature(100.0, "bump", True),
                                          _feature(300.0, "tunnel", True),
                                          _feature(500.0, "bridge", False)])
    by = {c.text: c for c in cs}
    assert by["bump"].is_warning and by["tunnel"].is_warning
    assert not by["bridge"].is_warning


def test_a_bump_outranks_a_corner_call_for_its_slot():
    """A bump is a physical object. A corner description is an estimate."""
    from timing import Callout
    s = np.arange(0.0, 1200.0, 5.0)
    t = s / 20.0
    corner = Callout(anchor_s=300.0, text="right 4", kind="corner", severity=4)
    bump = build_callouts([], [], features=[_feature(302.0, "bump", True)])[0]
    kept, dropped = schedule([corner, bump], s, t)
    assert any(c.text == "bump" for c in kept), \
        f"the bump was dropped: {[(c.text, c.dropped) for c in dropped]}"

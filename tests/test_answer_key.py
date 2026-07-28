"""The synthetic canyon road's answer key, as assertions.

synth_road.py builds a road out of explicit arcs and straights, so we know
exactly what the engine should say. Each test below is one designed feature.
All seven passed in the Phase 0 validation; any failure here is a regression.

Designed values come from synth_road.build_road() — keep them in sync.
"""
import pytest

# Designed geometry, straight from synth_road.build_road().
DESIGNED = {
    "right_4":      {"direction": "R", "radius": 90.0, "severity": 4},
    "left_2":       {"direction": "L", "radius": 30.0, "severity": 2},
    "right_3_tight": {"direction": "R", "radius": 50.0, "severity": 3},
    "hairpin_left": {"direction": "L", "radius": 12.0, "severity": "hairpin"},
    "right_3_long": {"direction": "R", "radius": 60.0, "severity": 3},
    "left_4_crest": {"direction": "L", "radius": 80.0, "severity": 4},
}
DESIGNED_CREST_M = 829.0


def by_order(corners, idx):
    """Corners in arc-length order; the road is built so order is stable."""
    return sorted(corners, key=lambda c: c.s0)[idx]


def test_six_corners_detected(corners):
    assert len(corners) == 6, f"expected 6 corners, got {len(corners)}"


# --- Feature 1: right 4 -----------------------------------------------------

def test_feature_1_right_4(corners):
    c = by_order(corners, 0)
    assert c.direction == "R"
    assert c.severity == DESIGNED["right_4"]["severity"]


# --- Feature 2: linked "into left 2" ----------------------------------------

def test_feature_2_left_2(corners):
    c = by_order(corners, 1)
    assert c.direction == "L"
    assert c.severity == DESIGNED["left_2"]["severity"]


def test_feature_2_linking(corners, analyzed):
    """The 40 m gap after the right 4 must produce an 'into' call."""
    assert by_order(corners, 0).linked_to_next is True
    assert any("into left 2" in text for _, text in analyzed["events"]), \
        f"no 'into left 2' in script:\n{analyzed['script']}"


# --- Feature 3: right 3 tightens (decreasing radius) ------------------------

def test_feature_3_tightens(corners):
    c = by_order(corners, 2)
    assert c.direction == "R"
    assert c.severity == DESIGNED["right_3_tight"]["severity"]
    assert "tightens" in c.modifiers, \
        "decreasing-radius corner lost its 'tightens' modifier — this is the " \
        "single most dangerous callout to get wrong"


# --- Feature 4: standalone blind crest --------------------------------------

def test_feature_4_standalone_crest(analyzed):
    loose = analyzed["loose_crests"]
    assert len(loose) == 1, f"expected 1 standalone crest, got {loose}"
    assert abs(loose[0] - DESIGNED_CREST_M) < 20, \
        f"crest at {loose[0]:.0f} m vs designed {DESIGNED_CREST_M:.0f} m"


# --- Feature 5: hairpin left ------------------------------------------------

def test_feature_5_hairpin(corners):
    c = by_order(corners, 3)
    assert c.direction == "L"
    assert c.severity == "hairpin"
    assert abs(c.min_radius - DESIGNED["hairpin_left"]["radius"]) < 3.0


# --- Feature 6: right 3 long ------------------------------------------------

def test_feature_6_long(corners):
    c = by_order(corners, 4)
    assert c.direction == "R"
    assert c.severity == DESIGNED["right_3_long"]["severity"]
    assert "long" in c.modifiers


# --- Feature 7: left 4 over crest, don't cut --------------------------------

def test_feature_7_crest_corner(corners):
    c = by_order(corners, 5)
    assert c.direction == "L"
    assert c.severity == DESIGNED["left_4_crest"]["severity"]
    assert "over crest" in c.modifiers
    assert "don't cut" in c.modifiers, \
        "blind apex lost its 'don't cut' — rider would cut into a blind crest"

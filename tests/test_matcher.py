"""Deciding which road the rider is on.

The dangerous failure here is not picking wrong once — it is FLAPPING, swapping
between two roads at a junction and re-announcing corners the rider has already
passed. A copilot that repeats itself is one the rider stops listening to, and a
warning nobody listens to is not a warning.
"""
import math

import numpy as np
import pytest

from matcher import Matcher, MAX_OFFROAD_M, SWITCH_PATIENCE
from build_bundle import build_index

M_PER_DEG_LAT = 110540.0


def m_per_deg_lon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def straight_road(name, lat0, lon0, bearing_deg, length_m, n=60):
    """A straight road from a point, as a bundle road dict."""
    br = math.radians(bearing_deg)
    d = np.linspace(0, length_m, n)
    dx, dy = math.sin(br) * d, math.cos(br) * d      # bearing 0 = north
    lat = lat0 + dy / M_PER_DEG_LAT
    lon = lon0 + dx / m_per_deg_lon(lat0)
    return {"name": name, "lon": list(lon), "lat": list(lat),
            "node_s": list(d), "callouts": []}


def bundle_of(*roads):
    rs = list(roads)
    return {"name": "test", "cell": 0.01, "roads": rs, "index": build_index(rs)}


LAT, LON = 37.35, -122.27


def enu_heading(bearing_deg):
    """Bundle geometry is ENU, so heading is atan2(dy, dx) with x east."""
    br = math.radians(bearing_deg)
    return math.atan2(math.cos(br), math.sin(br))


# --- basic matching -------------------------------------------------------

def test_matches_the_only_road():
    b = bundle_of(straight_road("A", LAT, LON, 0, 2000))
    m = Matcher(b)
    got = m.update(LON, LAT + 500 / M_PER_DEG_LAT)
    assert got is not None and got["name"] == "A"
    assert got["s"] == pytest.approx(500, abs=30)


def test_reports_none_when_far_from_every_road():
    b = bundle_of(straight_road("A", LAT, LON, 0, 2000))
    m = Matcher(b)
    off = m.update(LON + 0.02, LAT)          # ~1.8 km away
    assert off is None, "claimed a match from far off the network"


def test_arc_length_advances_along_the_road():
    b = bundle_of(straight_road("A", LAT, LON, 0, 2000))
    m = Matcher(b)
    seen = [m.update(LON, LAT + d / M_PER_DEG_LAT)["s"] for d in (100, 400, 900)]
    assert seen == sorted(seen), f"position went backwards: {seen}"


# --- heading disambiguation ----------------------------------------------

def test_heading_picks_the_road_you_are_travelling_along():
    """Two roads crossing at a point. Distance alone cannot choose; heading can.

    This is the overpass and frontage-road case, and the switchback case the
    Dragon produces where two stretches pass within metres running opposite ways.
    """
    ns = straight_road("north-south", LAT, LON, 0, 2000)
    ew = straight_road("east-west", LAT, LON, 90, 2000)
    m = Matcher(bundle_of(ns, ew))
    # sit exactly on the crossing point but travelling east
    got = m.update(LON, LAT, heading=enu_heading(90), speed=20)
    assert got["name"] == "east-west", f"heading ignored, picked {got['name']}"


def test_opposite_direction_still_matches_the_same_road():
    """A road is bidirectional: 180 degrees out is a match, not a mismatch."""
    b = bundle_of(straight_road("A", LAT, LON, 0, 2000))
    m = Matcher(b)
    got = m.update(LON, LAT + 500 / M_PER_DEG_LAT,
                   heading=enu_heading(180), speed=20)
    assert got is not None and got["name"] == "A"


def test_heading_is_ignored_when_barely_moving():
    """GPS heading is noise at walking pace; it must not throw the match."""
    b = bundle_of(straight_road("A", LAT, LON, 0, 2000))
    m = Matcher(b)
    got = m.update(LON, LAT + 500 / M_PER_DEG_LAT,
                   heading=enu_heading(90), speed=0.4)
    assert got is not None and got["name"] == "A"


# --- the failure that matters --------------------------------------------

def test_does_not_flap_between_parallel_roads():
    """Two roads 12 m apart, GPS noise straddling both.

    Without hysteresis the lead trades every fix and every corner is
    re-announced. This is the single most important property of the matcher.
    """
    a = straight_road("A", LAT, LON, 0, 2000)
    b = straight_road("B", LAT, LON + 12 / m_per_deg_lon(LAT), 0, 2000)
    m = Matcher(bundle_of(a, b))
    rng = np.random.default_rng(4)
    switches = 0
    prev = None
    for i in range(120):
        lat = LAT + (i * 12) / M_PER_DEG_LAT
        lon = LON + rng.normal(0, 8) / m_per_deg_lon(LAT)   # 8 m of noise
        got = m.update(lon, lat, heading=enu_heading(0), speed=20)
        if got is None:
            continue
        if prev is not None and got["name"] != prev:
            switches += 1
        prev = got["name"]
    assert switches <= 2, f"flapped {switches} times between parallel roads"


def test_switch_requires_sustained_evidence():
    """A single stray fix on another road must not move us."""
    a = straight_road("A", LAT, LON, 0, 2000)
    b = straight_road("B", LAT, LON + 40 / m_per_deg_lon(LAT), 0, 2000)
    m = Matcher(bundle_of(a, b))
    for i in range(10):
        m.update(LON, LAT + i * 20 / M_PER_DEG_LAT,
                 heading=enu_heading(0), speed=20)
    assert m.current is not None
    on_a = m.current
    # one fix squarely on B
    m.update(LON + 40 / m_per_deg_lon(LAT), LAT + 200 / M_PER_DEG_LAT,
             heading=enu_heading(0), speed=20)
    assert m.current == on_a, "switched road on a single stray fix"


def test_a_genuine_turn_does_switch():
    """Hysteresis must not prevent a real change of road."""
    ns = straight_road("north-south", LAT, LON, 0, 2000)
    ew = straight_road("east-west", LAT, LON, 90, 2000)
    m = Matcher(bundle_of(ns, ew))
    for i in range(6):
        m.update(LON, LAT + i * 30 / M_PER_DEG_LAT,
                 heading=enu_heading(0), speed=20)
    start = m.roads[m.current]["name"]
    for i in range(1, SWITCH_PATIENCE + 4):
        m.update(LON + (i * 40) / m_per_deg_lon(LAT), LAT,
                 heading=enu_heading(90), speed=20)
    assert m.roads[m.current]["name"] != start, "never switched after turning off"


def test_switch_fires_the_hook():
    """The app clears its spoken set on a switch, so the new road's corners are
    announced rather than suppressed as already-said."""
    ns = straight_road("north-south", LAT, LON, 0, 2000)
    ew = straight_road("east-west", LAT, LON, 90, 2000)
    m = Matcher(bundle_of(ns, ew))
    fired = []
    m.on_switch = lambda: fired.append(1)
    for i in range(6):
        m.update(LON, LAT + i * 30 / M_PER_DEG_LAT, heading=enu_heading(0), speed=20)
    for i in range(1, SWITCH_PATIENCE + 4):
        m.update(LON + (i * 40) / m_per_deg_lon(LAT), LAT,
                 heading=enu_heading(90), speed=20)
    assert fired, "switching road did not notify the app"


def test_index_lookup_is_local():
    """The point of the grid: a fix must not scan every node in the bundle."""
    roads = [straight_road(f"R{i}", LAT + i * 0.05, LON, 0, 2000)
             for i in range(40)]
    b = bundle_of(*roads)
    m = Matcher(b)
    cands = m._candidates(LON, LAT)
    total_nodes = sum(len(r["lon"]) for r in roads)
    assert len(cands) < total_nodes / 5, (
        f"grid returned {len(cands)} of {total_nodes} nodes — not localising"
    )

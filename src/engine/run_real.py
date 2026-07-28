"""Run the pacenote engine on a real road fetched by fetch_osm.py.

Usage: python run_real.py road.json
"""
import json
import sys
import numpy as np
from geometry import lonlat_to_xy, resample, signed_radius, smooth_radius
from corners import (find_corners, add_shape_modifiers, find_crests,
                     attach_crests, link_corners)
from script_gen import build_script


def main(path):
    with open(path) as f:
        road = json.load(f)
    lon = np.array(road["lon"])
    lat = np.array(road["lat"])
    ele = np.array(road["ele"]) if road.get("ele") else None

    x, y = lonlat_to_xy(lon, lat)
    s, xi, yi, zi = resample(x, y, ele, spacing=5.0)
    r = signed_radius(xi, yi, window=3)
    rs = smooth_radius(r, k=7)  # more smoothing for real OSM noise

    corners = find_corners(s, rs)
    corners = add_shape_modifiers(corners, s, rs)
    crests = find_crests(s, zi) if zi is not None else []
    loose = attach_crests(corners, crests)
    corners = link_corners(corners)

    events, script = build_script(corners, loose, s[-1])
    print(f"\nPACENOTES: {road.get('name', path)}\n")
    print(script)

    # quick fun-density score: corners per km weighted by severity
    weight = {"hairpin": 7, 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1}
    fun = sum(weight[c.severity] for c in corners) / max(s[-1] / 1000, 0.1)
    print(f"\nfun density: {fun:.1f} (weighted corners per km)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "road.json")

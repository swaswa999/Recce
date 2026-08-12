"""Export a compact pacenote pack for live playback on a phone.

The rendered WAV is open-loop and drifts (see trace.py). A phone knows where it
actually is, so it can speak each callout when the rider is genuinely N seconds
away — which is the whole point of the product and the one thing a fixed track
cannot do.

This writes the minimum a live player needs:
  - the road polyline, for map-matching GPS to a position along the road
  - each callout's position, text, kind and severity

Usage:
    python3 export_pack.py ../../roads/tail-of-the-dragon.json -o pack.json
"""
import argparse
import json

import numpy as np

from geometry import lonlat_to_xy
from pipeline import analyze
from timing import build_callouts


def build_pack(path, name=None, precision=5):
    with open(path) as f:
        road = json.load(f)
    lon = np.array(road["lon"])
    lat = np.array(road["lat"])
    ele = np.array(road["ele"]) if road.get("ele") else None
    x, y = lonlat_to_xy(lon, lat)

    s, corners, loose = analyze(x, y, ele)
    callouts = build_callouts(corners, loose)

    # Arc-length position of each raw node, so the player can turn a matched
    # node index into metres along the road without re-deriving the geometry.
    d = np.hypot(np.diff(x), np.diff(y))
    node_s = np.concatenate([[0.0], np.cumsum(d)])

    return {
        "name": name or road.get("name", "road"),
        "length_m": round(float(node_s[-1]), 1),
        "lon": [round(float(v), precision) for v in lon],
        "lat": [round(float(v), precision) for v in lat],
        "node_s": [round(float(v), 1) for v in node_s],
        "callouts": [
            {
                "s": round(float(c.anchor_s), 1),
                "text": c.text,
                "kind": c.kind,
                # rally scale runs backwards from difficulty, so carry a plain
                # rank the player can threshold on for verbosity
                "rank": 0 if c.severity == "hairpin" else (
                    c.severity if isinstance(c.severity, int) else 9),
                "warn": bool(c.is_warning),
            }
            for c in callouts
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("road", help="road.json from fetch_osm.py")
    ap.add_argument("-o", "--out", default="pack.json")
    ap.add_argument("--name")
    args = ap.parse_args()

    pack = build_pack(args.road, name=args.name)
    with open(args.out, "w") as f:
        json.dump(pack, f, separators=(",", ":"))

    warns = sum(1 for c in pack["callouts"] if c["warn"])
    import os
    print(f"{pack['name']}: {pack['length_m'] / 1000:.1f} km, "
          f"{len(pack['callouts'])} callouts ({warns} warnings), "
          f"{len(pack['lon'])} nodes")
    print(f"wrote {args.out} ({os.path.getsize(args.out) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

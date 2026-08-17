"""Build a multi-road pacenote bundle for a region, from an OSM PBF extract.

One road at a time was route-first: the rider picked a road. A bundle holds
every qualifying road in a region, so the app can work out which one you are on
and have the notes ready — no route chosen, and nothing fetched mid-ride.

Ways are grouped by name and stitched before analysis. OSM splits a road at
arbitrary points (a bridge, a speed-limit change), and analysing each fragment
separately would cut corners in half at those boundaries and mis-measure them.

Usage:
    python3 build_bundle.py california.osm.pbf --bbox 37.0,-122.5,37.6,-121.8 \
        --name "Bay Area" -o bundle.json
"""
import argparse
import json
import math
from collections import defaultdict

import numpy as np
import osmium

from geometry import lonlat_to_xy
from pipeline import analyze
from timing import build_callouts
from survey import RIDEABLE, MAX_TRUSTED_MEDIAN_SPACING

# Three tiers, measured by decimating synth_stress.py at 16 phases per spacing:
#
#   <= 25 m   full callouts. Direction, severity and shape all hold.
#   25-40 m   DIRECTION ONLY. Direction is still perfect at 35 m and 40 m while
#             severity starts reading optimistic at 40 m, so "there is a right
#             here" is true and "it is a 3" is not.
#   >  40 m   nothing. Direction itself starts flipping (4 of 80 wrong at 50 m)
#             and corners go missing entirely, so there is no honest callout left.
#
# The point of the middle tier is that silence is not the only alternative to a
# full callout. A rider told a corner exists, without a number, still gets to
# roll off — and a number withheld cannot be an optimistic number.
MAX_DIRECTION_ONLY_SPACING = 40.0

# Grid cell for the spatial index, in degrees. ~1.1 km at this latitude, so a
# fix plus its eight neighbours covers everything within ~1.5 km — far more than
# GPS error, and small enough that a cell holds only a handful of segments.
CELL = 0.01


class WayCollector(osmium.SimpleHandler):
    def __init__(self, bbox):
        super().__init__()
        self.bbox = bbox
        self.by_name = defaultdict(list)

    def way(self, w):
        if w.tags.get("highway") not in RIDEABLE:
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return
        s, wst, n, e = self.bbox
        if not any(s <= la <= n and wst <= lo <= e for lo, la in coords):
            return
        tags = w.tags
        name = tags.get("name") or tags.get("ref") or f"way{w.id}"
        kind = "tunnel" if tags.get("tunnel") else (
            "bridge" if tags.get("bridge") else "")
        self.by_name[name].append([(lo, la, kind) for lo, la in coords])


def stitch(segments):
    """Join ways end-to-end on POSITION, returning one or more chains.

    Ways that do not connect become separate chains rather than being dropped —
    a name like "Skyline Boulevard" legitimately covers disjoint stretches.
    """
    at = lambda p: (p[0], p[1])
    carry = lambda p, q: p if p[2] else (p[0], p[1], q[2])
    chains = []
    pending = list(segments)
    while pending:
        chain = pending.pop(0)
        changed = True
        while pending and changed:
            changed = False
            for i, seg in enumerate(pending):
                if at(seg[0]) == at(chain[-1]):
                    chain[-1] = carry(chain[-1], seg[0]); chain = chain + seg[1:]
                elif at(seg[-1]) == at(chain[-1]):
                    chain[-1] = carry(chain[-1], seg[-1]); chain = chain + seg[-2::-1]
                elif at(seg[-1]) == at(chain[0]):
                    chain[0] = carry(chain[0], seg[-1]); chain = seg[:-1] + chain
                elif at(seg[0]) == at(chain[0]):
                    chain[0] = carry(chain[0], seg[0]); chain = seg[::-1][:-1] + chain
                else:
                    continue
                pending.pop(i); changed = True; break
        chains.append(chain)
    return chains


def road_from_chain(name, chain, with_elevation=True):
    lon = np.array([p[0] for p in chain])
    lat = np.array([p[1] for p in chain])
    structure = [p[2] for p in chain]
    x, y = lonlat_to_xy(lon, lat)
    node_s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    if node_s[-1] < 300:
        return None

    gaps = np.diff(node_s)
    median_gap = float(np.median(gaps))
    if median_gap > MAX_DIRECTION_ONLY_SPACING:
        return None
    rated = median_gap <= MAX_TRUSTED_MEDIAN_SPACING

    ele = None
    if with_elevation:
        try:
            from elevation import sample_elevation
            ele = sample_elevation(lon, lat, verbose=False)
        except Exception:
            ele = None

    try:
        s, corners, loose = analyze(x, y, np.array(ele) if ele else None)
    except Exception:
        return None
    if not corners:
        return None

    if rated:
        from features import road_features
        feats = road_features({"structure": structure, "points": []}, node_s)
        callouts = build_callouts(corners, loose, features=feats)
        out_calls = [
            {"s": round(float(c.anchor_s), 1), "text": c.text, "kind": c.kind,
             "rank": 0 if c.severity == "hairpin" else (
                 c.severity if isinstance(c.severity, int) else 9),
             "warn": bool(c.is_warning), "rated": True}
            for c in callouts
        ]
    else:
        # Direction only. No severity, no shape, no crest — nothing whose
        # magnitude this geometry cannot support. Rank 0 so no verbosity mode
        # can suppress them: an unrated corner is the LEAST described, and
        # dropping it too would leave the rider with nothing at all.
        out_calls = [
            {"s": round(float(c.s0), 1),
             "text": "left" if c.direction == "L" else "right",
             "kind": "corner", "rank": 0, "warn": False, "rated": False}
            for c in corners
        ]
    if not out_calls:
        return None

    return {
        "name": name,
        "rated": rated,
        "node_gap": round(median_gap, 1),
        "lon": [round(float(v), 5) for v in lon],
        "lat": [round(float(v), 5) for v in lat],
        "node_s": [round(float(v), 1) for v in node_s],
        "callouts": out_calls,
    }


def build_index(roads, cell=CELL):
    """cell key -> [(road index, node index), ...] for nearest-segment search."""
    idx = defaultdict(list)
    for ri, r in enumerate(roads):
        for ni, (lo, la) in enumerate(zip(r["lon"], r["lat"])):
            key = f"{int(math.floor(la / cell))},{int(math.floor(lo / cell))}"
            idx[key].append([ri, ni])
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("--bbox", required=True, help="south,west,north,east")
    ap.add_argument("--name", default="region")
    ap.add_argument("-o", "--out", default="bundle.json")
    ap.add_argument("--no-elevation", action="store_true",
                    help="skip 3DEP sampling; produces no crest callouts")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    h = WayCollector(bbox)
    print(f"scanning {args.pbf} within {bbox}")
    h.apply_file(args.pbf, locations=True, idx="flex_mem")
    print(f"  {len(h.by_name):,} named road groups in the box")

    roads, skipped = [], 0
    for i, (name, segs) in enumerate(sorted(h.by_name.items())):
        if i % 250 == 0 and i:
            print(f"  processed {i:,}/{len(h.by_name):,}, kept {len(roads)}")
        for chain in stitch(segs):
            r = road_from_chain(name, chain,
                                with_elevation=not args.no_elevation)
            if r is None:
                skipped += 1
            else:
                roads.append(r)

    km = sum(r["node_s"][-1] for r in roads) / 1000
    calls = sum(len(r["callouts"]) for r in roads)
    rated = [r for r in roads if r["rated"]]
    unrated = [r for r in roads if not r["rated"]]
    bundle = {"name": args.name, "cell": CELL, "roads": roads,
              "index": build_index(roads)}
    with open(args.out, "w") as f:
        json.dump(bundle, f, separators=(",", ":"))

    import os
    print(f"\n{args.name}: {len(roads)} roads, {km:,.0f} km, {calls:,} callouts")
    print(f"  fully rated:    {len(rated):5d} roads  "
          f"{sum(r['node_s'][-1] for r in rated)/1000:7,.0f} km")
    print(f"  direction only: {len(unrated):5d} roads  "
          f"{sum(r['node_s'][-1] for r in unrated)/1000:7,.0f} km  "
          f"(too sparse for severity)")
    print(f"  {skipped:,} chains skipped (too short, too sparse, or no corners)")
    print(f"  wrote {args.out} ({os.path.getsize(args.out)/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()

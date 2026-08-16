"""Survey a region's roads from an OSM PBF extract: how much is rideable, and
how much of that has geometry good enough to trust.

This answers the question that sizes everything else. "All of California"
without a quality filter is 394,000 km; the number that matters is how much
survives `node_spacing_stats`, because a road too sparsely mapped to measure
curvature produces callouts that read optimistic — which is the one failure this
product cannot have.

Usage:
    python3 survey.py california.osm.pbf --bbox 36.9,-122.6,37.9,-121.6
    python3 survey.py california.osm.pbf            # whole extract, slow
"""
import argparse
import json
import math
import sys
from collections import defaultdict

import numpy as np
import osmium

# Road classes worth pacenotes. Motorways are straight and dull, residential and
# service roads are urban clutter, tracks are not pavement.
RIDEABLE = {"primary", "secondary", "tertiary", "unclassified",
            "primary_link", "secondary_link", "tertiary_link"}

# Road-level thresholds, now only a coarse screen. The real gate is per corner
# (corners.mark_shape_trust), which compares local spacing to that corner's own
# radius and suppresses shape modifiers rather than refusing the road.
#
# Measured on synth_stress.py: shape modifiers stay correct to ~22 m even for a
# 14 m hairpin, and beyond that the per-corner gate suppresses them rather than
# emitting anything wrong — zero false modifiers from 8 m through 40 m. Above
# ~40 m the geometry is degraded enough that corner DETECTION itself is
# unreliable, which no per-corner gate can rescue.
MAX_TRUSTED_MEDIAN_SPACING = 25.0
MAX_TRUSTED_P90_SPACING = 45.0


def _hav_len(lons, lats):
    """Length in metres of a lon/lat polyline, and its node gaps."""
    lat0 = math.radians(float(np.mean(lats)))
    x = np.asarray(lons) * 111320.0 * math.cos(lat0)
    y = np.asarray(lats) * 110540.0
    gaps = np.hypot(np.diff(x), np.diff(y))
    return float(gaps.sum()), gaps


class RoadSurvey(osmium.SimpleHandler):
    def __init__(self, bbox=None):
        super().__init__()
        self.bbox = bbox            # (south, west, north, east)
        self.roads = []
        self.seen = 0

    def _inside(self, lon, lat):
        if self.bbox is None:
            return True
        s, w, n, e = self.bbox
        return s <= lat <= n and w <= lon <= e

    def way(self, w):
        tags = w.tags
        hw = tags.get("highway")
        if hw not in RIDEABLE:
            return
        self.seen += 1
        try:
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 3:
            return
        if not any(self._inside(lo, la) for lo, la in coords):
            return

        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        length, gaps = _hav_len(lons, lats)
        if length < 200:            # too short to carry a callout
            return
        self.roads.append({
            "id": w.id,
            "name": tags.get("name") or tags.get("ref") or "",
            "class": hw,
            "len_m": length,
            "nodes": len(coords),
            "median_gap": float(np.median(gaps)),
            "p90_gap": float(np.percentile(gaps, 90)),
        })


def summarize(roads):
    total_km = sum(r["len_m"] for r in roads) / 1000
    passes_median = [r for r in roads if r["median_gap"] <= MAX_TRUSTED_MEDIAN_SPACING]
    passes_both = [r for r in passes_median if r["p90_gap"] <= MAX_TRUSTED_P90_SPACING]
    km = lambda rs: sum(r["len_m"] for r in rs) / 1000

    print(f"\nrideable roads found: {len(roads)}  ({total_km:,.0f} km)")
    print(f"  pass median gate (<= {MAX_TRUSTED_MEDIAN_SPACING:.0f} m): "
          f"{len(passes_median):5d} roads  {km(passes_median):8,.0f} km  "
          f"({100*km(passes_median)/max(total_km,1):.0f}%)")
    print(f"  pass median AND p90 (<= {MAX_TRUSTED_P90_SPACING:.0f} m): "
          f"{len(passes_both):5d} roads  {km(passes_both):8,.0f} km  "
          f"({100*km(passes_both)/max(total_km,1):.0f}%)")

    print(f"\nby road class (km, and % passing both gates):")
    by = defaultdict(lambda: [0.0, 0.0])
    for r in roads:
        by[r["class"]][0] += r["len_m"] / 1000
        if r["median_gap"] <= MAX_TRUSTED_MEDIAN_SPACING and \
           r["p90_gap"] <= MAX_TRUSTED_P90_SPACING:
            by[r["class"]][1] += r["len_m"] / 1000
    for cls, (tot, good) in sorted(by.items(), key=lambda kv: -kv[1][0]):
        print(f"  {cls:16} {tot:8,.0f} km   {100*good/max(tot,1):3.0f}% usable")

    gaps = np.array([r["median_gap"] for r in roads])
    print(f"\nnode spacing across all rideable roads:")
    for p in (10, 25, 50, 75, 90):
        print(f"  p{p:<2} {np.percentile(gaps, p):5.1f} m")

    # 1.96 KB/km measured on two real roads
    print(f"\npack size at 1.96 KB/km:")
    print(f"  all rideable   {total_km*1.96/1024:7.1f} MB")
    print(f"  passing gates  {km(passes_both)*1.96/1024:7.1f} MB")
    return passes_both


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("--bbox", help="south,west,north,east")
    ap.add_argument("-o", "--out", help="write passing roads as JSON")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(",")) if args.bbox else None
    h = RoadSurvey(bbox=bbox)
    print(f"scanning {args.pbf}" + (f" within {bbox}" if bbox else " (whole extract)"))
    h.apply_file(args.pbf, locations=True, idx="flex_mem")
    print(f"  {h.seen:,} rideable-class ways seen, {len(h.roads):,} kept "
          f"(>=200 m, >=3 nodes, in bbox)")

    good = summarize(h.roads)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(good, f)
        print(f"\nwrote {len(good)} passing roads to {args.out}")


if __name__ == "__main__":
    main()

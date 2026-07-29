"""Run the pacenote engine on a real road fetched by fetch_osm.py.

Usage: python3 run_real.py road.json [--force]
"""
import argparse
import json
import sys
import numpy as np

from geometry import lonlat_to_xy, node_spacing_stats
from pipeline import analyze_to_script, elevation_report

# Below this node density the geometry cannot support trustworthy pacenotes:
# resampling finer than the survey manufactures kinks that a short-window arc
# fit reads as real curvature.
#
# Measured over 100 decimation phases of the answer-key road (10 phases is not
# enough — it straddles the onset and reads clean): false "opens" is 0/100
# through 14 m, then 3/100 at 16 m, 11/100 at 18 m, 29/100 at 20 m. When it
# fires it lands on the real hairpin as "hairpin, opens", the most dangerous
# string this engine can emit.
#
# 12 m keeps margin below the 16 m onset without refusing well-traced roads. A
# gate that refuses every mountain road gets loosened or bypassed, and then the
# false modifiers ship anyway.
#
# Provisional until Phase C calibrates on real OSM geometry — see
# docs/ARCHITECTURE.md, "The information limit".
MAX_TRUSTED_MEDIAN_SPACING = 12.0

# The median alone is not enough. The Tail of the Dragon has a 9.7 m median —
# comfortably inside the gate — while 40% of its gaps exceed 12 m, p90 is 30 m
# and the largest is 176 m. A road can pass on its median and still be
# untrustworthy across a large fraction of its length.
MAX_TRUSTED_P90_SPACING = 25.0


def main(path, force=False):
    with open(path) as f:
        road = json.load(f)
    lon = np.array(road["lon"])
    lat = np.array(road["lat"])
    ele = np.array(road["ele"]) if road.get("ele") else None

    x, y = lonlat_to_xy(lon, lat)

    med, p90, mx = node_spacing_stats(x, y)
    frac_coarse = float(np.mean(np.hypot(np.diff(x), np.diff(y))
                                > MAX_TRUSTED_MEDIAN_SPACING))
    print(f"node spacing: median {med:.1f} m, p90 {p90:.1f} m, max {mx:.1f} m "
          f"({frac_coarse:.0%} of gaps over {MAX_TRUSTED_MEDIAN_SPACING:.0f} m)")

    # Report the elevation verdict. analyze() enforces it either way — this only
    # surfaces the reason so a suppressed crest channel is visible rather than
    # looking like a road with no crests on it.
    quantum, p95, verdict = elevation_report(x, y, ele)
    if ele is not None:
        # Label the quantum. Printed bare it misleads in both directions: a
        # continuous source shows "0.00 m", which reads like missing data, while
        # a quantized one shows a reassuringly small-sounding "1.00 m".
        kind = "quantized" if quantum > 0.01 else "continuous"
        print(f"elevation: quantum {quantum:.4f} m ({kind}), "
              f"p95 gradient {p95:.0%} -> {verdict}")
        if verdict != "ok":
            print("\n*** DEGRADED: crest detection SUPPRESSED on this road.")
            print(f"*** {verdict}.")
            print("*** Corner severity and shape are still usable; 'over crest'")
            print("*** and 'don't cut' are not. Emitting them anyway buries the")
            print("*** real crests among false ones, which is worse than silence.")
            print("*** Needs a better DEM (SRTM tiles read directly, or LIDAR)")
            print("*** than a point-lookup elevation API.\n")
    else:
        print("elevation: absent -> crest warnings will not be emitted")

    if p90 > MAX_TRUSTED_P90_SPACING:
        print(f"\n*** WARNING: p90 node spacing {p90:.1f} m exceeds "
              f"{MAX_TRUSTED_P90_SPACING:.0f} m.")
        print("*** The median passes but a large fraction of this road is too")
        print("*** sparse to trust. Severity on those stretches is unreliable.\n")

    if med > MAX_TRUSTED_MEDIAN_SPACING:
        # Refuse, don't warn. A printed warning above a full pacenote script
        # gets scrolled past, and the output looks authoritative either way.
        msg = (
            f"\nREFUSING: median node spacing {med:.1f} m exceeds the "
            f"{MAX_TRUSTED_MEDIAN_SPACING:.0f} m trust threshold.\n"
            "Severity and shape modifiers on this road are NOT reliable: tight\n"
            "corners can read flatter than they are, and false 'opens'\n"
            "modifiers occur — including on hairpins. Do not ship as a route\n"
            "pack. This is what osm-data-quality-checker gates in Phase C.\n"
            "\nRe-run with --force to see the output anyway, for diagnosis only.\n"
        )
        if not force:
            sys.exit(msg)
        print(msg)
        print(">>> --force given: output below is UNTRUSTWORTHY <<<\n")

    s, corners, loose, events, script = analyze_to_script(x, y, ele)
    print(f"\nPACENOTES: {road.get('name', path)}"
          f"{'' if verdict == 'ok' else '  [no crest data]'}\n")
    print(script)

    # fun-density score: corners per km weighted by severity. Reused later as
    # the road-fun function for curvy routing (Phase 5).
    weight = {"hairpin": 7, 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1}
    fun = sum(weight[c.severity] for c in corners) / max(s[-1] / 1000, 0.1)
    print(f"\nfun density: {fun:.1f} (weighted corners per km)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("road", nargs="?", default="road.json")
    ap.add_argument("--force", action="store_true",
                    help="process a road that fails the density gate "
                         "(diagnosis only — output is untrustworthy)")
    a = ap.parse_args()
    main(a.road, force=a.force)

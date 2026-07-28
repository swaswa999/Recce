"""Phase 0 validation: run the pacenote engine on a road with a known answer key."""
import numpy as np
from geometry import resample, signed_radius, smooth_radius
from corners import (find_corners, add_shape_modifiers, find_crests,
                     attach_crests, link_corners)
from script_gen import build_script
from synth_road import build_road


def main():
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

    print("=" * 56)
    print("GROUND TRUTH (what we built into the road)")
    print("=" * 56)
    for t in truth:
        print("  " + t)
    print()
    print("=" * 56)
    print("ENGINE OUTPUT (what the pipeline detected)")
    print("=" * 56)
    print(script)
    print()
    print("Corner detail:")
    for c in corners:
        link = " ->into next" if c.linked_to_next else ""
        print(f"  {c.s0:6.0f}-{c.s1:6.0f}m  {c.direction} sev={c.severity}"
              f"  minR={c.min_radius:5.1f}m  len={c.length:5.0f}m"
              f"  mods={c.modifiers}{link}")


if __name__ == "__main__":
    main()

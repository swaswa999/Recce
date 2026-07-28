"""Phase 0 validation: run the pacenote engine on a road with a known answer key."""
from pipeline import analyze_to_script
from synth_road import build_road


def main():
    x, y, z, truth, road_len = build_road()
    s, corners, loose, events, script = analyze_to_script(x, y, z)

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

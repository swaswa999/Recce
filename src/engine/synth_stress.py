"""Second synthetic road, built to stress what the answer-key road cannot test.

`synth_road.py` has three weaknesses this road fixes:

1. **No transition spirals.** It steps straight-to-arc instantaneously, which no
   built road does — an instantaneous curvature change is undriveable. Those
   discontinuities are read as real curvature by short-window estimators, so the
   road tests an artifact rather than the road.
2. **No sustained minimum.** Its tightening corner reaches 50.67 m over ~0.85 m
   of arc, so no windowed estimator can resolve it and the "within 10%" accuracy
   goal is unmeasurable. Here every corner holds its minimum radius over a
   plateau long enough to measure.
3. **No genuinely opening corner.** So the suite can only check that `opens` is
   never emitted falsely, never that it IS emitted when a corner really opens.
   A modifier that never fires is as broken as one that fires wrongly.

Built by integrating a curvature profile rather than concatenating arcs, which is
what makes spirals natural to express.
"""
import numpy as np

# Clothoid transition length. Real roads spiral in over tens of metres.
SPIRAL = 30.0


class _Builder:
    """Accumulates curvature segments and tracks arc position as it goes.

    Position bookkeeping lives here rather than being hand-computed in the road
    definition: hand-computed spans silently drift as soon as a segment length
    changes, and a test matching the wrong span reports "fragmented" instead of
    "your span is wrong".
    """

    def __init__(self, step):
        self.step = step
        self.segs = []  # (length, kappa_start, kappa_end)
        self.pos = 0.0  # arc length consumed so far

    def straight(self, length):
        self.segs.append((length, 0.0, 0.0))
        self.pos += length
        return self

    def spiral(self, length, r_from, r_to, direction):
        sign = 1.0 if direction == "L" else -1.0
        k0 = 0.0 if r_from is None else sign / r_from
        k1 = 0.0 if r_to is None else sign / r_to
        self.segs.append((length, k0, k1))
        self.pos += length
        return self

    def arc(self, length, radius, direction):
        sign = 1.0 if direction == "L" else -1.0
        k = sign / radius
        self.segs.append((length, k, k))
        self.pos += length
        return self

    def mark(self):
        return self.pos

    def build(self):
        """Integrate the curvature profile into a polyline."""
        xs, ys, ss, ks = [0.0], [0.0], [0.0], []
        heading = 0.0
        s = 0.0
        for length, k0, k1 in self.segs:
            n = max(1, int(round(length / self.step)))
            for i in range(n):
                frac = (i + 0.5) / n
                k = k0 + (k1 - k0) * frac
                heading += k * self.step
                x = xs[-1] + self.step * np.cos(heading)
                y = ys[-1] + self.step * np.sin(heading)
                s += self.step
                xs.append(x)
                ys.append(y)
                ss.append(s)
                ks.append(k)
        return (np.array(xs), np.array(ys), np.array(ss), np.array(ks))


def build_stress_road(step=1.0):
    """Returns (x, y, z, truth, road_len).

    `truth` is a list of dicts, not prose — tests consume it directly:
      {name, direction, min_radius, severity, modifiers, s_hint}
    """
    b = _Builder(step)
    truth = []

    def record(name, direction, min_radius, severity, modifiers, forbid,
               start, end):
        # pad the span so a corner detected slightly wide still matches; the
        # engine's boundaries sit a few metres outside the spiral by design
        truth.append(dict(name=name, direction=direction,
                          min_radius=min_radius, severity=severity,
                          modifiers=modifiers, forbid=forbid,
                          s_hint=(start - 25, end + 25)))

    # 1 --- plain right 4, constant radius, properly spiralled in and out.
    b.straight(150)
    a = b.mark()
    b.spiral(SPIRAL, None, 100.0, "R")
    b.arc(80, 100.0, "R")
    b.spiral(SPIRAL, 100.0, None, "R")
    record("right_4", "R", 100.0, 4, [], ["tightens", "opens"], a, b.mark())

    # 2 --- decreasing radius with a SUSTAINED minimum. This is the corner the
    # answer-key road cannot test: 45 m is held for 50 m of arc, so a windowed
    # estimator can actually resolve it.
    b.straight(120)
    a = b.mark()
    b.spiral(SPIRAL, None, 120.0, "R")
    b.spiral(110, 120.0, 45.0, "R")
    b.arc(50, 45.0, "R")
    b.spiral(SPIRAL, 45.0, None, "R")
    record("right_3_tightens", "R", 45.0, 3, ["tightens"], ["opens"],
           a, b.mark())

    # 3 --- genuinely OPENING corner. Tests the true positive for "opens".
    b.straight(140)
    a = b.mark()
    b.spiral(SPIRAL, None, 38.0, "L")
    b.arc(45, 38.0, "L")
    b.spiral(100, 38.0, 90.0, "L")
    b.spiral(SPIRAL, 90.0, None, "L")
    record("left_2_opens", "L", 38.0, 2, ["opens"], ["tightens"], a, b.mark())

    # 4 --- tight constant corner well inside band 1.
    b.straight(130)
    a = b.mark()
    b.spiral(SPIRAL, None, 20.0, "L")
    b.arc(45, 20.0, "L")
    b.spiral(SPIRAL, 20.0, None, "L")
    record("left_1", "L", 20.0, 1, [], ["tightens", "opens"], a, b.mark())

    # 5 --- spiralled hairpin, sustained.
    b.straight(160)
    a = b.mark()
    b.spiral(SPIRAL, None, 14.0, "R")
    b.arc(40, 14.0, "R")
    b.spiral(SPIRAL, 14.0, None, "R")
    record("hairpin_right", "R", 14.0, "hairpin", [], ["tightens", "opens"],
           a, b.mark())

    b.straight(200)

    x, y, s, k = b.build()

    # gentle climb, no crests: this road tests curvature, not elevation
    z = 0.02 * s
    return x, y, z, truth, float(s[-1])


def describe(truth):
    lines = []
    for t in truth:
        mods = (" " + " ".join(t["modifiers"])) if t["modifiers"] else ""
        sev = t["severity"]
        d = "left" if t["direction"] == "L" else "right"
        label = f"hairpin {d}" if sev == "hairpin" else f"{d} {sev}"
        lines.append(f"{label}{mods}  (R={t['min_radius']:.0f}m sustained)")
    return lines


if __name__ == "__main__":
    from pipeline import analyze_to_script

    x, y, z, truth, road_len = build_stress_road()
    print("=" * 56)
    print("STRESS ROAD GROUND TRUTH")
    print("=" * 56)
    for line in describe(truth):
        print("  " + line)
    s, corners, loose, events, script = analyze_to_script(x, y, z)
    print()
    print("=" * 56)
    print("ENGINE OUTPUT")
    print("=" * 56)
    print(script)
    print("\nCorner detail:")
    for c in corners:
        print(f"  {c.s0:6.0f}-{c.s1:6.0f}m  {c.direction} sev={c.severity}"
              f"  minR={c.min_radius:5.1f}m  mods={c.modifiers}")

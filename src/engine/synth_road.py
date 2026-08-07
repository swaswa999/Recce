"""Synthetic canyon road with a known answer key.

Build a road out of explicit segments (straights, arcs, compound arcs) so we
know exactly what the pacenote engine SHOULD say, then check it says it.
"""
import numpy as np


def build_road(step=2.0):
    """Returns x, y, z arrays (meters) plus a human-readable ground truth list."""
    pts = [(0.0, 0.0)]
    heading = 0.0  # radians, 0 = east

    def straight(length):
        nonlocal heading
        x, y = pts[-1]
        n = int(length / step)
        for _ in range(n):
            x += step * np.cos(heading)
            y += step * np.sin(heading)
            pts.append((x, y))

    def arc(radius, angle_deg, direction, radius_end=None):
        """direction 'L' or 'R'. radius_end for compound (tightening) corners."""
        nonlocal heading
        sign = 1.0 if direction == "L" else -1.0
        total = np.radians(angle_deg)
        r0 = radius
        r1 = radius_end if radius_end else radius
        # step around the arc in small angle increments
        n = max(8, int((total * max(r0, r1)) / step))
        dth = total / n
        x, y = pts[-1]
        for k in range(n):
            frac = k / n
            r = r0 + (r1 - r0) * frac
            ds = r * dth
            heading += sign * dth
            x += ds * np.cos(heading)
            y += ds * np.sin(heading)
            pts.append((x, y))

    truth = []
    straight(200)
    truth.append("right 4  (R=90m, 60 deg)")
    arc(90, 60, "R")
    straight(40)  # short gap -> should link
    truth.append("  into left 2  (R=30m, 90 deg, linked)")
    arc(30, 90, "L")
    straight(150)
    truth.append("right 3 tightens  (R 120->50m, 100 deg)")
    arc(120, 100, "R", radius_end=50)
    straight(150)
    truth.append("caution blind crest  (on straight)")
    crest_a = None  # filled below by arc-length position
    straight(150)
    truth.append("hairpin left  (R=12m, 170 deg)")
    arc(12, 170, "L")
    straight(80)
    truth.append("right 3 long  (R=60m, 140 deg, arc ~147m)")
    arc(60, 140, "R")
    straight(120)
    truth.append("left 4 over crest, don't cut  (R=80m, 70 deg, crest at apex)")
    arc(80, 70, "L")
    straight(250)

    xy = np.array(pts)
    x, y = xy[:, 0], xy[:, 1]
    d = np.hypot(np.diff(x), np.diff(y))
    s = np.concatenate([[0.0], np.cumsum(d)])
    road_len = s[-1]

    # Elevation: gentle 3% climb + gaussian crest bumps.
    # Crest 1: middle of the 300m straight after the tightening corner.
    # Crest 2: apex of the final left 4.
    # Locate those arc positions from construction order:
    # lengths: 200 + arc(90,60)=94 + 40 + arc(30,90)=47 + 150 + arc(120->50,100)=148
    #        = 679 -> straight 300 runs 679..979, crest at ~829
    # then 150.. wait: two straights of 150 with crest between them = same thing.
    # hairpin arc(12,170)=36 -> 979+36=1015, +80=1095, arc(60,140)=147 -> 1242,
    # +120=1362, arc(80,70)=98, apex at ~1362+49=1411
    crest_positions = [829.0, 1411.0]
    z = 0.03 * s  # base climb
    for cp, height, width in [(crest_positions[0], 6.0, 45.0),
                              (crest_positions[1], 5.0, 40.0)]:
        z = z + height * np.exp(-((s - cp) ** 2) / (2 * width ** 2))
    # flatten the climb after each crest so the far side actually descends
    z = z - 0.015 * np.maximum(0, s - crest_positions[0])

    return x, y, z, truth, road_len

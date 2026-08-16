"""Road furniture worth calling: bridges, tunnels, speed bumps.

Separate from corners.py because none of this is derived from curvature — it
comes straight from OSM tags and needs no estimation, so it carries none of the
severity-bias risk the geometry pipeline does. What it does carry is a placement
risk: a bump called late is a bump you hit.

Why each one earns a callout on two wheels:

  bridge  — expansion joints and a different surface, and bridges ice before
            the road either side of them does
  tunnel  — the visor and the eyes both need a moment; entering one mid-corner
            at pace is a genuine hazard
  bump    — the one that physically hurts if it arrives unannounced

All three survive every verbosity mode — they are facts from the map rather than
estimates, and they are rare enough not to bury the corner calls (4 bridges on
30 km of CA-84). Tunnels and bumps are additionally marked as warnings, so the
scheduler will move them rather than drop them when the stream is crowded.
"""
import numpy as np

# Minimum length before a bridge is worth mentioning. Below this it is a culvert
# and calling it is noise that costs the rider trust in the whole channel.
#
# 10 m keeps all four of CA-84's creek bridges (14, 46, 14, 37 m) — one per
# 7.5 km, nowhere near a flood — and a 14 m bridge still has an expansion joint
# at each end, which is what matters on two wheels in the wet.
MIN_BRIDGE_M = 10.0

# Merge structures closer than this into one callout rather than saying
# "bridge ... bridge" across a short gap between two mapped spans.
MERGE_GAP_M = 40.0

SPOKEN = {
    "bridge": "bridge",
    "tunnel": "tunnel",
    "bump": "bump",
}
# Tunnels and bumps must survive every verbosity mode.
WARNING_TYPES = {"tunnel", "bump"}


def structure_spans(structure, node_s):
    """Contiguous runs of bridge/tunnel tagging, as (type, start_s, end_s)."""
    spans = []
    if structure is None:
        return spans
    i, n = 0, len(structure)
    while i < n:
        kind = structure[i]
        if not kind:
            i += 1
            continue
        j = i
        while j + 1 < n and structure[j + 1] == kind:
            j += 1
        spans.append([kind, float(node_s[i]), float(node_s[min(j, n - 1)])])
        i = j + 1

    merged = []
    for sp in spans:
        if merged and merged[-1][0] == sp[0] and sp[1] - merged[-1][2] < MERGE_GAP_M:
            merged[-1][2] = sp[2]
        else:
            merged.append(sp)

    return [tuple(sp) for sp in merged
            # a tunnel of any length matters; a short "bridge" is a culvert
            if sp[0] == "tunnel" or (sp[2] - sp[1]) >= MIN_BRIDGE_M]


def road_features(road, node_s):
    """Positioned features from a fetched road.

    Returns a list of dicts: {s, type, text, warn}. Positions are arc length
    along the same grid the corner callouts use, so they schedule together.
    """
    out = []
    for kind, s0, s1 in structure_spans(road.get("structure"), node_s):
        out.append({"s": s0, "type": kind, "text": SPOKEN[kind],
                    "warn": kind in WARNING_TYPES})

    for p in road.get("points") or []:
        i = int(p["i"])
        if 0 <= i < len(node_s):
            t = p["type"]
            out.append({"s": float(node_s[i]), "type": t,
                        "text": SPOKEN.get(t, t), "warn": t in WARNING_TYPES})

    out.sort(key=lambda f: f["s"])
    return out


def node_arc_length(x, y):
    """Arc length at each RAW node, for placing features before resampling."""
    d = np.hypot(np.diff(x), np.diff(y))
    return np.concatenate([[0.0], np.cumsum(d)])

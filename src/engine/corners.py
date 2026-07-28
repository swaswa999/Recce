"""Corner segmentation, rally-scale severity, modifiers, crest detection."""
import numpy as np
from dataclasses import dataclass, field

# Radius (m) -> severity. Rally convention: 6 = fastest, 1 = slowest, plus hairpin.
# Tuned for road riding; these thresholds are THE tuning knobs.
SEVERITY_BANDS = [
    (15, "hairpin"),
    (25, 1),
    (40, 2),
    (70, 3),
    (110, 4),
    (180, 5),
    (300, 6),
]
STRAIGHT_RADIUS = 300.0   # radius above this = not a corner
MIN_CORNER_LEN = 12.0     # meters of sustained curvature to count
MERGE_GAP = 10.0          # merge same-direction segments closer than this
LINK_GAP = 60.0           # corners closer than this get "into" linking
LONG_CORNER = 130.0       # arc length for "long" modifier
TIGHTEN_RATIO = 0.72      # last-third radius < ratio * first-third => tightens
CREST_GRADE_DELTA = 0.05  # grade change across a local max to call a crest
CREST_WIN = 30.0          # meters each side of candidate crest


@dataclass
class Corner:
    i0: int
    i1: int
    s0: float
    s1: float
    direction: str          # 'L' or 'R'
    min_radius: float
    severity: object        # int 1-6 or 'hairpin'
    modifiers: list = field(default_factory=list)
    linked_to_next: bool = False

    @property
    def length(self):
        return self.s1 - self.s0


def severity_of(radius):
    for thresh, sev in SEVERITY_BANDS:
        if radius < thresh:
            return sev
    return None


def find_corners(s, r_smooth):
    """Segment the road into corners where |radius| stays below STRAIGHT_RADIUS."""
    in_corner = np.abs(r_smooth) < STRAIGHT_RADIUS
    corners = []
    i = 0
    n = len(s)
    while i < n:
        if not in_corner[i]:
            i += 1
            continue
        j = i
        while j < n and in_corner[j]:
            j += 1
        seg_r = r_smooth[i:j]
        # dominant direction by summed curvature
        direction = "L" if np.sum(1.0 / seg_r) > 0 else "R"
        corners.append((i, j, direction))
        i = j
    # merge close same-direction segments
    merged = []
    for c in corners:
        if merged:
            pi, pj, pd = merged[-1]
            if pd == c[2] and s[c[0]] - s[pj - 1] < MERGE_GAP:
                merged[-1] = (pi, c[1], pd)
                continue
        merged.append(c)
    out = []
    for i0, i1, d in merged:
        if s[i1 - 1] - s[i0] < MIN_CORNER_LEN:
            continue
        seg = np.abs(r_smooth[i0:i1])
        min_r = float(np.min(seg))
        sev = severity_of(min_r)
        if sev is None:
            continue
        out.append(
            Corner(i0=i0, i1=i1, s0=float(s[i0]), s1=float(s[i1 - 1]),
                   direction=d, min_radius=min_r, severity=sev)
        )
    return out


def add_shape_modifiers(corners, s, r_smooth):
    """tightens / opens / long, based on radius profile through the corner."""
    for c in corners:
        seg = np.abs(r_smooth[c.i0:c.i1])
        third = max(1, len(seg) // 3)
        r_in = np.min(seg[:third])
        r_out = np.min(seg[-third:])
        if r_out < TIGHTEN_RATIO * r_in:
            c.modifiers.append("tightens")
        elif r_in < TIGHTEN_RATIO * r_out:
            c.modifiers.append("opens")
        if c.length > LONG_CORNER:
            c.modifiers.append("long")
    return corners


def find_crests(s, z):
    """Return arc-length positions of blind crests (sharp local elevation maxima)."""
    if z is None:
        return []
    crests = []
    n = len(s)
    spacing = s[1] - s[0] if n > 1 else 5.0
    w = max(2, int(CREST_WIN / spacing))
    grade = np.gradient(z, s)
    for i in range(w, n - w):
        if z[i] >= np.max(z[i - w : i + w + 1]) - 1e-9:
            g_before = np.mean(grade[i - w : i])
            g_after = np.mean(grade[i : i + w])
            if g_before - g_after > CREST_GRADE_DELTA and g_before > 0.015:
                if not crests or s[i] - crests[-1] > 2 * CREST_WIN:
                    crests.append(float(s[i]))
    return crests


def attach_crests(corners, crests):
    """Mark corners containing/near a crest; return crests on straights."""
    loose = []
    for cs in crests:
        hit = False
        for c in corners:
            if c.s0 - 20 <= cs <= c.s1 + 20:
                if "over crest" not in c.modifiers:
                    c.modifiers.append("over crest")
                    # blind apex heuristic: crest inside a real corner => don't cut
                    if c.severity == "hairpin" or (isinstance(c.severity, int) and c.severity <= 4):
                        c.modifiers.append("don't cut")
                hit = True
                break
        if not hit:
            loose.append(cs)
    return loose


def link_corners(corners):
    for a, b in zip(corners, corners[1:]):
        if b.s0 - a.s1 < LINK_GAP:
            a.linked_to_next = True
    return corners

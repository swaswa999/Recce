"""Corner segmentation, rally-scale severity, modifiers, crest detection."""
import numpy as np
from dataclasses import dataclass, field

from geometry import confined_arc_profile, max_safe_spacing

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
# Metres trimmed from each end of a refined profile before comparing shape.
# Matches confined_arc_profile's min_half: those windows are one-sided and
# systematically biased. See add_shape_modifiers.
EDGE_MARGIN_M = 10.0


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
    profile: object = None   # refined radius samples, set by refine_corners()
    refined: bool = False    # False means we fell back to the coarse estimate
    edge_margin: int = 0     # samples per end whose fit window is one-sided
    node_gap: float = 0.0    # median RAW node spacing across this corner
    shape_trusted: bool = True   # False: too sparse to call tightens/opens

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


def refine_corners(corners, s_seg, s_fine, x_fine, y_fine, spacing_fine,
                   seed_fine):
    """Re-measure each corner's radius on the fine grid, confined to the corner.

    Segmentation on the coarse grid decides WHERE corners are; this decides how
    tight they are. Splitting the two is deliberate: one estimator doing both
    jobs either flattens tight corners (wide window) or fragments the road into
    phantom corners with false modifiers (short window). Corner boundaries are
    untouched here, so this can only change severity, never corner count.

    Attaches `profile` (radius samples through the corner) for the modifier
    pass, and re-derives min_radius and severity from it.

    Sets `refined` so a silent fallback to the coarse (flattening) estimate is
    observable rather than invisible, and `edge_margin` — the number of samples
    at each end whose window is one-sided and therefore biased. See
    add_shape_modifiers.
    """
    margin = max(1, int(round(EDGE_MARGIN_M / spacing_fine)))
    for c in corners:
        lo = int(np.searchsorted(s_fine, s_seg[c.i0], side="left"))
        hi = int(np.searchsorted(s_fine, s_seg[c.i1 - 1], side="right"))
        prof = confined_arc_profile(x_fine, y_fine, spacing_fine, seed_fine,
                                    lo, hi)
        prof = prof[np.isfinite(prof)]
        if len(prof) == 0:
            continue
        min_r = float(np.min(prof))
        sev = severity_of(min_r)
        if sev is None:
            # measured flatter than the corner threshold; keep the coarse
            # result rather than silently dropping a corner
            continue
        c.profile = prof
        c.edge_margin = margin
        c.refined = True
        c.min_radius = min_r
        c.severity = sev
    return corners


def mark_shape_trust(corners, node_s):
    """Decide per corner whether the mapping is dense enough to call its SHAPE.

    Gating whole roads on one median cannot tell a 15 m hairpin from a 100 m
    sweeper, and 20 m spacing is fatal for the first and ample for the second.
    Statewide that refused Angeles Crest (103 km, mapped at 17.4 m) entirely
    while its long-radius corners were perfectly measurable.

    Degrade rather than silence. Measurement shows the modifiers break well
    before the radius does, so a sparse corner keeps its direction and severity
    — "right 3" — and loses only "tightens"/"opens". Those are the callouts that
    turn dangerous when wrong; a corner the rider is told about but not fully
    described is still far better than silence.
    """
    node_s = np.asarray(node_s, dtype=float)
    for c in corners:
        inside = node_s[(node_s >= c.s0) & (node_s <= c.s1)]
        if len(inside) < 2:
            c.node_gap = float(c.length)
        else:
            c.node_gap = float(np.median(np.diff(inside)))
        c.shape_trusted = c.node_gap <= max_safe_spacing(c.min_radius)
    return corners


def add_shape_modifiers(corners, s, r_smooth):
    """tightens / opens / long, based on radius profile through the corner.

    Uses the refined confined profile when refine_corners() has run, since the
    coarse profile is flattened at the corner ends by boundary bleed and can
    invert the tightens/opens comparison.

    The profile ENDS are discarded before comparing. Confinement stops the fit
    window leaving the corner, but that makes the outermost windows one-sided:
    at the entry a window can only look forward into tighter geometry (reads low)
    and at the exit only backward into flatter geometry (reads high). That biases
    r_in down and r_out up — against emitting "tightens", and far enough to
    invert into a false "opens" on a constant-radius corner. Measured: a
    constant-radius 30 m arc reported "opens" at 12-13 m node spacing, and at
    13 m the real hairpin reported "hairpin, opens" — the most dangerous string
    this engine can produce.
    """
    for c in corners:
        # `long` depends only on arc length, not the profile, so compute it here
        # where no profile-shape guard can skip it — but append it LAST so the
        # urgent shape word comes first: "right 3 tightens long", not
        # "right 3 long tightens".
        is_long = c.length > LONG_CORNER

        seg = c.profile if c.profile is not None else np.abs(r_smooth[c.i0:c.i1])
        margin = c.edge_margin if c.profile is not None else 0
        if margin and len(seg) > 2 * margin + 6:
            seg = seg[margin:-margin]
        if len(seg) >= 6 and c.shape_trusted:
            third = max(2, len(seg) // 3)
            r_in = np.min(seg[:third])
            r_out = np.min(seg[-third:])
            if r_out < TIGHTEN_RATIO * r_in:
                c.modifiers.append("tightens")
            elif r_in < TIGHTEN_RATIO * r_out:
                c.modifiers.append("opens")
        if is_long:
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

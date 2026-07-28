"""The canonical pacenote pipeline.

One definition, used by run_demo.py, run_real.py and the test suite, so they
cannot drift apart — the tests validating a different pipeline than the demo
prints would make both meaningless.

Two-scale by design: segmentation on a coarse, stable curvature estimate decides
WHERE corners are; a short window confined inside each found corner decides how
TIGHT it is. See docs/ARCHITECTURE.md, "Two-scale curvature estimation".
"""
import numpy as np

from geometry import (resample, signed_radius, smooth_radius,
                      SEG_SPACING, FINE_SPACING)
from corners import (find_corners, refine_corners, add_shape_modifiers,
                     find_crests, attach_crests, link_corners)
from script_gen import build_script


def analyze(x, y, z=None, seg_spacing=SEG_SPACING, fine_spacing=FINE_SPACING):
    """Geometry in, corners + crests out.

    Returns (s, corners, loose_crests) where s is the coarse arc-length grid.
    """
    s, xi, yi, zi = resample(x, y, z, spacing=seg_spacing)
    r_seg = smooth_radius(signed_radius(xi, yi, window=3), k=5)

    corners = find_corners(s, r_seg)

    sf, xf, yf, _ = resample(x, y, None, spacing=fine_spacing)
    seed_w = max(1, int(round(10.0 / fine_spacing)))
    seed_f = np.abs(signed_radius(xf, yf, window=seed_w))
    corners = refine_corners(corners, s, sf, xf, yf, fine_spacing, seed_f)

    corners = add_shape_modifiers(corners, s, r_seg)
    crests = find_crests(s, zi)
    loose = attach_crests(corners, crests)
    corners = link_corners(corners)
    return s, corners, loose


def analyze_to_script(x, y, z=None, **kw):
    """analyze() plus the printable callout script."""
    s, corners, loose = analyze(x, y, z, **kw)
    events, script = build_script(corners, loose, s[-1])
    return s, corners, loose, events, script

# Pacenote Engine — Phase 0 prototype

Turns road geometry into rally-style pacenotes: corner direction, severity
1–6 + hairpin, modifiers (tightens / opens / long / over crest / don't cut),
corner linking ("into"), distance calls, and blind-crest warnings.

## Files

- `geometry.py` — resample road to even 5 m spacing, signed circumradius
  (Menger curvature via circumscribed circle), rolling-median smoothing
- `corners.py` — corner segmentation, severity bands, modifiers, crest
  detection from the elevation profile
- `script_gen.py` — turns corners into a callout script with linking and
  co-driver-style distance rounding
- `synth_road.py` — synthetic canyon road with a known answer key
- `run_demo.py` — validation run: ground truth vs engine output
- `fetch_osm.py` — pull a real road from OpenStreetMap + elevation
  (run on your own machine; needs open internet)
- `run_real.py` — run the engine on a fetched road

## Quick start

```
pip install numpy
python run_demo.py                 # synthetic validation
python fetch_osm.py "Tail of the Dragon" 35.44,-84.00,35.56,-83.88 --ref "US 129"
python run_real.py road.json       # real road
```

## Validation result (synthetic road)

All 7 designed features recovered: right 4; linked "into left 2";
decreasing-radius "right 3 tightens"; standalone blind crest (detected at
835 m vs designed 829 m); hairpin left (12.5 m vs designed 12 m radius);
"right 3 long"; and "left 4 over crest, don't cut".

Known limitation: on the compound (tightening) corner the smoothed minimum
radius reads ~64 m vs the designed 50 m — rolling-median smoothing
underestimates rapidly changing curvature. Severity was still correct, but
on real roads this means borderline corners can rate one band optimistic.
Fix candidates: smaller smoothing window at high curvature, or fit arcs
per-segment instead of pointwise radius.

## Tuning knobs (all in corners.py)

- `SEVERITY_BANDS` — the radius→severity mapping. THE thing to tune on a
  road you know.
- `LINK_GAP` (60 m) — how close corners must be for "into" linking
- `LONG_CORNER` (130 m) — arc length for the "long" modifier
- `TIGHTEN_RATIO` (0.72) — sensitivity of tightens/opens
- `CREST_GRADE_DELTA` (5%) — how sharp an elevation break counts as blind

## What Phase 0 does NOT do yet

- Sightline analysis (true blind-apex detection needs terrain beside the
  road, not just the profile along it)
- Speed-aware callout timing (that's playback / Phase 2 — these are
  position-anchored events, the phone converts to seconds-ahead)
- OSM data quality checks (low node density on some roads will
  under-detect corners — flag roads where median node spacing > 15 m)

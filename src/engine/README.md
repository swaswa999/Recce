# Pacenote Engine

Turns road geometry into rally-style pacenotes: corner direction, severity 1–6 plus
hairpin, modifiers (tightens / opens / long / over crest / don't cut), corner linking
("into"), distance calls, blind-crest warnings — then schedules them in time and
renders speakable audio.

Requires numpy only (plus macOS `say` for audio).

## Modules

**Geometry and corners**

- `geometry.py` — resampling, signed circumradius, least-squares circle fitting,
  `confined_arc_profile()` for measurement, node-spacing stats
- `corners.py` — segmentation, severity bands, shape modifiers, crest detection,
  `refine_corners()`
- `script_gen.py` — corners into a callout script with linking and co-driver-style
  distance rounding
- `pipeline.py` — **the single entry point.** `analyze()` / `analyze_to_script()`

**Ride simulation and output**

- `speed.py` — physics speed profile (lateral grip, then braking/drive limits) and
  GPS-derived lean angle
- `timing.py` — seconds-ahead scheduling, verbosity modes, callout priority
- `make_audio.py` — renders a ride to a timed WAV via macOS `say`

**Test roads and runners**

- `synth_road.py` — the original answer-key canyon road
- `synth_stress.py` — spiral road with sustained minima and a genuinely opening
  corner
- `run_demo.py` — answer-key validation: ground truth vs engine output
- `fetch_osm.py` — pull a real road from Overpass plus elevation (needs open
  internet)
- `run_real.py` — run the engine on a fetched road, with the density gate

## Quick start

```
pip install numpy pytest
python3 run_demo.py                      # answer-key road
python3 synth_stress.py                  # spiral stress road
python3 make_audio.py --no-audio         # callout schedule
python3 make_audio.py -o ~/ride.wav      # listenable track
python3 make_audio.py --mode guardian    # minimal verbosity
python3 -m pytest                        # from the repo root
```

Real roads:

```
python3 fetch_osm.py "Tail of the Dragon" 35.44,-84.00,35.56,-83.88 --ref "US 129"
python3 run_real.py road.json
```

`run_real.py` **refuses** roads above a 12 m median node spacing — their severity and
shape modifiers are not trustworthy. `--force` overrides for diagnosis only.

## Two-scale estimation

Segmentation runs on a coarse 5 m grid (wide, stable — decides *where* corners are).
Measurement runs on a 2 m grid with a short arc-fit window confined inside each found
corner (decides *how tight* it is). One estimator cannot do both: wide windows flatten
tight corners, short windows fragment roads into phantom corners.

Full rationale, measured numbers, and the list of approaches already tried and
rejected: `docs/ARCHITECTURE.md`.

## Tuning knobs

Severity and shape, in `corners.py`:

| Knob | Default | Controls |
| --- | --- | --- |
| `SEVERITY_BANDS` | see source | radius → severity. **The** thing to tune on a road you know |
| `STRAIGHT_RADIUS` | 300 m | above this, not a corner |
| `MIN_CORNER_LEN` | 12 m | sustained curvature needed to count |
| `LINK_GAP` | 60 m | how close corners must be to link with "into" |
| `LONG_CORNER` | 130 m | arc length for "long" |
| `TIGHTEN_RATIO` | 0.72 | sensitivity of tightens/opens |
| `CREST_GRADE_DELTA` | 0.05 | elevation break sharp enough to call blind |
| `EDGE_MARGIN_M` | 10 m | profile ends discarded before shape comparison |

Grids in `geometry.py` (`SEG_SPACING`, `FINE_SPACING`); fit window in
`confined_arc_profile` (`frac`, `min_half`, `max_half`).

Ride model in `speed.py` (`A_LAT`, `A_BRAKE`, `A_DRIVE`, `V_MAX`); callouts in
`timing.py` (`LEAD_SECONDS`, `PRIORITY`).

**Any change to severity or geometry math must clear the `severity-bias-reviewer`
agent.** A BLOCKING verdict stops the change.

## Not implemented yet

- **Sightline analysis.** True blind-apex detection needs terrain *beside* the road,
  not just the elevation profile along it. Current "don't cut" is a heuristic: a crest
  inside a corner of severity ≤ 4.
- **Full OSM data-quality gate.** `run_real.py` checks node density only. Elevation
  coverage and geometry gaps are Phase C (`osm-data-quality-checker`).
- **Real GPS traces.** Timing is validated against a modelled speed profile.
- **IMU lean angle.** v1 is GPS-derived; sensor fusion needs mount calibration.

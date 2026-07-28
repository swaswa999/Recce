# Architecture

## Current state

The Phase 0 pacenote engine lives in `src/engine/` (numpy only), with its answer
key encoded as a pytest suite in `tests/`.

## Stack

| Layer | Choice | Status |
| --- | --- | --- |
| Pacenote engine | Python + numpy (offline preprocessing) | In repo, under test |
| Mobile app | Native iOS, Swift | Not started |
| Map data | OpenStreetMap via Overpass | Fetch script written, not yet run |
| Elevation | SRTM | Used for crest detection |
| Backend | Deferred to Phase 5 | Not started |

## The pacenote pipeline

This is the core of the product. Input is road geometry; output is a spoken callout
script.

```
OSM / GPX geometry
  → resample to 5 m spacing
  → signed circumradius (Menger curvature)
  → rolling-median smoothing
  → corner segmentation
  → severity bands (1–6)
  → modifiers (tightens / opens / long / over crest / don't cut)
  → SRTM crest detection
  → corner linking ("right 4 into left 2")
  → callout script
```

At ride time the app matches GPS position against the precomputed script and speaks
each callout a fixed **time** ahead (4–6 s), computed from current speed — not a
fixed distance.

### Known limitation

Rolling-median smoothing **under-reads rapidly tightening corners**: the validation
road measured 64 m minimum radius where 50 m was designed. This makes borderline
corners rate one band *optimistic* — the wrong direction for a safety tool, and
directly connected to the liability risk in [PRODUCT.md](PRODUCT.md).

First fix: **per-segment arc fitting** instead of pointwise radius.

### Validation (Phase 0, July 2026)

Validated against a synthetic canyon road with a designed answer key. **7/7 features
recovered:**

- right 4
- linked "into left 2"
- decreasing-radius "right 3 tightens"
- standalone blind crest (835 m detected vs 829 m designed)
- hairpin left (12.5 m vs 12 m designed radius)
- "right 3 long"
- "left 4 over crest, don't cut"

## Key decisions

| Decision | Why | Alternatives considered |
| --- | --- | --- |
| **Native iOS (Swift) first** | Best IMU access, audio routing, background reliability. Can piggyback Apple's built-in crash detection API (iPhone 14+). Riders skew iPhone in Western markets. | Android first, React Native / Flutter |
| **Route-first navigation** | Rider downloads a road's pacenote pack; works offline. Canyon roads and cell dead zones go together. | On-the-fly analysis ahead of GPS position — works anywhere but heavier compute, and you need offline tiles regardless. A quieter free-roam "follow me" mode comes later. |
| **Lean angle v1 is GPS-derived** | `tan(θ) = v² / (g·r)` — free from the geometry pipeline, no calibration step. | IMU sensor fusion (gyro + accel + GPS heading). Deferred to v2: needs mount-angle calibration, and cornering forces corrupt pure accelerometer readings. |
| **Police reports framed as neutral "police reports"** | Waze precedent. Region-gated off in Germany, France, Switzerland. | Omitting the feature entirely; explicit "cop warning" framing (worse legally) |
| **No leaderboards or segment timing** | Keeps the product a safety copilot, not a street-racing incentive. Ethics and liability. | Strava-style segments — rejected; this is what got similar apps into legal trouble |
| **Preprocessed pacenote packs** | Accuracy + offline reliability in the hills | Real-time analysis (see route-first row) |

## Prior art worth reusing

- **Curvature** — open-source project that already does curve-radius analysis on OSM
  data. Good reference/starting point for the geometry stage.

## Layout

```
src/engine/          Python pacenote engine
  geometry.py        resample to 5 m, signed circumradius, rolling-median smoothing
  corners.py         segmentation, severity bands, modifiers, crest detection
  script_gen.py      corners → callout script, linking, distance rounding
  synth_road.py      synthetic canyon road with the known answer key
  run_demo.py        validation run: ground truth vs engine output
  fetch_osm.py       pull a real road from Overpass + elevation
  run_real.py        run the engine on a fetched road
  README.md          tuning knobs, quick start
src/ios/             Swift app (not started)
tests/               answer key + optimistic-bias invariants
```

Modules use flat imports, so `run_demo.py` runs from inside `src/engine/`.
`pytest.ini` puts that directory on the path for the test suite.

`fetch_osm.py` hits Overpass and must run on a machine with open internet.

## Tuning knobs

All in `corners.py` — these are what get calibrated against real roads:

| Knob | Default | What it controls |
| --- | --- | --- |
| `SEVERITY_BANDS` | see source | Radius → severity mapping. **The** thing to tune. |
| `STRAIGHT_RADIUS` | 300 m | Above this, not a corner |
| `MIN_CORNER_LEN` | 12 m | Sustained curvature needed to count |
| `LINK_GAP` | 60 m | How close corners must be to get "into" linking |
| `LONG_CORNER` | 130 m | Arc length for the "long" modifier |
| `TIGHTEN_RATIO` | 0.72 | Sensitivity of tightens/opens |
| `CREST_GRADE_DELTA` | 0.05 | Elevation break sharp enough to call blind |

Changing any of these can shift severity optimistic — run
`severity-bias-reviewer` and `synthetic-road-validator` on the change.

## Not in Phase 0

- **Sightline analysis.** True blind-apex detection needs terrain *beside* the
  road, not just the elevation profile along it. Current "don't cut" is a
  heuristic: a crest inside a corner of severity ≤ 4.
- **Speed-aware callout timing.** The engine emits position-anchored events; the
  phone converts to seconds-ahead at ride time (Phase E).
- **OSM data quality checks.** Low node density under-detects corners. Flag roads
  where median node spacing > 15 m — this is the `osm-data-quality-checker`
  agent's job in Phase C.

## Conventions

Python 3.11+, numpy only. Tests live in `tests/`, run with `python3 -m pytest`
from the repo root. No formatter or linter configured yet.

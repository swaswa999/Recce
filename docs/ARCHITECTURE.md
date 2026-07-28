# Architecture

## Current state

The repo is a fresh scaffold. **No application code has been committed yet.**

A Phase 0 pacenote engine was built and validated in Python (see below), but it
exists only as `pacenote-engine.zip` off-machine — it is not in this repo and not
on this laptop. Recovering it (or rebuilding from the pipeline description below)
is the first task in [TASKS.md](TASKS.md).

## Stack

| Layer | Choice | Status |
| --- | --- | --- |
| Pacenote engine | Python (offline preprocessing) | Built, validated, not in repo |
| Mobile app | Native iOS, Swift | Not started |
| Map data | OpenStreetMap via Overpass | Fetch script written |
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

## Planned layout

```
src/
  engine/     Python pacenote engine (geometry, corners, script generation)
  ios/        Swift app
```

The Phase 0 engine's module breakdown, for when it's restored:
`geometry.py`, `corners.py`, `script_gen.py`, `synth_road.py`, `run_demo.py`,
`fetch_osm.py`, `run_real.py`, plus a README documenting all tuning knobs.

Note: `fetch_osm.py` hits Overpass and must run on a machine with open internet.

## Conventions

Not yet established — no code in the repo. Set these when the engine lands:
Python version and formatter, test layout, how tuning knobs are configured.

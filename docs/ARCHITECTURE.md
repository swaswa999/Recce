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
  → resample to 5 m (segmentation grid)
  → signed circumradius (Menger curvature) + rolling-median smoothing
  → corner segmentation                    ── decides WHERE corners are
  → re-measure each corner on a 2 m grid   ── decides HOW TIGHT they are
      with a short arc-fit window confined inside the corner
  → severity bands (1–6)
  → modifiers (tightens / opens / long / over crest / don't cut)
  → SRTM crest detection
  → corner linking ("right 4 into left 2")
  → callout script
```

Entry point is `pipeline.analyze()` / `analyze_to_script()` — the demo, `run_real.py`
and the test suite all call it, so they cannot validate different pipelines.

At ride time the app matches GPS position against the precomputed script and speaks
each callout a fixed **time** ahead (4–6 s), computed from current speed — not a
fixed distance.

## Two-scale curvature estimation

Segmentation and measurement want opposite things, so the pipeline runs two grids
instead of forcing one estimator to do both jobs.

| | Grid | Estimator | Job |
| --- | --- | --- | --- |
| **Segmentation** | `SEG_SPACING` = 5 m | 3-point circumradius, window 3, rolling median k=5 | Decide *where* corners start and end |
| **Measurement** | `FINE_SPACING` = 2 m | `confined_arc_profile()` — short adaptive-window least-squares circle fit | Decide *how tight* a found corner is |

**Why split them.** A wide window is stable but flattens curvature peaks, so it
reads tight corners as flatter than they are — optimistic. A short window measures
peaks accurately but resolves polyline kinks as real curvature, fragmenting roads
into phantom corners with false modifiers. Neither is acceptable alone; each is
correct for exactly one of the two jobs.

**Confinement is the key property.** The measurement window is clamped to the
corner's own extent and can never reach outside it. A symmetric window centred near
a corner's end would otherwise reach into the adjoining straight, average corner
with straight, and report a flatter radius. Confinement also means the measurement
pass *cannot change corner count*: segmentation is untouched, so this stage can only
adjust severity.

Confinement removes the **outward** bleed but substitutes an inward one-sided end
bias, which is *also* optimistic at a corner's tightest end: at the entry the window
can only look forward into tighter geometry (reads low), at the exit only backward
into flatter geometry (reads high). The residual magnitude is unmeasured, and it will
under-read any corner whose minimum sits near its exit — which is the definition of a
decreasing-radius corner, exactly the geometry this product exists to warn about.

That end bias also biases `r_in` low and `r_out` high, working *against* emitting
`tightens` and far enough to invert into a false `opens` on a constant-radius corner.
Mitigated by discarding `EDGE_MARGIN_M` (10 m) from each profile end before the shape
comparison — see `add_shape_modifiers`.

Segmentation is deliberately left bit-identical to the Phase 0 validated
configuration. Do not tune `SEG_SPACING` casually.

### Measured effect

Worst-corner radius error on the answer-key road went from **+26.7% to +13.6%**, and
every other corner to within 0.6% — with the hairpin going from +4.5% *optimistic* to
−0.3%.

On clean geometry decimated to real OSM node spacing, measured over 100 decimation
phases per spacing (10 phases is not enough — it straddles the failure onset and
reads clean):

| node spacing | false `opens` | corner count | `tightens` lost |
| --- | --- | --- | --- |
| 4–14 m | **0/100** | stable 6 | 0/100 |
| 16 m | 3/100 | stable 6 | 0/100 |
| 18 m | 11/100 | stable 6 | 0/100 |
| 20 m | 29/100 | stable 6 | 0/100 |

Before this change the same test showed false `opens` at a 20–50% rate across
4–12 m and corner counts of 6–8. Severity itself held up throughout: **zero
optimistic severity ratings** at every spacing from 4–16 m.

### Approaches that were tried and rejected

Recorded so they are not retried. Each was measured, not reasoned about:

- **Three-way fit, take the tightest** (symmetric plus both one-sided, `min`)
  — collapses every corner: `right_4` read 9.7 m instead of 90 m. "Take the more
  pessimistic estimate" fails when a candidate estimate is degenerate.
- **Break-aware windowing** (stop growing at a curvature jump) — truncates
  mid-corner on clean data (`left_2` 20.9 m vs 30 m) and collapses under noise,
  which manufactures fake breaks everywhere.
- **Stable-seed single pass** (to break the window/output feedback loop) — the
  feedback loop was real but not the cause; no improvement under noise.
- **Savitzky-Golay geometry-domain pre-smoothing** — helps, nowhere near enough.
- **Global short-window arc fitting** (no confinement) — the change that got a
  BLOCKING review: accurate on the dense road, but false `opens` at 20–50% on
  decimated geometry.

## The information limit

Curvature finer than the survey cannot be recovered. Resampling 15 m-spaced nodes
down to 2 m does not add information — it manufactures kinks that a short-window fit
reads as real corners. **Severity bias and data quality are therefore the same
problem**, which is why the Phase C data-quality gate is a safety control and not
housekeeping.

Concretely, on the answer-key road: 4–14 m node spacing is clean; at 16 m the 12 m
hairpin becomes unrepresentable and false `opens` appear on 3/100 decimation phases,
landing on the real hairpin as "hairpin, opens". A corner's radius must be
comfortably larger than the node spacing to be measurable at all.

`run_real.py` **refuses** a road above a 12 m median spacing
(`MAX_TRUSTED_MEDIAN_SPACING`), requiring `--force` to process it for diagnosis. It
refuses rather than warns because a printed warning above a full pacenote script gets
scrolled past, and the output looks equally authoritative either way.

That threshold is **provisional** — measured on one synthetic road, and it needs
Phase C calibration on real OSM geometry before it is trusted as a ship/no-ship gate.

### Remaining known limitation

The tightening corner still measures +13.6%, and **how much of that is the test road
versus the estimator is genuinely unresolved.**

The road is definitely part of it: `synth_road`'s compound arc only reaches its
50.67 m minimum over about 0.85 m of arc (7 of 104 steps sit below R=55), and no
windowed estimator can resolve a radius existing over less than a metre. But the
one-sided end bias described above is an estimator property that also under-reads a
corner's tight exit, and its magnitude has not been separated out.

`synth_stress.py` settles it. Every corner there holds its minimum over a plateau, and
all five read **exactly** — including a sustained decreasing-radius 45 m corner at
45.0 m. So the one-sided end bias is not material on geometry whose minimum has real
arc extent, which is what built roads have. The answer-key error is about the
minimum's arc extent, not the corner's shape.

The gap is pinned as a strict `xfail` in `tests/test_severity_bias.py` rather than
absorbed into a tolerance.

**Caveat on the stress road.** It is *not* a discriminator between estimators: the
pre-Phase-B estimator also reads all five corners exactly, with identical modifiers.
That strengthens the argument above — an estimator whose defect is flattening peaks
still resolves a sustained peak — but it means the stress road cannot be cited as
evidence that the new estimator is better. That evidence is in
`tests/test_decimated_geometry.py`, where the old estimator produced false `opens` on
20–50% of phases and this one produces none.

The stress road is also a road written to test code by the same author, so treat it as
necessary rather than sufficient. Geometry classes neither road covers are listed in
[TASKS.md](TASKS.md).

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

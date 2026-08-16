# Scaling Recce to all of California

## What changed

The original architecture decision was **route-first**: the rider picks a road and
downloads its pacenote pack. That is now overridden. The target is **proximity-based**
— the app works out which road you are on and has the notes ready, the way Google
Maps does, with no route selection.

That is a bigger change than it sounds. Route-first meant "one road loaded, match GPS
along it" — a linear scan over 1856 nodes. Proximity means "any road in California,
decide which one you are on" — a spatial search plus a decision problem at every
junction. **Map-matching moves from a detail to the central piece of engineering.**

## The measurements this rests on

Taken on the two real roads processed so far, not estimated:

| | |
| --- | --- |
| Node density | 62.5 nodes/km (both roads, consistently) |
| Pack size | 1.96 KB/km |
| 3DEP elevation throughput | **4.7 nodes/sec** at 8 concurrent |
| Quality gate | Dragon 9.7 m median (passes) · CA-84 10.7 m median, p90 28 m (**fails p90**) |

Two consequences fall straight out:

- **Data volume is a non-issue.** All CA state highways ≈ 24,000 km ≈ **46 MB**.
  Every public road in the state ≈ 754 MB. This is a hosting detail.
- **Elevation is the wall.** 1.5M nodes for state highways at 4.7/sec is **88 hours**
  of continuous point queries against a public USGS endpoint — which would be
  rate-limited long before it finished. For all public roads it is 60 days.

---

## Blocker 1 — Elevation: point queries → raster tiles ✅ DONE

`src/engine/elevation.py` reads the 3DEP 1/3 arc-second COGs directly: open the tile,
read the one window covering the road, bilinear-interpolate every node locally.

Measured on CA-84's 1856 nodes:

| | rate | 1.5M nodes (CA state highways) | 24.6M nodes (all public roads) |
| --- | --- | --- | --- |
| point API | 4.7/sec | 88 hours | 60 days |
| **raster** | **1426/sec** | **17 minutes** | **4.8 hours** |

**303× faster, and it agrees with the point API to a median of 0.25 m** (p95 1.13 m).
The residual is bilinear versus the API's nearest-post sampling, which is the
direction we want: at ~10 m post spacing on a steep hillside the nearest post can be
several metres out vertically, and a crest is called from a grade change of 0.05 — the
same order as that error.

Bilinear matters for a second reason. `elevation_quality()` rejects data whose values
sit on a coarse grid, and nearest-post sampling *is* a grid. Interpolation keeps real
3DEP data continuous and the crest channel enabled.

`fetch_osm.py` now uses the raster first and keeps the point API as a fallback.
3DEP is US-only, so this does not solve elevation outside the US.

## Blocker 2 — OSM: Overpass → bulk extract

**Now:** one Overpass query per road, by name or ref. It 504s on a 167-way bounding
box, has failed repeatedly in this session, and cannot enumerate anything — every road
must be named by hand.
**Needed:** the Geofabrik California extract (~1.2 GB PBF), parsed locally with
`pyosmium`.

This is what makes "all of California" possible at all: it turns *"fetch the road I
named"* into *"iterate every road in the state and decide which ones qualify."*

**Done when:** the extract yields a list of candidate ways with tags and geometry, and
CA-84 built from it matches CA-84 built from Overpass.

## Blocker 3 — Map-matching among many roads ← the hard one

**Now:** `matchNode()` in `web/recce.template.html` scans one road's nodes, windowed
to ±120 of the last match. That window exists because the Dragon doubles back on
itself and a global nearest-node search jumps to a switchback running the other way a
few metres across the hillside.

**Needed:** at any GPS fix, out of every road in the region, decide which one you are
on — and stay decided.

Three parts:

1. **Spatial index.** A grid hash keyed on rounded lat/lon, mapping cell → segments.
   Turns "search everything" into "search the ~10 segments in this cell and its
   neighbours."
2. **Scoring.** Distance alone is not enough: at an overpass, a switchback, or a
   frontage road beside a highway, the nearest segment is often the wrong one. Score
   on perpendicular distance **and** agreement between GPS heading and segment
   bearing.
3. **Hysteresis.** The failure to design against is *flapping* — switching roads back
   and forth at a junction and re-announcing corners. Require several consecutive fixes
   agreeing before switching, and forget spoken callouts only on a genuine switch.

Do **not** start with a full HMM. Nearest-segment-with-heading plus hysteresis is
likely sufficient for rural roads, which is where the product lives; escalate only if
measurement says so.

**Done when:** replaying a recorded GPS trace across a junction picks the right road
throughout, with zero flapping, and going the wrong way up a road announces nothing.

## Blocker 4 — Tiled packs and offline regions

Proximity loading conflicts directly with the constraint that made the current build
work: **it must survive dead zones**, which is exactly where these roads are.

Resolve it the way offline maps do — proximity *within* a downloaded area:

- Preprocess into tiles (~0.1° ≈ 11 × 9 km). At statewide volume that is a few tens
  of KB per tile.
- The rider downloads a **region** once on wifi ("Bay Area", "Sierra") — a few MB.
- At ride time the app selects tiles by proximity from what it already holds. No
  route picked, no signal needed.

This keeps the "just works" behaviour while never depending on coverage mid-ride.

**Done when:** with the phone in airplane mode after a region download, riding into an
adjacent tile produces callouts with no interaction.

## Blocker 5 — Which roads qualify

Both roads processed so far *barely* pass, and CA-84 already fails the p90 check. If
that is representative, "all California roads" is really "the subset whose OSM geometry
supports pacenotes" — and nobody knows what fraction that is.

**Do this first.** It is cheap once Blocker 2 lands, it needs no new algorithms, and it
decides whether the rest is worth building. Run `node_spacing_stats()` and
`elevation_quality()` over every candidate road in the extract and produce the
distribution.

A road that fails must be **absent**, not silently degraded — a rider who gets no
callouts knows nothing is there, while one who gets bad callouts trusts them.

## Blocker 6 — Severity calibration

`SEVERITY_BANDS` has never been calibrated against a real road by a rider. It is the
one number the docs call *"**the** thing to tune on a road you know"*, and it is
currently a guess.

Statewide distribution multiplies the exposure the docs already identify as the main
business risk. Calibrate on known roads **before** scaling, not after — this is
sequencing, not caution: bands tuned after release cannot un-teach a rider who has
learned to trust a 3 that rides like a 2.

---

## Order

1. **Blocker 5 survey** (needs 2) — decides whether the rest is worth it
2. **Blocker 2**, bulk OSM — unblocks the survey and everything else
3. **Blocker 1**, raster elevation — removes the 88-hour wall
4. **Blocker 3**, map-matching — the central engineering piece
5. **Blocker 4**, tiles and regions
6. **Blocker 6**, calibration — gates release, and can run in parallel throughout

1–3 are mechanical. 4 is the one with real design risk. 6 is the one that decides
whether any of it should ship.

## What stays as it is

The corner engine itself needs no changes. Two-scale curvature estimation, the
optimistic-bias invariants, the data-quality gates, the callout scheduler and the
feature layer all operate per road and are indifferent to how many roads exist. The
scaling work is entirely ingest, storage, and matching.

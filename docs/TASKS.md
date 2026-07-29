# Tasks

Status values: `todo`, `in-progress`, `blocked`, `done`.

Phases come from the roadmap. Phase 0 is complete; Phase 1 is the active phase.

For MVP scope, phase-by-phase acceptance criteria, and which agent handles what,
see [MVP-PLAN.md](MVP-PLAN.md). The roadmap phases below map to plan phases A–F.

## In progress

- **A real DEM.** This is the top item. Crest detection is currently dead on real
  roads: `over crest` and `don't cut` are suppressed entirely because
  Open-Elevation gives integer metres and a 126% p95 gradient. Blind crests
  mid-corner are the highest-consequence hazard this product set out to warn
  about, so a permanently silent crest channel is the biggest functional gap in
  the MVP. Candidates: USGS 3DEP 1 m LIDAR (US roads), Copernicus DEM GLO-30,
  reading SRTM tiles directly with bilinear interpolation, or barometric
  altitude from recorded rides. Needs its own evaluation — do not just swap the
  API and re-enable the channel.

## Todo

1. **Ride the audio track.** `make_audio.py` produces a listenable WAV, but
   "subjectively non-distracting at pace" cannot be tested at a desk. This is
   the real Phase D gate.
2. **Feed a recorded GPS trace into the timing engine.** Timing is currently
   validated against a *modelled* speed profile, not a real ride.
3. **Judge the severity bands on a road I know.** The Tail of the Dragon now
   runs end to end (260 corners over 34.8 km, 7.5/km), but I can't tell whether
   band 3 vs 4 matches how it actually rides. This needs someone who knows a road.
4. **Calibrate the spacing thresholds on more real roads.** 12 m median / 25 m p90,
   measured on one synthetic road and sanity-checked on one real one.
6. **Elevation on the stress road.** `synth_stress.py` deliberately has no
   crests, so crest detection and "don't cut" are still only tested by the
   answer-key road.
7. **Geometry classes neither test road covers.** Both roads are clean, isolated
   corners separated by long straights. Untested: switchbacks with no straight
   between them, corners shorter than the fit window, compound corners that
   tighten *then* open, off-camber/banked sections, junctions and forks, doubling-
   back geometry where the road nearly touches itself, and very long constant
   sweepers. Neither road discriminates the new estimator from the old on radius
   accuracy — only the decimated-geometry tests do that.
8. **Finish the third `severity-bias-reviewer` pass.** Rounds 1 and 2 returned
   BLOCKING and were addressed; round 3 was cut off by an API spend limit before
   giving a verdict. Its one partial finding (the stress road doesn't discriminate)
   was verified and folded in. Phase B has no clean verdict on record.

Later phases:

- **Phase 2 — Minimal iOS app.** Load a pacenote pack, speak GPS-matched callouts
  over Bluetooth, log rides with GPS-derived lean angle.
- **Phase 3 — Ride testing and tuning** with 3–5 rider friends.
- **Phase 4 — Safety layer.** Crash detection with SOS countdown, the three report
  buttons (Police / Hazard / Traffic), telemetry replay UI.
- **Phase 5 — Backend.** Accounts, crowd-sourced hazards with time decay, curvy
  routing (reuses the Phase 0 corner scoring as the road-fun function).
- **Phase 6 — Business hardening.** LLC, insurance, region gating for police
  reports, pricing, App Store launch.

Unscheduled:

- Name clearance for "Recce" — App Store, USPTO, EUIPO, domain. Short name, so
  collisions are likely. Fallback: **Codriver**.

## Blocked

- ~~Real-road validation — blocked on open internet.~~ **Never actually blocked.**
  `fetch_osm.py` claimed the sandbox blocked Overpass; the real cause was a 406
  from posting the query as `text/plain` with urllib's default User-Agent. Fixed.
- The remaining Phase D gates need a bike and a road, not code.

## Done

- **Phase C partial — real road end to end** (2026-07-28). Tail of the Dragon
  fetched from Overpass and run through the engine: 260 corners over 34.8 km.
  Found and fixed two data-fitness defects (elevation unfit for crests; median
  node spacing an insufficient gate) and four callout-layer defects (linked
  corners colliding and being dropped, warnings droppable by collision, the
  elevation gate bypassable by any caller, negative speak times silently
  clipping audio). None were visible to 108 green tests on synthetic roads.
- **Phase D built, not yet ridden** (2026-07-28). `speed.py`, `timing.py`,
  `make_audio.py`. Renders a listenable timed callout track for synthetic or
  real roads.
- **Phase B — two-scale curvature estimation** (2026-07-27). Worst corner
  +26.7% → +13.6%, all others inside 0.6%, false `opens` on decimated geometry
  20–50% → 0. Two BLOCKING reviewer rounds, both legitimate; third round cut
  off by an API spend limit, so no clean verdict is on record.
- **Phase A — Engine in repo, answer key under test** (2026-07-27). Recovered the
  engine from `~/Desktop/pacenotes/` into `src/engine/`, encoded all 7 answer-key
  features as assertions in `tests/`, and added the optimistic-bias invariants.
  22 passed, 1 strict xfail (the Phase B bug).
- **Phase 0 — Pacenote engine (Python, laptop).** Built and validated July 2026.
  7/7 designed features recovered against a synthetic canyon road with an answer
  key. Details in [ARCHITECTURE.md](ARCHITECTURE.md).

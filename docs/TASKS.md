# Tasks

Status values: `todo`, `in-progress`, `blocked`, `done`.

Phases come from the roadmap. Phase 0 is complete; Phase 1 is the active phase.

For MVP scope, phase-by-phase acceptance criteria, and which agent handles what,
see [MVP-PLAN.md](MVP-PLAN.md). The roadmap phases below map to plan phases A–F.

## In progress

- **Phase B — awaiting final `severity-bias-reviewer` verdict.** Two BLOCKING
  rounds so far, both legitimate; see MVP-PLAN.md for what each caught.

## Todo

1. **Ride the audio track.** `make_audio.py` produces a listenable WAV, but
   "subjectively non-distracting at pace" cannot be tested at a desk. This is
   the real Phase D gate.
2. **Feed a recorded GPS trace into the timing engine.** Timing is currently
   validated against a *modelled* speed profile, not a real ride.
3. **Run `fetch_osm.py` + `run_real.py` on a road I know well** and judge whether
   the severity bands match reality. Needs a machine with open internet for the
   Overpass fetch. Note `run_real.py` now refuses roads above 12 m median node
   spacing — expect some real roads to be rejected.
4. **Calibrate `MAX_TRUSTED_MEDIAN_SPACING` on real OSM geometry.** It is 12 m,
   measured on one synthetic road. Provisional until Phase C.
5. **Elevation on the stress road.** `synth_stress.py` deliberately has no
   crests, so crest detection and "don't cut" are still only tested by the
   answer-key road.
6. **Geometry classes neither test road covers.** Both roads are clean, isolated
   corners separated by long straights. Untested: switchbacks with no straight
   between them, corners shorter than the fit window, compound corners that
   tighten *then* open, off-camber/banked sections, junctions and forks, doubling-
   back geometry where the road nearly touches itself, and very long constant
   sweepers. Neither road discriminates the new estimator from the old on radius
   accuracy — only the decimated-geometry tests do that.
7. **Finish the third `severity-bias-reviewer` pass.** Rounds 1 and 2 returned
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

- Real-road validation — blocked on a machine with open internet for the Overpass
  API fetch.
- The two remaining Phase D gates need a bike and a road, not code.

## Done

- **Phase A — Engine in repo, answer key under test** (2026-07-27). Recovered the
  engine from `~/Desktop/pacenotes/` into `src/engine/`, encoded all 7 answer-key
  features as assertions in `tests/`, and added the optimistic-bias invariants.
  22 passed, 1 strict xfail (the Phase B bug).
- **Phase 0 — Pacenote engine (Python, laptop).** Built and validated July 2026.
  7/7 designed features recovered against a synthetic canyon road with an answer
  key. Details in [ARCHITECTURE.md](ARCHITECTURE.md).

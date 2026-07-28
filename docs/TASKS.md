# Tasks

Status values: `todo`, `in-progress`, `blocked`, `done`.

Phases come from the roadmap. Phase 0 is complete; Phase 1 is the active phase.

For MVP scope, phase-by-phase acceptance criteria, and which agent handles what,
see [MVP-PLAN.md](MVP-PLAN.md). The roadmap phases below map to plan phases A–F.

## In progress

- **Phase 1 — Audio validation.** Generate a callout audio track timed to a
  recorded GPS trace, then ride it on a road I know. Tests both callout accuracy
  and rider distraction, cheaply, before any app exists.

## Todo

Immediate (the next three actions):

1. **Recover the Phase 0 engine.** `pacenote-engine.zip` is not in this repo and
   not on this laptop. Find it and commit it to `src/engine/`, or rebuild from the
   pipeline description in [ARCHITECTURE.md](ARCHITECTURE.md).
2. **Run `fetch_osm.py` + `run_real.py` on a road I know well** and judge whether
   the severity bands match reality. Needs a machine with open internet for the
   Overpass fetch.
3. **Fix the tightening-corner underestimate** with per-segment arc fitting.
   Smoothing currently under-reads rapidly tightening corners (64 m measured vs
   50 m designed), rating borderline corners one band optimistic — the wrong
   direction for a safety tool.

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

- Task 2 (real-road validation) — blocked on a machine with open internet for the
  Overpass API fetch.

## Done

- **Phase 0 — Pacenote engine (Python, laptop).** Built and validated July 2026.
  7/7 designed features recovered against a synthetic canyon road with an answer
  key. One known limitation carried forward as todo #3. Details in
  [ARCHITECTURE.md](ARCHITECTURE.md).

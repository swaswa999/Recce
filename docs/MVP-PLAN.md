# MVP Plan

## What the MVP is

**A rider downloads a pacenote pack for one known road, rides it with helmet comms,
and hears accurate, well-timed corner callouts.**

That's the whole MVP. It exists to answer the one question that decides whether this
product is real: *are the callouts accurate and well-timed enough to be trusted at
speed?* Callout accuracy is the only genuine technical unknown — everything else in
the feature set is proven table stakes that competitors already ship.

### Explicitly not in the MVP

Crash detection, the Police/Hazard/Traffic report buttons, crowd-sourced hazards,
telemetry replay UI, accounts, backend, curvy routing, App Store launch. These are
Phases 4–6 in [TASKS.md](TASKS.md) and stay there. None of them matter if the
callouts are wrong.

## The through-line: severity must never read optimistic

Every phase below carries the same acceptance criterion, because it's the product's
#1 named risk. A corner called easier than it is can contribute to a crash. The
known smoothing bug (64 m measured vs 50 m designed minimum radius) is exactly this
failure mode, and it is not fixed yet.

So: **zero corners may rate easier than ground truth.** Rating a corner *harder*
than it is costs the rider a little confidence. Rating it easier costs more than
that. Where the pipeline is uncertain, it rounds toward the harder band.

---

## Phase A — Restore the engine and put it under test ✅ done

Engine recovered from `~/Desktop/pacenotes/` and committed to `src/engine/`
(all 7 modules). Answer key encoded as `tests/`.

**Acceptance criteria — all met**

- ✅ `python3 -m pytest` runs green from the repo root.
- ✅ All 7 answer-key features asserted by the suite, not by reading demo output.
- ✅ The bias invariant exists and the tightening corner is visible as a **strict
  `xfail`** — the suite stays green while the known bug stays legible in the
  output. `strict=True` means that when arc fitting lands, the test XPASSes and
  pytest turns that into a failure, forcing the marker off and locking the fix in.

**Result:** 22 passed, 1 xfailed.

---

## Phase B — Fix the severity underestimate

Rolling-median smoothing under-reads rapidly tightening corners. Replace pointwise
radius with **per-segment arc fitting**.

**Work**

1. Implement arc fitting in the geometry stage.
2. Re-run the full answer key; check no previously-passing feature regressed.
3. Add a second synthetic road that stresses decreasing-radius corners specifically.

**Acceptance criteria**

- Measured minimum radius on the tightening corner within 10% of designed (50 m),
  versus 64 m today.
- The optimistic-bias invariant passes across both synthetic roads — **zero**
  optimistic ratings.
- No regression on the original 7 features.

**Agents:** planner → builder → synthetic-road-validator → severity-bias-reviewer

This is the phase where `severity-bias-reviewer` is load-bearing. Its verdict is
blocking.

---

## Phase C — Real-road validation

Synthetic roads prove the math. Real OSM data is a different problem: node density
varies, elevation is patchy, and geometry has gaps.

**Work**

1. Run `fetch_osm.py` + `run_real.py` on 2–3 roads I know well. *(Needs a machine
   with open internet for the Overpass fetch — currently blocking.)*
2. Ride or drive them, and judge the severity bands against reality.
3. Build the data-quality gate: node density, elevation coverage, geometry gaps.

**Acceptance criteria**

- On a road I know well, I agree with the severity band on ≥90% of corners.
- **Every disagreement is in the pessimistic direction.** A single optimistic
  miss on real data blocks the phase.
- The quality checker correctly flags a deliberately degraded road as no-ship.

**Agents:** osm-data-quality-checker → severity-bias-reviewer

---

## Phase D — Audio validation (roadmap Phase 1)

The cheapest possible test of the actual product experience: no app required.

**Work**

1. Record a GPS trace of a known road.
2. Generate a callout audio track timed to that trace, using the seconds-ahead
   timing model (4–6 s at current speed).
3. Ride the road with the track playing through helmet comms.

**Acceptance criteria**

- Callouts land 4–6 s ahead of corner entry; **no callout arrives late.**
- Linked corners ("right 4 into left 2") land as one useful call, not two
  confusing ones.
- Subjectively non-distracting at pace — this is a real gate, not a nice-to-have.
  Too much chatter fails the phase.

**Agents:** planner → builder → tester

This phase is where the product either feels right or doesn't. Be honest about the
result; a bad outcome here is worth more than a forced pass.

---

## Phase E — Minimal iOS app (roadmap Phase 2)

**Work**

1. Load a precomputed pacenote pack.
2. GPS position matching against the pack.
3. Speak callouts over Bluetooth with the priority system.
4. Ride logging with GPS-derived lean angle: `tan(θ) = v² / (g·r)`.
5. Verbosity modes: Full rally / Highlights / Guardian.

**Acceptance criteria**

- Works fully in airplane mode — canyon roads and dead zones go together, so
  offline is a hard requirement, not a fallback.
- Callout timing matches the Phase D offline reference within tolerance.
- Audio survives a backgrounded app and a screen lock for a full ride.

**Agents:** planner → builder → tester → reviewer

---

## Phase F — Ride testing (roadmap Phase 3)

3–5 rider friends, real roads, tuning the severity bands and verbosity against
other people's judgment rather than only mine.

**Acceptance criteria**

- No rider reports a corner that was called easier than it rode.
- Riders choose to keep using it after the test ride.

---

## Phase → agent map

| Phase | Primary agents |
| --- | --- |
| A — Restore engine | planner, builder, tester, synthetic-road-validator |
| B — Fix severity bias | builder, synthetic-road-validator, **severity-bias-reviewer** |
| C — Real-road validation | **osm-data-quality-checker**, severity-bias-reviewer |
| D — Audio validation | planner, builder, tester |
| E — iOS app | planner, builder, tester, reviewer |
| F — Ride testing | — (human) |

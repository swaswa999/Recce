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

Replaced the estimator with **two-scale curvature estimation**: coarse-grid
segmentation (unchanged from Phase 0) decides where corners are; a short arc-fit
window *confined inside* each found corner decides how tight it is. See
[ARCHITECTURE.md](ARCHITECTURE.md), "Two-scale curvature estimation".

**Outcome against the original criteria**

- ⚠️ **Tightening corner within 10% of designed — NOT met.** Improved from +26.7%
  to +13.6%. The criterion turned out to be unachievable on this road by any
  windowed estimator: the designed 50.67 m minimum exists over ~0.85 m of arc. This
  is a limitation of the test road, not the estimator. Pinned as a strict `xfail`
  rather than absorbed into a tolerance.
- ✅ **Zero optimistic ratings.** Every other corner now measures within 0.6%, and
  the hairpin went from +4.5% *optimistic* to −0.3%.
- ✅ **No regression on the original 7 features.**
- ⏳ Second stress road still outstanding — now the blocking item for making the
  10% goal meaningful.

**What the review caught.** `severity-bias-reviewer` returned **BLOCKING** on the
first attempt. Short windows applied globally invented false `opens` modifiers on
20–50% of clean geometry decimated to 4–12 m node spacing, plus phantom corners
including a hairpin on a straight — while 23 tests stayed green, because the suite
only ever saw the 2 m-stepped road. Confinement fixed it: zero false `opens`, stable
6 corners. This is the agent earning its keep; four other approaches were measured
and rejected (listed in ARCHITECTURE.md).

**The lasting lesson:** severity bias and data quality are the *same problem*.
Curvature finer than the survey cannot be recovered, so the Phase C gate is a safety
control, not housekeeping.

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

**Built**

- `speed.py` — physics speed profile (lateral-grip cap, then braking/drive limits),
  plus GPS-derived lean angle. Callout timing is meaningless without it.
- `timing.py` — seconds-ahead scheduling, verbosity modes, priority/pre-emption.
- `make_audio.py` — renders a ride to a single timed WAV via macOS `say`.

```
cd src/engine
python3 make_audio.py --no-audio            # schedule only
python3 make_audio.py -o ~/Desktop/ride.wav # listenable track
python3 make_audio.py --mode guardian
```

On the synthetic road: 1710 m, 32–100 km/h, peak lean 34°, 7 callouts each landing
exactly 3.0 s ahead.

**Acceptance criteria**

- ✅ **No callout arrives late.** Enforced as a test across all three verbosity
  modes. Callouts are scheduled to *finish* before the lead point, not start there —
  a rider committing while still hearing the description has been told too late.
- ✅ Linked corners land as one call ("into left 2"), not two.
- ✅ Verbosity never suppresses a warning: `tightens`, `don't cut`, `over crest`,
  crests and hazards survive every mode. A quieter setting must not be a less safe
  one.
- ⏳ **Subjectively non-distracting at pace** — still needs a real ride. This is the
  actual gate and it cannot be tested at a desk.

**Still to do:** the timing is validated against a *modelled* speed profile, not a
recorded GPS trace. Feeding a real trace in is the remaining Phase D work.

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

# Product

**Recce** — a rally co-driver for public roads. Named for the reconnaissance runs
where rally crews write their pacenotes.

## Problem

Riding a motorcycle fast on unfamiliar mountain roads means guessing what's around
each blind corner. Turn-by-turn navigation tells you *where* to go; it says nothing
about *how hard* the next corner is, whether it tightens, or whether there's a blind
crest at the apex. Decreasing-radius corners and blind crests are what catch riders
out — and no consumer product warns you about them in real time.

Rally crews solved this decades ago with spoken pacenotes. Nobody has brought that
to public roads.

## Users

Primary: motorcycle riders doing spirited weekend rides on canyon/mountain roads,
usually on unfamiliar routes, wearing a Bluetooth helmet comm (Cardo/Sena).

Secondary: spirited car drivers on the same roads. Same callouts, same value.

## What it does

**The copilot (core loop)**

- Corner severity on the rally 1–6 scale, spoken with words: "hairpin left"
- Callouts timed by **seconds ahead at current speed**, not fixed distance — "in
  200 meters" is useless at 40 vs 120 km/h
- Modifiers, which matter more than the corner rating itself: *tightens, opens,
  long, over crest, don't cut*
- Corner linking: "right 4 into left 2" beats two separate callouts
- Blind crest warnings from elevation data — blind crests mid-corner are the
  highest-consequence hazard on these roads

**Safety layer**

- Crash detection → countdown → auto-SOS with GPS coords to an emergency contact.
  The countdown exists so a dropped phone doesn't text your mom.
- Three big glove-friendly report buttons: **Police / Hazard / Traffic**. One tap,
  no typing, auto-tagged with location and direction of travel.
- Crowd-sourced hazards spoken back as pacenotes: "caution, gravel reported,
  right four ahead"

**After the ride**

- Session telemetry and replay: lean angle, speed, braking points on the map

**Design constraints**

- Audio-first. Screen is optional while moving; cognitive load is the enemy.
- Callout priority system: crash/hazard interrupts everything, corner calls beat
  traffic info.
- Adjustable verbosity: **Full rally / Highlights / Guardian** modes.
- Fun routing: maximize curves, avoid highways and signals, prefer elevation.

## Non-goals

- **No leaderboards. No segment timing.** This is the load-bearing product decision.
  It keeps Recce a safety copilot rather than a street-racing incentive — both an
  ethics line and a liability one. Everything is framed as *"know what's coming"*,
  never *"beat your time."* The go-fast itch gets scratched in post-ride telemetry
  review, not mid-ride competition.
- Not a track/lap-timing app — that space is served (Harry's LapTimer, RaceChrono).
- Not a general-purpose navigation app.

## Competitive landscape

| Product | What it does | Gap |
| --- | --- | --- |
| Calimoto / Kurviger | Curvy routing, EU-strong (~$60/yr — proves demand) | No pacenotes |
| Rever | US route discovery/sharing (~$70/yr) | No pacenotes |
| Scenic | iOS motorcycle nav | No pacenotes |
| Detecht | Crash detection + insurance partnerships | Nav only, no corner intel |
| Waze | Hazard/police reporting | Zero motorcycle focus |
| Harry's LapTimer / RaceChrono | Track telemetry | No road navigation |

**The gap: nobody does spoken rally pacenotes on public roads.** That is the
differentiator. Everything else in the feature set is proven table stakes.

## Business

- Passionate niche that pays for subscriptions. Realistic pricing ~$5–8/mo or
  ~$60/yr, **annual-first** because of winter churn.
- Sustainable lifestyle business ($100K–1M ARR), not venture-scale. Calimoto has
  ~2M registered users after years as category leader — that's the ceiling shape.
- **Biggest risk is liability.** A wrong callout — "opens" when the corner actually
  tightens — could contribute to a crash. Mitigations: excellent map data,
  disclaimers, LLC, insurance. OSM quality varies by region.
- Callout accuracy is the only real technical unknown. It gets validated first
  (see Phase 0/1 in [TASKS.md](TASKS.md)).

## Open questions

- Name is not locked. **Recce** was chosen for brand character (rally credibility,
  sounds good spoken: *"ready for your recce?"*). Runner-up was **Codriver** for
  clarity. Still needs App Store / USPTO / EUIPO / domain checks — "Recce" is short
  enough that collisions are likely.
- How far the car-driving audience gets served explicitly vs. incidentally.
- Which regions ship at launch, given OSM quality variance and police-report gating.

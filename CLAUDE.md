# Recce

A rally co-driver for public roads. Recce speaks pacenotes to motorcycle riders
(and spirited drivers) on mountain roads — how far the next corner is, which way it
goes, how hard it is, and whether it tightens or hides a blind crest. Named for the
reconnaissance runs where rally crews write their notes.

## Orientation

- Product context, feature set, competitive gap: [docs/PRODUCT.md](docs/PRODUCT.md)
- Pacenote pipeline, stack, key decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **MVP scope, phases, acceptance criteria: [docs/MVP-PLAN.md](docs/MVP-PLAN.md)**
- Roadmap and active work: [docs/TASKS.md](docs/TASKS.md)

## Current state

Fresh scaffold — **no application code committed yet.** A Phase 0 pacenote engine
was built and validated in Python, but it lives in an off-machine
`pacenote-engine.zip`. Recovering it is task #1 in TASKS.md.

Active phase: **Phase 1 — audio validation** (callout track timed to a recorded GPS
trace, ridden on a known road).

## Working conventions

Not yet established — the repo has no code. Set these when the engine lands:

- Install: `TODO`
- Run: `TODO`
- Test: `TODO`
- Lint/typecheck: `TODO`

Planned layout: `src/engine/` (Python pacenote engine), `src/ios/` (Swift app).

## Rules

**This is a safety tool, and errors have physical consequences.** Two rules follow
from that, and they outrank normal engineering preferences:

- **Corner severity must never rate optimistic.** A corner called easier than it is
  can contribute to a crash. When smoothing, rounding, or band assignment is
  ambiguous, err toward the harder rating. The known arc-fitting bug in
  ARCHITECTURE.md is exactly this failure mode.
- **No leaderboards, segment times, or competitive framing** anywhere in the
  product or its copy. Recce tells you *what's coming*; it never tells you to *beat
  a time*. This is a deliberate ethics and liability line, not a feature backlog
  item.

General:

- Don't add abstractions or error handling for cases that can't happen.
- No comments that restate the code — only ones explaining non-obvious *why*.
- Keep [docs/TASKS.md](docs/TASKS.md) current as work starts and finishes.

## Agent workflow

Role-specific subagents live in `.claude/agents/`. All run on Sonnet.

**Core loop**

- **planner** — read-only; studies the code and writes plans with acceptance
  criteria.
- **builder** — implements one scoped task; must run tests before reporting.
- **tester** — runs tests/demo/lint and reports pass/fail with quoted evidence.
- **reviewer** — read-only; reviews a diff for bugs, security, missing tests, and
  complexity.

Typical flow: plan → build → test → review → ship (`.claude/skills/ship/SKILL.md`).

**Safety specialists** — these enforce the rules above; don't skip them.

- **severity-bias-reviewer** — *must* run on any change to corner severity or
  geometry math. Asks only: does this shift severity optimistic? A BLOCKING
  verdict stops the change.
- **synthetic-road-validator** — *must* run after any geometry/corner pipeline
  change. Re-runs the answer-key road and reports regressions feature by feature.
- **osm-data-quality-checker** — gates route packs on node density, elevation
  coverage, and geometry gaps. Fails closed.

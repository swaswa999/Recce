# Recce — vault index

A rally co-driver for public roads. This note is the entry point when browsing the
repo as an Obsidian vault; `memory/` is a symlink to Claude Code's memory directory,
so agent-written notes and project docs are both visible here.

## Project docs — the current state of things

- [[PRODUCT]] — problem, feature set, competitive gap, business shape
- [[ARCHITECTURE]] — the pacenote pipeline, two-scale estimation, rejected approaches
- [[MVP-PLAN]] — MVP scope, phases A–F, acceptance criteria
- [[TASKS]] — what's next, what's blocked
- [[CLAUDE]] — working conventions and the safety rules agents must follow

## Memory — durable facts and hard-won findings

Start at [[MEMORY]] for the full index. The hub note is
[[recce-project-overview]].

**Constraints that outrank normal engineering preferences**
- [[recce-severity-must-never-read-optimistic]]
- [[recce-no-leaderboards-ever]]
- [[recce-liability-is-the-main-business-risk]]

**Engine findings — read before touching geometry**
- [[recce-two-scale-curvature-estimation]] — how the estimator works and why
- [[recce-arc-fitting-accuracy-vs-robustness-tradeoff]] — four dead ends, measured
- [[recce-stress-road-settles-estimator-vs-road]]
- [[recce-test-only-covers-dense-geometry]] — how a green suite hid a real defect
- [[recce-synth-road-lacks-transition-spirals]]

**Process**
- [[recce-agent-roles]] — the seven subagents; BLOCKING stops a change
- [[user-wants-obsidian-queryable-memory]]

## Try it

```
cd src/engine
python3 run_demo.py                       # answer-key road, truth vs output
python3 synth_stress.py                   # spiral stress road
python3 make_audio.py -o ~/Desktop/x.wav  # listenable callout track
python3 make_audio.py --mode guardian     # minimal verbosity
python3 -m pytest                         # from repo root
```

## Note on the two halves

Docs describe the design as it stands. Memory notes record *why* decisions were made
and which approaches were already measured and rejected — the things that aren't
recoverable from the code. When they disagree, the code is truth and both should be
corrected.

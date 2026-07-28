---
name: ship
description: Use when a change is implemented and ready to ship — runs verification and review, then commits, pushes, and opens a PR. Triggers on "ship this", "/ship", "open a PR for this".
---

# Ship

Takes a completed, working-directory change through to an open PR. Stop and surface to the user at any step that fails rather than pushing through.

## Steps

1. **Verify.** Run the `tester` agent against the current diff. If anything fails, stop and report — do not proceed to review/commit.
2. **Pipeline gate.** If the diff touches geometry, corner severity, smoothing, bands, or modifiers, run **both** `synthetic-road-validator` and `severity-bias-reviewer`. A BLOCKING verdict from the bias reviewer stops the ship — no exceptions, no "ship it and fix forward". If the diff adds or changes a route pack, run `osm-data-quality-checker` and require a SHIP verdict.
3. **Review.** Run the `reviewer` agent against the diff. Surface any findings to the user. For anything above minor/nitpick severity, fix it (or ask the user how they want to handle it) before continuing.
4. **Update docs.** If the change closes or starts work tracked in `docs/TASKS.md` or `docs/MVP-PLAN.md`, update it.
5. **Commit.** Stage only the files relevant to this change (never blanket `git add -A`). Write a commit message that explains *why*, following the repo's existing commit style (`git log` for examples).
6. **Push and open PR.** Push the branch and open a PR with `gh pr create`, including a summary and a test plan checklist.

## Guardrails

- Never force-push.
- Never skip steps 1–3, even under time pressure.
- If there are no changes to ship, say so instead of creating an empty commit/PR.
- Confirm with the user before pushing if the branch is `main`/`master`.

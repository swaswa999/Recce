# Moved

The project instruction file now lives at [`../CLAUDE.md`](../CLAUDE.md).

Claude Code loads `CLAUDE.md` from the **project root**, so that is the only copy
that is guaranteed to apply. While the rules lived here instead, Recce's two
safety rules — never rate a corner optimistic, and no competitive framing — were
not being loaded at all.

Keeping a second copy here would only let the two drift, and the one that drifts
is the one nobody reads.

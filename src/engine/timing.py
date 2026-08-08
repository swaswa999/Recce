"""Turn position-anchored corners into callouts scheduled in TIME.

The engine emits events at positions; this module decides when to speak them.
Three rules matter more than anything else here:

1. Lead time is in SECONDS, converted to a position using the speed profile.
   A fixed distance is useless across the speed range riders actually use.
2. A callout must FINISH before the lead point, not start there. A rider
   committing to a corner while still hearing its description has been told
   too late.
3. Late is dangerous, early is merely annoying. Every trade-off here resolves
   toward early.
"""
from dataclasses import dataclass, replace

from script_gen import corner_phrase
from speed import time_at

# Speak so the call ENDS this many seconds before corner entry. Rally crews
# work a beat or two ahead; 3 s at road pace is roughly 40-70 m of thinking room.
LEAD_SECONDS = 3.0

# Rough speaking rate for scheduling, refined by real clip length when the audio
# renderer measures it. 2.6 words/s is unhurried and intelligible under a helmet.
WORDS_PER_SECOND = 2.6
MIN_CLIP_SECONDS = 0.6
# Conservative rate for the chain-length budget only. Slower than
# WORDS_PER_SECOND so a slow voice cannot push a merged utterance over budget in
# the rendered audio.
CHAIN_WPS = 2.0

# Lower number wins. A hazard interrupts a corner call; a corner call beats
# traffic chatter. Nothing outranks a hazard.
PRIORITY = {"hazard": 0, "crest": 1, "corner": 2, "info": 3}

# Verbosity. Full speaks everything; Guardian speaks only what could hurt you.
MODES = ("full", "highlights", "guardian")

# Words that make a callout a WARNING rather than a description.
#
# A warning is never dropped by verbosity, and the scheduler will move it —
# earlier by preference — rather than drop it on a collision. It CAN still be
# dropped when no legal slot exists at all (one that starts at or after t=0,
# overlaps nothing, keeps road order, and finishes before its own corner). That
# is a genuine capacity limit, and unspoken_warnings() exists to make it loud
# rather than let it pass as a delivered callout.
WARNING_WORDS = ("tightens", "don't cut", "over crest", "blind crest")

# Linked corners are spoken as one call ("right 4 into left 2") rather than two,
# which is both what a co-driver says and what stops the second half colliding
# with the first and being dropped.
#
# The chain is bounded by how long the utterance takes to SAY, not by a corner
# count: a two-corner chain is already up to nine words. A fixed cap of 2 dropped
# 79 of the Tail of the Dragon's 181 linkages, implying a break in the road at a
# median gap of 15 m where there is none — the road described as more broken up,
# and so more recoverable, than it is.
# Measured on the Dragon's 181 linked pairs (budget / cap -> linkages kept, max
# words). The originally shipped cap-of-2 kept 56% at a 10-word maximum, so 4.0/3
# is strictly better on both axes:
#
#     3.0 / 2  ->  52%,  7 words        3.5 / 3  ->  65%,  9 words
#     4.0 / 2  ->  56%, 10 words        4.0 / 3  ->  70%, 10 words   <- chosen
#     5.0 / 4  ->  77%, 13 words
#
# Past this the utterance gets long enough that absorbing it at pace is the
# limit, not the arithmetic. This is a ride-test tuning parameter: if a callout
# feels like too much to take in, lower the budget.
MAX_UTTERANCE_SECONDS = 4.0
MAX_LINK_CHAIN = 3          # hard ceiling so short phrases cannot run away

# Placement bounds for a warning that collides with something else.
#
# Earlier is safe, later is not: a callout finishing after its corner describes
# road the rider is already in, and they will attach it to the NEXT corner. But
# arbitrarily early is its own wrong-corner failure, hence the cap.
MAX_EARLY_LEAD = 8.0
MIN_LEAD = 1.0


@dataclass
class Callout:
    anchor_s: float      # position the callout refers to
    text: str
    kind: str            # 'corner' | 'crest' | 'hazard' | 'info'
    severity: object = None
    speak_at: float = 0.0   # scheduled start time, seconds into the ride
    duration: float = 0.0
    dropped: str = ""    # non-empty if suppressed, with the reason
    lead: float = 0.0    # actual seconds between end of speech and the corner
    short_lead: bool = False  # less lead than we wanted, but still usable
    unwarnable: bool = False  # lead below MIN_LEAD: too late to act on

    @property
    def priority(self):
        return PRIORITY[self.kind]

    @property
    def ends_at(self):
        return self.speak_at + self.duration

    @property
    def is_warning(self):
        """Carries information that could prevent a crash, so it must never be
        silently dropped. True by KIND for hazards and crests — a hazard's text
        ("caution, gravel") contains none of the corner-shape warning words, and
        keying only off text once let a hazard be discarded."""
        return self.kind in ("hazard", "crest") or any(
            w in self.text for w in WARNING_WORDS)


def estimate_duration(text, wps=WORDS_PER_SECOND):
    return max(MIN_CLIP_SECONDS, len(text.split()) / wps)


def _severity_rank(sev):
    """Lower is harder. Hairpin is the hardest thing on the scale."""
    return 0 if sev == "hairpin" else (sev if isinstance(sev, int) else 99)


def keep_for_mode(c, mode):
    """Which callouts survive a verbosity mode.

    Suppression is only ever allowed to remove information about EASY corners.
    Anything carrying a warning modifier, any crest, and any hazard survives
    every mode — a quieter setting must not become a less safe one.
    """
    if mode == "full":
        return True
    if c.kind in ("hazard", "crest"):
        return True
    if c.is_warning:
        return True
    rank = _severity_rank(c.severity)
    if mode == "highlights":
        return rank <= 4
    if mode == "guardian":
        return rank <= 2
    raise ValueError(f"unknown verbosity mode: {mode!r}")


def build_callouts(corners, loose_crests, max_chain=MAX_LINK_CHAIN,
                   max_seconds=MAX_UTTERANCE_SECONDS):
    """Corners and crests into unscheduled callouts, in road order.

    Linked corners are MERGED into one utterance anchored at the first corner:
    "right 4 into left 2". Emitting them as two separate callouts meant the
    second one landed inside the first one's speech, collided, and was dropped —
    on the Tail of the Dragon that silently discarded 12 callouts, 11 of which
    carried a warning modifier. Merging removes the collision structurally
    rather than special-casing it in the scheduler.

    The merged callout takes the HARDEST severity in the chain, so verbosity
    filtering can never drop a group because its first corner happened to be
    easy.
    """
    def phrase_of(group):
        return " into ".join(corner_phrase(c) for c in group)

    out = []
    i = 0
    n = len(corners)
    while i < n:
        group = [corners[i]]
        # Extend while genuinely linked AND still one breath. The chain breaks
        # greedily at the last corner that fits — the remainder becomes its own
        # callout with its own severity, so nothing is lost but the audible
        # "into".
        while (len(group) < max_chain and i + len(group) <= n - 1
               and group[-1].linked_to_next):
            trial = group + [corners[i + len(group)]]
            # Budget against the SLOW voice. estimate_duration's 2.6 words/s is
            # optimistic: the renderer reschedules at measured clip length, and
            # at 2.0 words/s the Dragon's longest utterance ran 5.0 s against a
            # 4.0 s budget — 25% over, in the audio a rider actually hears.
            if estimate_duration(phrase_of(trial), wps=CHAIN_WPS) > max_seconds:
                break
            group = trial
        text = phrase_of(group)
        hardest = min(group, key=lambda c: _severity_rank(c.severity)).severity
        out.append(Callout(anchor_s=group[0].s0, text=text, kind="corner",
                           severity=hardest))
        i += len(group)
    for cs in loose_crests:
        out.append(Callout(anchor_s=cs, text="caution, blind crest",
                           kind="crest"))
    out.sort(key=lambda c: c.anchor_s)
    return out


def schedule(callouts, s_grid, t_grid, mode="full", lead=LEAD_SECONDS,
             duration_fn=estimate_duration):
    """Assign each callout a start time, resolving overlaps by priority.

    Returns (kept, dropped). A callout is only dropped when it would collide
    with something more important — and then the drop reason is recorded rather
    than the callout silently vanishing.

    Pure: the input callouts are never mutated, so scheduling the same list at
    two verbosity levels (or twice with different duration estimates, as the
    audio renderer does) gives independent results. An earlier version wrote
    `speak_at` and `dropped` straight onto the inputs, which let a callout
    dropped on one pass come back marked as both kept and dropped on the next.
    """
    work = [replace(c, speak_at=0.0, duration=0.0, dropped="") for c in callouts]

    live, dropped = [], []
    for c in work:
        if not keep_for_mode(c, mode):
            c.dropped = f"verbosity={mode}"
            dropped.append(c)
            continue
        live.append(c)

    arrive_of = {id(c): time_at(s_grid, t_grid, c.anchor_s) for c in live}
    for c in live:
        c.duration = duration_fn(c.text)
        # ideal: finish `lead` seconds before arrival
        c.speak_at = max(0.0, arrive_of[id(c)] - lead - c.duration)

    live.sort(key=lambda c: (c.speak_at, c.priority))

    GAP = 0.05

    def collides(c, others):
        """Against EVERY other kept callout, not just the first one found.

        The previous version used next(...) — the FIRST overlap — so removing
        one clashing callout and appending could leave the new one overlapping a
        second, with nothing looking again. render() sums overlapping clips, so
        both warnings became unintelligible while the schedule reported both as
        delivered.
        """
        return any(c.speak_at < k.ends_at and k.speak_at < c.ends_at
                   for k in others)

    def inverts_order(c, others):
        """Callouts must be heard in road order, in BOTH directions.

        A rider maps what they hear onto what they see next. The guard was
        originally only on the early path, but pushing a callout LATER jumps it
        behind callouts anchored further down the road — which is where
        inversion actually happened.
        """
        return any((k.anchor_s < c.anchor_s and k.speak_at > c.speak_at)
                   or (k.anchor_s > c.anchor_s and k.speak_at < c.speak_at)
                   for k in others)

    def place(c, others, flexible):
        """Find the best legal start time. Returns True if placed.

        A slot is legal only if it starts at or after t=0, overlaps nothing,
        preserves road order, and leaves lead >= 0 — the hard invariant. A
        callout finishing after its own corner describes road the rider is
        already in, and they will attach it to the NEXT corner.

        `flexible` callouts (warnings) may be moved off the ideal slot; plain
        descriptions may not, because for those a shuffled call is worth less
        than the silence.
        """
        arrive = arrive_of[id(c)]
        ideal = c.speak_at
        candidates = [ideal]
        if flexible:
            for k in others:
                candidates.append(k.ends_at + GAP)                 # after
                candidates.append(k.speak_at - c.duration - GAP)   # before
        best = None
        for start in candidates:
            c.speak_at = max(0.0, start)   # never negative: render() would clip
            ld = arrive - c.ends_at
            if ld < 0.0 or ld > MAX_EARLY_LEAD:
                continue
            if collides(c, others) or inverts_order(c, others):
                continue
            score = abs(ld - lead)
            if best is None or score < best[0]:
                best = (score, c.speak_at, ld)
        if best is None:
            c.speak_at = ideal
            c.lead = arrive - c.ends_at
            return False
        _, c.speak_at, c.lead = best
        # Flags are derived from the FINAL placement, never carried over from
        # the ideal one. A stale `unwarnable` previously deleted warnings that
        # had been successfully placed, citing a lead they no longer had.
        c.short_lead = c.lead < lead
        c.unwarnable = c.lead < MIN_LEAD
        return True

    kept = []
    for c in live:
        if place(c, kept, flexible=c.is_warning):
            kept.append(c)
        elif c.is_warning:
            c.dropped = (f"no slot with lead >= 0 preserving road order "
                         f"(best {c.lead:.1f}s)")
            dropped.append(c)
        else:
            c.dropped = "collided with a higher-priority callout"
            dropped.append(c)

    kept.sort(key=lambda c: c.speak_at)
    return kept, dropped


def unspoken_warnings(dropped):
    """Warnings that could not be delivered at all. The number that matters."""
    return [c for c in dropped if c.is_warning]


def format_schedule(kept, dropped, s_grid, t_grid):
    lines = [f"{'t':>7}  {'pos':>6}  {'lead':>5}  callout",
             f"{'-'*7}  {'-'*6}  {'-'*5}  {'-'*44}"]
    for c in kept:
        flag = " <SHORT LEAD" if c.short_lead else ""
        lines.append(f"{c.speak_at:7.1f}  {c.anchor_s:6.0f}  "
                     f"{c.lead:5.1f}  {c.text}{flag}")
    unspoken = unspoken_warnings(dropped)
    if unspoken:
        # Lead with this. An unspoken warning is the number that matters, and it
        # must not be buried among ordinary verbosity suppressions.
        lines.append("")
        lines.append(f"*** {len(unspoken)} WARNING(S) COULD NOT BE SPOKEN — the "
                     f"callout stream is over-subscribed here:")
        for c in unspoken:
            lines.append(f"{'':7}  {c.anchor_s:6.0f}  {'':5}  "
                         f"{c.text}   [{c.dropped}]")
    other = [c for c in dropped if not c.is_warning]
    if other:
        lines.append("")
        lines.append("suppressed:")
        for c in other:
            lines.append(f"{'':7}  {c.anchor_s:6.0f}  {'':5}  "
                         f"{c.text}   [{c.dropped}]")
    return "\n".join(lines)

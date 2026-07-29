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

# Lower number wins. A hazard interrupts a corner call; a corner call beats
# traffic chatter. Nothing outranks a hazard.
PRIORITY = {"hazard": 0, "crest": 1, "corner": 2, "info": 3}

# Verbosity. Full speaks everything; Guardian speaks only what could hurt you.
MODES = ("full", "highlights", "guardian")

# Words that make a callout a WARNING rather than a description. A warning may
# never be dropped — not by verbosity, not by collision. See schedule().
WARNING_WORDS = ("tightens", "don't cut", "over crest", "blind crest")

# Corners per merged utterance. Linked corners are spoken as one call
# ("right 4 into left 2") rather than two, which is both what a co-driver says
# and what stops the second half colliding with the first and being dropped.
#
# Capped at 2 because linking is common: on the Tail of the Dragon 181 of 260
# corners link to the next one, so an uncapped chain would produce a single
# unbroken sentence covering half the road.
MAX_LINK_CHAIN = 2


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
    short_lead: bool = False  # True when full lead could not be given

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


def build_callouts(corners, loose_crests, max_chain=MAX_LINK_CHAIN):
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
    out = []
    i = 0
    n = len(corners)
    while i < n:
        group = [corners[i]]
        while (len(group) < max_chain and i + len(group) <= n - 1
               and group[-1].linked_to_next):
            group.append(corners[i + len(group)])
        text = " into ".join(corner_phrase(c) for c in group)
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

    for c in live:
        c.duration = duration_fn(c.text)
        arrive = time_at(s_grid, t_grid, c.anchor_s)
        # finish `lead` seconds before arrival, so start earlier by the clip length
        c.speak_at = arrive - lead - c.duration
        if c.speak_at < 0.0:
            # The corner is too close to the start of the ride to give full
            # warning. Clamp and FLAG it: the audio renderer would otherwise
            # clip the front of the clip and the callout would be heard
            # mid-word, looking like a delivered warning when it wasn't.
            c.speak_at = 0.0
            c.short_lead = True
        c.lead = arrive - c.ends_at

    live.sort(key=lambda c: (c.speak_at, c.priority))

    def overlap(c, others):
        return next((k for k in others
                     if c.speak_at < k.ends_at and k.speak_at < c.ends_at), None)

    def delay_into_free_slot(c, others):
        """Push a callout later until it fits, then recompute its lead.

        Used only for warnings: silence about a tightening corner or a blind
        apex is worse than hearing it with less lead than we would like. Plain
        corner descriptions are dropped instead, because for those late really
        is worse than absent.
        """
        for _ in range(8):  # bounded: cascading collisions are rare
            clash = overlap(c, others)
            if clash is None:
                break
            c.speak_at = clash.ends_at + 0.05
        c.lead = time_at(s_grid, t_grid, c.anchor_s) - c.ends_at
        c.short_lead = c.lead < lead

    kept = []
    for c in live:
        clash = overlap(c, kept)
        if clash is None:
            kept.append(c)
            continue

        if c.priority < clash.priority:
            # Strictly more important wins the slot — a hazard outranks
            # everything, including a corner call carrying "tightens".
            kept.remove(clash)
            kept.append(c)
            if clash.is_warning:
                delay_into_free_slot(clash, kept)
                kept.append(clash)
            else:
                clash.dropped = f"pre-empted by {c.kind} at {c.anchor_s:.0f} m"
                dropped.append(clash)
        elif c.is_warning:
            delay_into_free_slot(c, kept)
            kept.append(c)
        else:
            # never delay a plain corner call to fit it in — late is the
            # dangerous direction, so it is dropped and said so
            c.dropped = f"collided with {clash.kind} at {clash.anchor_s:.0f} m"
            dropped.append(c)

    kept.sort(key=lambda c: c.speak_at)
    return kept, dropped


def format_schedule(kept, dropped, s_grid, t_grid):
    lines = [f"{'t':>7}  {'pos':>6}  {'lead':>5}  callout",
             f"{'-'*7}  {'-'*6}  {'-'*5}  {'-'*44}"]
    for c in kept:
        flag = " <SHORT LEAD" if c.short_lead else ""
        lines.append(f"{c.speak_at:7.1f}  {c.anchor_s:6.0f}  "
                     f"{c.lead:5.1f}  {c.text}{flag}")
    if dropped:
        lines.append("")
        lines.append("suppressed:")
        for c in dropped:
            lines.append(f"{'':7}  {c.anchor_s:6.0f}  {'':5}  "
                         f"{c.text}   [{c.dropped}]")
    return "\n".join(lines)

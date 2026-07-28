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


@dataclass
class Callout:
    anchor_s: float      # position the callout refers to
    text: str
    kind: str            # 'corner' | 'crest' | 'hazard' | 'info'
    severity: object = None
    speak_at: float = 0.0   # scheduled start time, seconds into the ride
    duration: float = 0.0
    dropped: str = ""    # non-empty if suppressed, with the reason

    @property
    def priority(self):
        return PRIORITY[self.kind]

    @property
    def ends_at(self):
        return self.speak_at + self.duration


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
    warns = ("tightens", "don't cut", "over crest")
    if any(w in c.text for w in warns):
        return True
    rank = _severity_rank(c.severity)
    if mode == "highlights":
        return rank <= 4
    if mode == "guardian":
        return rank <= 2
    raise ValueError(f"unknown verbosity mode: {mode!r}")


def build_callouts(corners, loose_crests):
    """Corners and crests into unscheduled callouts, in road order."""
    out = []
    prev_linked = False
    for c in corners:
        phrase = corner_phrase(c)
        text = f"into {phrase}" if prev_linked else phrase
        out.append(Callout(anchor_s=c.s0, text=text, kind="corner",
                           severity=c.severity))
        prev_linked = c.linked_to_next
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

    live.sort(key=lambda c: (c.speak_at, c.priority))

    kept = []
    for c in live:
        clash = next((k for k in kept if c.speak_at < k.ends_at
                      and k.speak_at < c.ends_at), None)
        if clash is None:
            kept.append(c)
            continue
        if c.priority < clash.priority:
            # more important: shift the loser out rather than dropping this
            clash.dropped = f"pre-empted by {c.kind} at {c.anchor_s:.0f} m"
            kept.remove(clash)
            dropped.append(clash)
            kept.append(c)
        else:
            # never delay a callout to fit it in — late is the dangerous
            # direction, so it is dropped and said so
            c.dropped = f"collided with {clash.kind} at {clash.anchor_s:.0f} m"
            dropped.append(c)

    kept.sort(key=lambda c: c.speak_at)
    return kept, dropped


def format_schedule(kept, dropped, s_grid, t_grid):
    lines = [f"{'t':>7}  {'pos':>6}  {'lead':>5}  callout",
             f"{'-'*7}  {'-'*6}  {'-'*5}  {'-'*44}"]
    for c in kept:
        arrive = time_at(s_grid, t_grid, c.anchor_s)
        lines.append(f"{c.speak_at:7.1f}  {c.anchor_s:6.0f}  "
                     f"{arrive - c.ends_at:5.1f}  {c.text}")
    if dropped:
        lines.append("")
        lines.append("suppressed:")
        for c in dropped:
            lines.append(f"{'':7}  {c.anchor_s:6.0f}  {'':5}  "
                         f"{c.text}   [{c.dropped}]")
    return "\n".join(lines)

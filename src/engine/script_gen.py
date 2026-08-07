"""Turn analyzed corners into a rally-style pacenote script."""


def dist_call(meters):
    """Round distance the way a co-driver would."""
    if meters < 40:
        return None  # immediate / linked
    for step in (50, 100, 150, 200, 300, 400, 600, 800):
        if meters < step * 1.25:
            return step
    return int(round(meters / 200) * 200)


def corner_phrase(c):
    d = "left" if c.direction == "L" else "right"
    if c.severity == "hairpin":
        base = f"hairpin {d}"
    else:
        base = f"{d} {c.severity}"
    mods = list(c.modifiers)
    return " ".join([base] + mods) if mods else base


def build_script(corners, loose_crests, road_length):
    """Returns list of (position_m, text) callout events, plus printable script."""
    events = []
    prev_end = 0.0
    prev_linked = False
    for c in corners:
        gap = c.s0 - prev_end
        phrase = corner_phrase(c)
        if prev_linked:
            events.append((c.s0, f"into {phrase}"))
        else:
            d = dist_call(gap)
            if d:
                events.append((c.s0, f"{phrase}, in {d}"))
            else:
                events.append((c.s0, phrase))
        prev_end = c.s1
        prev_linked = c.linked_to_next
    for cs in loose_crests:
        events.append((cs, "caution, blind crest"))
    events.sort(key=lambda e: e[0])
    lines = [f"{'pos':>6}  callout", f"{'-'*6}  {'-'*40}"]
    for pos, text in events:
        lines.append(f"{pos:5.0f}m  {text}")
    lines.append(f"{'-'*6}  {'-'*40}")
    lines.append(f"road length {road_length:.0f} m, {len(corners)} corners, "
                 f"{len(loose_crests)} standalone crests")
    return events, "\n".join(lines)

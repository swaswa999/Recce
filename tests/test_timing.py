"""Callout timing and verbosity.

The dangerous failure in this module is a callout that arrives LATE — a rider
already committing to a corner while still being told what it is. Everything
here is built so late is impossible and early is merely annoying.
"""
import numpy as np
import pytest

from pipeline import analyze
from geometry import resample, signed_radius, smooth_radius, SEG_SPACING
from speed import speed_profile, time_profile, lean_angle, time_at, A_LAT, G
from timing import (build_callouts, schedule, keep_for_mode, Callout,
                    LEAD_SECONDS, MODES, MAX_LINK_CHAIN, MIN_LEAD,
                    MAX_EARLY_LEAD, MAX_UTTERANCE_SECONDS, unspoken_warnings,
                    estimate_duration)
from synth_road import build_road


@pytest.fixture(scope="module")
def ride():
    x, y, z, _, _ = build_road()
    s, corners, loose = analyze(x, y, z)
    _, xi, yi, _ = resample(x, y, None, spacing=SEG_SPACING)
    r = smooth_radius(signed_radius(xi, yi, window=3), k=5)
    v = speed_profile(s, r)
    t = time_profile(s, v)
    return {"s": s, "t": t, "v": v, "r": r,
            "callouts": build_callouts(corners, loose)}


# --- the core guarantee ----------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_no_callout_ever_finishes_late(ride, mode):
    """Every callout must FINISH at least LEAD_SECONDS before its corner."""
    kept, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    late = []
    for c in kept:
        arrive = time_at(ride["s"], ride["t"], c.anchor_s)
        slack = arrive - c.ends_at
        if slack < LEAD_SECONDS - 1e-6:
            late.append((c.text, round(slack, 2)))
    assert not late, (
        f"mode={mode}: callouts finishing less than {LEAD_SECONDS}s before the "
        f"corner: {late}. A rider hearing the description while already "
        f"committing has been told too late."
    )


def test_faster_ride_triggers_callout_earlier_in_distance(ride):
    """Lead is in seconds, so a faster rider must be warned further back."""
    s, r = ride["s"], ride["r"]
    slow_t = time_profile(s, speed_profile(s, r, v_max=11.0))   # ~40 km/h
    fast_t = time_profile(s, speed_profile(s, r, v_max=33.0))   # ~120 km/h

    slow, _ = schedule(ride["callouts"], s, slow_t)
    fast, _ = schedule(ride["callouts"], s, fast_t)
    by_anchor_slow = {c.anchor_s: c for c in slow}

    compared = 0
    for c in fast:
        sc = by_anchor_slow.get(c.anchor_s)
        if sc is None:
            continue
        slow_pos = np.interp(sc.speak_at, slow_t, s)
        fast_pos = np.interp(c.speak_at, fast_t, s)
        assert fast_pos <= slow_pos + 1e-6, (
            f"{c.text!r}: fast rider warned at {fast_pos:.0f} m but slow rider "
            f"at {slow_pos:.0f} m — fixed-distance behaviour, not seconds-ahead"
        )
        compared += 1
    assert compared >= 3, "test did not actually compare enough callouts"


# --- verbosity must never reduce safety -----------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_verbosity_never_suppresses_a_warning(ride, mode):
    """Quieter must not mean less safe."""
    kept, dropped = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    lost = [c.text for c in dropped
            if c.is_warning and c.dropped.startswith("verbosity")]
    assert not lost, f"mode={mode} suppressed warning callouts: {lost}"


@pytest.mark.parametrize("mode", MODES)
def test_no_warning_is_dropped_FOR_ANY_REASON(ride, mode):
    """The gap that let a real defect through.

    The verbosity test above filters on `c.dropped.startswith("verbosity")`, so
    it says nothing about COLLISION drops. On the Tail of the Dragon the
    scheduler silently discarded 12 callouts, 11 of them carrying "don't cut" or
    "tightens", and the suite stayed green. A warning must survive every drop
    path, not just the one that was tested.
    """
    kept, dropped = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    lost = [(c.text, c.dropped) for c in dropped if c.is_warning]
    assert not lost, (
        f"mode={mode}: warnings dropped: {lost}. Silence about a tightening "
        f"corner or blind apex is worse than a late call."
    )


def test_hazards_and_crests_count_as_warnings():
    """is_warning must key off KIND too, not just text.

    "caution, gravel" contains none of the corner-shape warning words. When
    is_warning was text-only, a hazard colliding with a corner call that said
    "tightens" was itself discarded — the exact inversion of the priority rule.
    """
    assert Callout(anchor_s=0, text="caution, gravel", kind="hazard").is_warning
    assert Callout(anchor_s=0, text="caution, blind crest", kind="crest").is_warning
    assert Callout(anchor_s=0, text="right 4 tightens", kind="corner",
                   severity=4).is_warning
    assert not Callout(anchor_s=0, text="right 4", kind="corner",
                       severity=4).is_warning


def test_short_lead_at_ride_start_is_spoken_not_silenced(ride):
    """An uncontended callout close to the start is KEPT, flagged, not deleted.

    It is fully audible from t=0 and still ends before the corner, so the
    "attaches to the next corner" failure does not apply — the trade here is
    genuinely "some warning" versus "no warning", and silence is the optimistic
    choice. An earlier version dropped these for lead < MIN_LEAD, which silenced
    the Dragon's first corner and the first ~60 m of every rendered segment.

    Contrast test_no_kept_callout_ever_has_negative_lead: finishing AFTER the
    corner is the real invariant, and that is never allowed.
    """
    s, t = ride["s"], ride["t"]
    early = Callout(anchor_s=25.0, text="left 4", kind="corner", severity=4)
    kept, dropped = schedule([early], s, t)
    assert kept, "an audible, uncontended callout was silenced"
    c = kept[0]
    assert c.speak_at >= 0.0
    assert c.lead >= 0.0, "finishes after its own corner"
    assert c.short_lead, "reduced lead was not flagged"


def test_reduced_but_usable_lead_is_kept_and_flagged(ride):
    """Between MIN_LEAD and the ideal, keep it but mark it."""
    s, t = ride["s"], ride["t"]
    # far enough in to be warnable, close enough that lead is squeezed
    a = Callout(anchor_s=300.0, text="right 3 tightens", kind="corner", severity=3)
    b = Callout(anchor_s=318.0, text="left 2 over crest don't cut",
                kind="corner", severity=2)
    kept, _ = schedule([a, b], s, t)
    assert kept, "everything was dropped"
    for c in kept:
        assert c.lead >= MIN_LEAD, f"{c.text!r} kept with {c.lead:.2f}s lead"
        assert not c.unwarnable
    squeezed = [c for c in kept if c.lead < LEAD_SECONDS]
    for c in squeezed:
        assert c.short_lead, f"{c.text!r} has {c.lead:.2f}s lead but is unflagged"


@pytest.mark.parametrize("mode", MODES)
def test_verbosity_never_suppresses_a_hazard_or_crest(ride, mode):
    for kind in ("hazard", "crest"):
        c = Callout(anchor_s=500.0, text="caution, gravel", kind=kind)
        assert keep_for_mode(c, mode), f"{kind} dropped in mode={mode}"


def test_guardian_is_quieter_than_full(ride):
    full, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode="full")
    guard, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode="guardian")
    assert len(guard) < len(full), "guardian mode suppressed nothing"


def test_unknown_verbosity_mode_is_an_error(ride):
    with pytest.raises(ValueError):
        keep_for_mode(Callout(anchor_s=0.0, text="right 4", kind="corner",
                              severity=4), "whisper")


# --- priority --------------------------------------------------------------

def test_hazard_preempts_a_colliding_corner_call(ride):
    """Nothing outranks a hazard."""
    s, t = ride["s"], ride["t"]
    corner = Callout(anchor_s=530.0, text="right 3 tightens", kind="corner",
                     severity=3)
    hazard = Callout(anchor_s=531.0, text="caution, gravel", kind="hazard")
    kept, dropped = schedule([corner, hazard], s, t)
    assert any(c.kind == "hazard" for c in kept), "hazard was not spoken"
    if len(kept) == 1:
        assert dropped and dropped[0].kind == "corner"


def _uniform(length=1200.0, kmh=72.0):
    s = np.arange(0.0, length, 5.0)
    return s, s / (kmh / 3.6)


@pytest.mark.parametrize("mode", MODES)
def test_no_kept_callout_ever_has_negative_lead(ride, mode):
    """THE invariant. A callout finishing after its corner describes road the
    rider is already in, and they will attach it to the NEXT corner — a hairpin
    call landing on a corner of unknown severity.

    Strictly worse than the drop it replaced: a dropped callout is silence, a
    negative-lead callout is an actively wrong description.
    """
    kept, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    late = [(c.text, round(c.lead, 2)) for c in kept if c.lead < 0]
    assert not late, f"mode={mode}: callouts finishing AFTER their corner: {late}"


@pytest.mark.parametrize("mode", MODES)
def test_squeezed_leads_are_always_flagged(ride, mode):
    """Below the ideal lead is allowed; being silent about it is not."""
    kept, _ = schedule(ride["callouts"], ride["s"], ride["t"], mode=mode)
    unflagged = [(c.text, round(c.lead, 2)) for c in kept
                 if c.lead < LEAD_SECONDS and not c.short_lead]
    assert not unflagged, f"mode={mode}: squeezed but unflagged: {unflagged}"


def test_stale_flags_never_drop_a_placed_callout(ride):
    """Flags must derive from the FINAL placement, not the ideal one.

    A stale `unwarnable` computed before placement deleted warnings that had
    been successfully placed — one was removed for "lead 2.5s below the 1.0s
    minimum", which is arithmetically self-contradicting.
    """
    kept, dropped = schedule(ride["callouts"], ride["s"], ride["t"])
    for c in kept:
        assert c.short_lead == (c.lead < LEAD_SECONDS), \
            f"{c.text!r}: short_lead={c.short_lead} but lead={c.lead:.2f}"
    contradictory = [c for c in dropped if c.is_warning and c.lead >= MIN_LEAD
                     and "below" in c.dropped]
    assert not contradictory, (
        f"dropped for a lead it did not have: "
        f"{[(c.text, round(c.lead, 2), c.dropped) for c in contradictory]}"
    )


def test_dense_warnings_never_produce_a_late_callout():
    """The cascade that the delay-only scheduler turned into a pile-up.

    Twelve tightly spaced warning corners used to yield leads from +3.0 down to
    -16.2 s, with 10 of 12 callouts finishing after their corner — one of them
    spoken 360 m past it.
    """
    s, t = _uniform()
    cs = [Callout(anchor_s=float(200 + 20 * i), kind="corner", severity=2,
                  text=f"left {i % 5 + 1} tightens over crest don't cut")
          for i in range(12)]
    kept, dropped = schedule(cs, s, t)
    # The invariant is lead >= 0 — never finishing after the corner. Squeezed
    # but positive leads are kept and flagged rather than silenced.
    assert all(c.lead >= 0.0 for c in kept), \
        f"leads: {sorted(round(c.lead, 2) for c in kept)}"
    for c in kept:
        if c.lead < MIN_LEAD:
            assert c.short_lead, f"{c.text!r} has {c.lead:.2f}s lead but is unflagged"
    # over-subscribed: the shortfall must be REPORTED, never silently mangled
    assert len(kept) + len(dropped) == len(cs)
    assert unspoken_warnings(dropped), \
        "an over-subscribed stream dropped nothing — warnings were mangled instead"


def test_no_two_kept_callouts_overlap_in_time():
    """render() sums overlapping clips, so two kept callouts that overlap become
    unintelligible while neither is marked dropped — a silent warning loss."""
    s, t = _uniform()
    cs = [Callout(anchor_s=float(200 + 20 * i), kind="corner", severity=2,
                  text=f"left {i % 5 + 1} tightens over crest don't cut")
          for i in range(12)]
    kept, _ = schedule(cs, s, t)
    ordered = sorted(kept, key=lambda c: c.speak_at)
    bad = [(a.text[:20], b.text[:20]) for a, b in zip(ordered, ordered[1:])
           if b.speak_at < a.ends_at - 1e-9]
    assert not bad, f"overlapping kept callouts: {bad}"


def test_callouts_are_spoken_in_road_order():
    """A rider maps what they hear onto what they see next, so announcing a
    corner at 240 m before one at 200 m misattributes both. Early placement
    must not jump a corner that comes earlier on the road."""
    s, t = _uniform()
    cs = [Callout(anchor_s=float(p), kind="corner", severity=2,
                  text=f"hairpin left tightens into right {i + 1} tightens")
          for i, p in enumerate((200, 240, 275))]
    cs.append(Callout(anchor_s=300.0, kind="hazard", text="caution, gravel"))
    kept, _ = schedule(cs, s, t)
    anchors = [c.anchor_s for c in kept]
    assert anchors == sorted(anchors), \
        f"callouts out of road order: {anchors}"


def _fuzz_schedules(n=400, seed=0):
    """Mixed durations, mixed kinds, clustered near t=0.

    Every invariant test above is built from uniform, mid-ride, same-length
    callouts — precisely the geometry where none of the real defects fire. This
    generates the awkward cases: short hazards beside long merged chains, tight
    clusters, and anchors close enough to the start that the clamp engages.
    """
    rng = np.random.default_rng(seed)
    s, t = _uniform(2000.0, kmh=72.0)
    for _ in range(n):
        cs = []
        for _ in range(int(rng.integers(2, 7))):
            anchor = float(rng.uniform(20, 400))
            kind = str(rng.choice(["corner", "corner", "corner", "hazard", "crest"]))
            words = int(rng.integers(1, 11))
            warn = bool(rng.integers(0, 2))
            text = " ".join(["word"] * words) + (" tightens don't cut" if warn else "")
            cs.append(Callout(anchor_s=anchor, kind=kind, text=text,
                              severity=int(rng.integers(1, 7))))
        yield cs, s, t


def test_fuzz_no_overlap_no_inversion_no_late_callout():
    """The three hard invariants, over awkward geometry rather than tidy cases."""
    bad_overlap = bad_order = bad_late = bad_negative = 0
    for cs, s, t in _fuzz_schedules():
        kept, _ = schedule(cs, s, t)
        ordered = sorted(kept, key=lambda c: c.speak_at)
        if any(b.speak_at < a.ends_at - 1e-9 for a, b in zip(ordered, ordered[1:])):
            bad_overlap += 1
        if [c.anchor_s for c in ordered] != sorted(c.anchor_s for c in ordered):
            bad_order += 1
        if any(c.lead < -1e-9 for c in kept):
            bad_late += 1
        if any(c.speak_at < -1e-9 for c in kept):
            bad_negative += 1
    assert bad_overlap == 0, f"{bad_overlap} schedules with overlapping clips"
    assert bad_order == 0, f"{bad_order} schedules heard out of road order"
    assert bad_late == 0, f"{bad_late} schedules with a callout finishing late"
    assert bad_negative == 0, f"{bad_negative} schedules with negative speak_at"


def test_fuzz_reported_lead_matches_what_is_rendered():
    """speak_at is what render() uses; lead must describe THAT, not an intent.

    A negative speak_at was clamped by the renderer, so the reported lead
    overstated the delivered lead by exactly the clamped amount.
    """
    for cs, s, t in _fuzz_schedules(n=200, seed=7):
        kept, _ = schedule(cs, s, t)
        for c in kept:
            rendered_start = max(0.0, c.speak_at)
            real_lead = np.interp(c.anchor_s, s, t) - (rendered_start + c.duration)
            assert abs(real_lead - c.lead) < 1e-6, (
                f"reported lead {c.lead:.2f}s but renders as {real_lead:.2f}s"
            )


def test_fuzz_a_hazard_rarely_loses_to_a_plain_description():
    """Nothing outranks a hazard — enforced in code, not just in a comment.

    Placement runs in priority order and a high-priority callout may displace a
    lower-priority non-warning. Before that, an inflexible corner description
    that happened to sort first could permanently hold the slot a crest needed.

    Measure only GENUINE contention. A crude "any dropped hazard alongside any
    kept description" count reads 315/4000, but 233 of those are hazards that
    could not be spoken at ANY time — they need more speech than exists before
    their own arrival, which is a capacity limit, not a priority failure. Real
    contention is ~13/4000, and those are hazard-versus-hazard.
    """
    contended = 0
    for cs, s, t in _fuzz_schedules(n=400, seed=11):
        kept, dropped = schedule(cs, s, t)
        lost = [c for c in dropped if c.kind in ("hazard", "crest")]
        plain = [c for c in kept if c.kind == "corner" and not c.is_warning]
        for l in lost:
            arrive = np.interp(l.anchor_s, s, t)
            if arrive - l.duration < 0:
                continue                      # unspeakable at any time
            if any(p.speak_at < arrive and (arrive - l.duration) < p.ends_at
                   for p in plain):
                contended += 1
                break
    assert contended <= 0.02 * 400, (
        f"{contended}/400 schedules silenced a hazard or crest that genuinely "
        f"contended with a droppable corner description"
    )


def test_early_placement_is_bounded():
    """Arbitrarily early is its own wrong-corner failure."""
    s, t = _uniform()
    cs = [Callout(anchor_s=float(p), kind="corner", severity=2,
                  text=f"left 2 tightens over crest don't cut {i}")
          for i, p in enumerate((300, 330, 360))]
    kept, _ = schedule(cs, s, t)
    too_early = [(c.text[:20], round(c.lead, 2)) for c in kept
                 if c.lead > MAX_EARLY_LEAD + 1e-6]
    assert not too_early, f"callouts placed further ahead than {MAX_EARLY_LEAD}s: {too_early}"


def test_utterance_length_is_bounded(ride):
    """Chains are limited by how long they take to say, not corner count."""
    for c in ride["callouts"]:
        d = estimate_duration(c.text)
        assert d <= MAX_UTTERANCE_SECONDS + 1e-6 or " into " not in c.text, (
            f"merged utterance runs {d:.1f}s: {c.text!r}"
        )


def test_linked_corners_merge_into_one_utterance(ride):
    """A linked pair is one call, not two that collide.

    Emitting "right 4" and "into left 2" as separate callouts put the second
    inside the first one's speech, so it collided and was dropped — losing both
    the linkage and any warning it carried.
    """
    texts = [c.text for c in ride["callouts"]]
    merged = [t for t in texts if " into " in t]
    assert merged, f"no merged linked callout found in {texts}"
    assert not any(t.startswith("into ") for t in texts), (
        f"found a bare 'into ...' callout, which means linking still emits two "
        f"separate calls: {[t for t in texts if t.startswith('into ')]}"
    )


def test_merged_callout_takes_the_hardest_severity(ride):
    """Otherwise verbosity could drop a group because its first corner is easy."""
    from synth_road import build_road
    from pipeline import analyze
    x, y, z, _, _ = build_road()
    _, corners, loose = analyze(x, y, z)
    cs = build_callouts(corners, loose)
    pair = next((c for c in cs if " into " in c.text), None)
    assert pair is not None
    # "right 4 into left 2" -> severity must be the 2, not the 4
    assert pair.severity == 2, (
        f"merged callout {pair.text!r} took severity {pair.severity}, expected "
        f"the harder of the pair"
    )


def test_link_chain_is_capped(ride):
    """Linking is common enough that an uncapped chain becomes one long sentence.

    On the Tail of the Dragon 181 of 260 corners link to the next one.
    """
    for c in ride["callouts"]:
        assert c.text.count(" into ") <= MAX_LINK_CHAIN - 1, (
            f"callout chains {c.text.count(' into ') + 1} corners, cap is "
            f"{MAX_LINK_CHAIN}: {c.text!r}"
        )


def test_suppressed_callouts_are_reported_not_silent(ride):
    """A dropped callout must carry a reason — silent loss looks like coverage."""
    _, dropped = schedule(ride["callouts"], ride["s"], ride["t"],
                          mode="guardian")
    assert dropped, "expected guardian to suppress something on this road"
    assert all(c.dropped for c in dropped), "a callout was dropped with no reason"


# --- speed model ----------------------------------------------------------

def test_speed_respects_lateral_grip(ride):
    """Speed in a corner must not exceed sqrt(a_lat * r)."""
    v, r = ride["v"], ride["r"]
    limit = np.sqrt(A_LAT * np.abs(r))
    bad = np.where(v > limit + 1e-6)[0]
    assert len(bad) == 0, f"{len(bad)} points exceed the grip limit"


def test_time_is_monotonic(ride):
    assert np.all(np.diff(ride["t"]) > 0), "time went backwards along the road"


def test_hairpin_is_the_slowest_point(ride):
    """Sanity: the 12 m hairpin should be where speed bottoms out."""
    s, v = ride["s"], ride["v"]
    slowest = s[int(np.argmin(v))]
    assert 940 < slowest < 1040, (
        f"slowest point at {slowest:.0f} m, expected inside the hairpin "
        f"(970-1025 m)"
    )


def test_lean_angle_is_physically_sane(ride):
    """tan(theta) = v^2/(g*r); at the grip limit that is atan(a_lat/g)."""
    lean = lean_angle(ride["v"], ride["r"])
    ceiling = np.degrees(np.arctan(A_LAT / G))
    assert lean.max() <= ceiling + 0.5, (
        f"peak lean {lean.max():.1f} deg exceeds the {ceiling:.1f} deg implied "
        f"by the lateral-grip cap"
    )
    assert lean.max() > 20, "no meaningful lean anywhere on a canyon road"

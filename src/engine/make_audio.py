"""Render a ride's callouts to a single timed WAV you can listen to.

This is the Phase D validation tool: it produces the actual audio experience
without needing an app, a phone or a bike. Play it on a known road (or just
listen at a desk) and judge whether the callouts land right and whether the
chatter is tolerable.

Uses macOS `say` for TTS and numpy for mixing, so it needs no extra packages.

Usage:
    python3 make_audio.py                        # synthetic road, full verbosity
    python3 make_audio.py --mode guardian
    python3 make_audio.py --road road.json -o out.wav
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

from geometry import lonlat_to_xy, resample, signed_radius, smooth_radius, SEG_SPACING
from pipeline import analyze
from speed import speed_profile, time_profile, lean_angle
from timing import build_callouts, schedule, format_schedule, MODES
from synth_road import build_road

RATE = 22050
VOICE = os.environ.get("RECCE_VOICE", "Daniel")


def tts(text, path, voice=VOICE, rate_wpm=180):
    """Render one phrase to a mono 16-bit WAV via macOS `say`."""
    subprocess.run(
        ["say", "-v", voice, "-r", str(rate_wpm),
         "--data-format=LEI16@%d" % RATE, "-o", path, text],
        check=True, capture_output=True)


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2, "expected 16-bit"
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def measure_durations(callouts, tmpdir, voice=VOICE):
    """Render each phrase once and return real clip lengths.

    Scheduling with real durations rather than a words-per-second estimate is
    what keeps the "finish before the lead point" guarantee honest — a phrase
    that takes longer than estimated would otherwise eat into the rider's
    thinking room.
    """
    clips = {}
    for c in callouts:
        if c.text in clips:
            continue
        path = os.path.join(tmpdir, f"clip{len(clips)}.wav")
        tts(c.text, path, voice=voice)
        clips[c.text] = read_wav(path)
    return clips


def render(kept, clips, total_seconds, rate=RATE):
    """Mix scheduled clips into one track."""
    n = int((total_seconds + 3.0) * rate)
    track = np.zeros(n, dtype=np.float32)
    for c in kept:
        clip = clips[c.text]
        start = max(0, int(c.speak_at * rate))
        end = min(n, start + len(clip))
        if end > start:
            track[start:end] += clip[: end - start]
    peak = np.max(np.abs(track)) or 1.0
    if peak > 1.0:
        track /= peak
    return track


def write_wav(path, track, rate=RATE):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())


def load_road(path):
    with open(path) as f:
        road = json.load(f)
    lon = np.array(road["lon"])
    lat = np.array(road["lat"])
    ele = np.array(road["ele"]) if road.get("ele") else None
    x, y = lonlat_to_xy(lon, lat)
    return x, y, ele, road.get("name", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--road", help="road.json from fetch_osm.py; omit for the "
                                   "synthetic answer-key road")
    ap.add_argument("--mode", default="full", choices=MODES)
    ap.add_argument("-o", "--out", default="ride.wav")
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--no-audio", action="store_true",
                    help="print the schedule only, skip TTS")
    args = ap.parse_args()

    if args.road:
        x, y, z, name = load_road(args.road)
    else:
        x, y, z, _truth, _len = build_road()
        name = "synthetic canyon road"

    s, corners, loose = analyze(x, y, z)

    # speed needs a radius sampled on the same grid as s
    _, xi, yi, _ = resample(x, y, None, spacing=SEG_SPACING)
    r_grid = smooth_radius(signed_radius(xi, yi, window=3), k=5)
    v = speed_profile(s, r_grid)
    t = time_profile(s, v)
    lean = lean_angle(v, r_grid)

    callouts = build_callouts(corners, loose)
    kept, dropped = schedule(callouts, s, t, mode=args.mode)

    print(f"road: {name}")
    print(f"length {s[-1]:.0f} m, {len(corners)} corners, "
          f"ride time {t[-1] / 60:.1f} min")
    print(f"speed {v.min() * 3.6:.0f}-{v.max() * 3.6:.0f} km/h "
          f"(mean {v.mean() * 3.6:.0f}), peak lean {lean.max():.0f} deg")
    print(f"verbosity: {args.mode} — {len(kept)} spoken, {len(dropped)} suppressed\n")

    if args.no_audio:
        print(format_schedule(kept, dropped, s, t))
        return

    if not shutil.which("say"):
        sys.exit("`say` not found — this renderer needs macOS TTS. "
                 "Re-run with --no-audio for the schedule.")

    with tempfile.TemporaryDirectory() as tmp:
        clips = measure_durations(kept, tmp, voice=args.voice)
        # reschedule with real clip lengths, then re-render
        real = {k: len(v_) / RATE for k, v_ in clips.items()}
        kept, dropped = schedule(callouts, s, t, mode=args.mode,
                                 duration_fn=lambda txt: real.get(
                                     txt, len(txt.split()) / 2.6))
        missing = [c.text for c in kept if c.text not in clips]
        for text in missing:
            path = os.path.join(tmp, f"extra{abs(hash(text)) % 9999}.wav")
            tts(text, path, voice=args.voice)
            clips[text] = read_wav(path)
        track = render(kept, clips, t[-1])
        write_wav(args.out, track)

    print(format_schedule(kept, dropped, s, t))
    print(f"\nwrote {args.out} ({len(track) / RATE / 60:.1f} min)")
    print("play it against a ride of the same road, or just listen for pacing.")


if __name__ == "__main__":
    main()

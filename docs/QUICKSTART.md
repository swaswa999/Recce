# Quickstart

Every command below has been run and verified on this machine.

## Requirements

`numpy` and `pytest`, plus macOS `say` for audio. Nothing else — no GDAL, no
rasterio, no API keys.

```
pip install numpy pytest
```

## Run the tests

From the **repo root**:

```
cd ~/Desktop/Projects/Recce
python3 -m pytest
```

Expect `126 passed, 2 xfailed`. The two xfails are deliberate — they pin known
limits so that if either is ever fixed, the test fails and forces the marker off.
One tracks a test-road artifact, the other the node-density information limit.

## Look at the engine's output

Everything else runs from `src/engine` (the modules use flat imports):

```
cd ~/Desktop/Projects/Recce/src/engine
```

**Synthetic answer-key road** — ground truth vs what the engine detected:

```
python3 run_demo.py
```

**Spiral stress road** — realistic transition curves, sustained minima, and a
genuinely opening corner:

```
python3 synth_stress.py
```

**A real road** — Tail of the Dragon, 34.8 km, 260 corners, fetched from OSM with
USGS 3DEP elevation:

```
python3 run_real.py ../../roads/tail-of-the-dragon.json
```

Note the data-quality report at the top. It refuses roads whose node spacing is
too coarse to trust, and suppresses crest warnings when the elevation profile
can't support them.

## Hear it

```
python3 make_audio.py --no-audio                       # schedule only, synthetic road
python3 make_audio.py -o ~/Desktop/ride.wav            # synthetic, listenable
python3 make_audio.py --road ../../roads/tail-of-the-dragon.json \
                      -o ~/Desktop/dragon.wav          # the real road, 26 min
python3 make_audio.py --mode guardian ...              # only what could hurt you
RECCE_VOICE=Serena python3 make_audio.py ...           # any macOS voice
```

Verbosity modes: `full`, `highlights`, `guardian`.

## Fetch a different road

```
python3 fetch_osm.py "<name>" <south,west,north,east> [--ref "<road number>"] [-o out.json]
```

Match by `--ref` for numbered highways, by name otherwise. Example:

```
python3 fetch_osm.py "Mulholland Highway" 34.05,-118.90,34.15,-118.60
```

Elevation comes from USGS 3DEP (US only, one request per point so it takes a few
minutes for a long road). Outside the US it falls back to Open-Elevation, whose
data fails the fitness gate — those roads will have no crest warnings.

## Validate against a real ride

**The rendered WAV is open-loop and will drift.** It assumes a modelled speed
profile; on the Dragon that's 80 km/h against a 48 km/h posted limit, which puts
you 40 s out of sync inside a minute. 3 s is one callout's worth of lead.

So don't ride to the track. Record first, then review:

1. Ride the road with any GPS logger running. Export a GPX.
2. Generate audio timed to how you **actually** rode:

```
python3 make_audio.py --road ../../roads/tail-of-the-dragon.json \
                      --gpx ~/Downloads/ride.gpx -o ~/Desktop/validated.wav
```

3. Listen at home. Judge each call: right severity? early enough? too much to
   absorb?

There's an `example-trace.gpx` in `roads/` to see the shape of the output.

If you do want a fixed track on the bike, match the pace and keep it short so
drift stays within a few seconds:

```
python3 make_audio.py --road ../../roads/tail-of-the-dragon.json \
                      --max-kmh 55 --from-km 8 --to-km 12 -o ~/Desktop/segment.wav
```

Live GPS-matched playback is the iOS app (Phase E). That's the only thing that
makes this a real copilot rather than a recording.

## What to tune

| What | Where |
| --- | --- |
| Radius → severity bands | `SEVERITY_BANDS` in `corners.py` — **the** thing to tune on a road you know |
| Callout lead time | `LEAD_SECONDS` in `timing.py` (3.0 s) |
| Merged utterance length | `MAX_LINK_CHAIN` in `timing.py` (2 corners) |
| Riding pace of the model | `A_LAT`, `V_MAX` in `speed.py` |
| tightens/opens sensitivity | `TIGHTEN_RATIO` in `corners.py` (0.72) |

Changing anything that affects severity or geometry means re-running the
`severity-bias-reviewer` agent. It returned BLOCKING twice on work that looked
correct and had a green test suite both times.

## Where things are

- `docs/` — product, architecture, MVP plan, tasks
- `memory/` — agent notes (symlink; also readable as an Obsidian vault via
  `START-HERE.md`)
- `src/engine/` — the pacenote engine
- `tests/` — answer key, bias invariants, decimated geometry, timing, traces
- `roads/` — a fetched real road and an example GPS trace

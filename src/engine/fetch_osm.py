"""Fetch real road geometry from OpenStreetMap and elevation from Open-Elevation.

Usage:
    python3 fetch_osm.py "Mulholland Highway" 34.05,-118.9,34.15,-118.6
    python3 fetch_osm.py "Tail of the Dragon" 35.44,-84.00,35.56,-83.88 --ref "US 129"

Outputs road.json: {"lon": [...], "lat": [...], "ele": [...]}
Then: python3 run_real.py road.json

Overpass needs the query FORM-ENCODED as data=... and a real User-Agent. Posting
the query as a text/plain body with urllib's default UA returns 406, which reads
like a network block and is not one — that mistake sat in this file as a "the
sandbox blocks overpass" comment and made Phase C look blocked for no reason.
"""
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from elevation import sample_elevation

OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OPEN_ELEVATION = "https://api.open-elevation.com/api/v1/lookup"
USGS_EPQS = "https://epqs.nationalmap.gov/v1/json"
UA = "Recce/0.1 (pacenote engine; road geometry research)"

# 3DEP returns a sentinel far outside any real elevation when a point falls
# outside coverage (it is a US-only dataset).
NO_DATA_BELOW = -1000.0


def _post(url, data, content_type, timeout=120):
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": content_type, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def overpass(query, attempts=2):
    """POST a query, trying each mirror in turn and then retrying the round.

    Overpass 504s and times out under load rather than because the query is
    wrong, so one failure is not a reason to give up. A wide bounding box makes
    it far likelier: CA 84 over a box reaching into Woodside is 167 ways and
    times out, while the twisty section alone is 16 ways and returns in ~30 s.
    Narrow the box before blaming the server.

    Errors go to stderr so a failed fetch is still visible when stdout is piped,
    and the exit status is non-zero — a run that reported success on a failed
    fetch is how a missing road file first surfaced.
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(attempts):
        for url in OVERPASS_MIRRORS:
            try:
                return _post(url, body, "application/x-www-form-urlencoded")
            except Exception as exc:  # noqa: BLE001 - report and try the next
                last = exc
                print(f"  {url.split('/')[2]}: {type(exc).__name__} {exc}",
                      file=sys.stderr)
    raise SystemExit(
        f"all Overpass mirrors failed after {attempts} rounds; last error: "
        f"{last}\nIf this is a 504 or a timeout, try a smaller bounding box.")


def fetch_road(name, bbox, ref=None):
    """bbox = (south, west, north, east). Matches by name= or ref= tag."""
    s, w, n, e = bbox
    selector = f'["ref"="{ref}"]' if ref else f'["name"="{name}"]'
    # `out geom` returns each way's coordinates inline. The obvious alternative,
    # `(._;>;); out body;`, recurses to every node and 504s on real bboxes.
    query = (f"[out:json][timeout:180];"
             f'way["highway"]{selector}({s},{w},{n},{e});'
             f"out geom;")
    data = overpass(query)

    ways = [el for el in data["elements"]
            if el["type"] == "way" and el.get("geometry")]
    if not ways:
        raise SystemExit("No ways found - check name/ref spelling and bbox.")

    # Stitch ways end-to-end (roads are split into many OSM ways). Each point
    # carries its way's structure tag, so bridge and tunnel spans survive the
    # reordering and reversing the stitch does.
    segments = []
    for wy in ways:
        tags = wy.get("tags", {})
        kind = "tunnel" if tags.get("tunnel") else (
            "bridge" if tags.get("bridge") else "")
        segments.append([(p["lon"], p["lat"], kind) for p in wy["geometry"]])
    # Join on POSITION only. Points now carry a structure tag, so comparing the
    # whole tuple would fail to join a bridge way to the ordinary way it meets —
    # same coordinates, different tag — and silently drop half the road.
    def at(p):
        return (p[0], p[1])

    def carry(point, incoming):
        """Adjacent ways SHARE their endpoint node, and the join drops one copy
        of it. Dropping the tagged copy shortens every structure by a node — on
        CA-84 that made all four bridges measure 0-9 m and the culvert filter
        then discarded the lot. Keep whichever copy carries a tag."""
        return point if point[2] else (point[0], point[1], incoming[2])

    chain = segments.pop(0)
    changed = True
    while segments and changed:
        changed = False
        for i, seg in enumerate(segments):
            if at(seg[0]) == at(chain[-1]):
                chain[-1] = carry(chain[-1], seg[0])
                chain += seg[1:]
            elif at(seg[-1]) == at(chain[-1]):
                chain[-1] = carry(chain[-1], seg[-1])
                chain += seg[-2::-1]
            elif at(seg[-1]) == at(chain[0]):
                chain[0] = carry(chain[0], seg[-1])
                chain = seg[:-1] + chain
            elif at(seg[0]) == at(chain[0]):
                chain[0] = carry(chain[0], seg[0])
                chain = seg[::-1][:-1] + chain
            else:
                continue
            segments.pop(i)
            changed = True
            break
    if segments:
        print(f"warning: {len(segments)} disconnected segments dropped "
              "(road may have gaps in this bbox)", file=sys.stderr)
    lon = [p[0] for p in chain]
    lat = [p[1] for p in chain]
    structure = [p[2] for p in chain]
    return lon, lat, structure


# Point features worth a callout on two wheels. Extend this table to add more —
# the fetch, snapping and callout path are all generic over it.
POINT_FEATURES = {
    "traffic_calming": {
        "bump": "bump", "hump": "bump", "table": "bump", "cushion": "bump",
    },
}


def fetch_point_features(bbox):
    """Speed bumps and similar point hazards inside the bbox.

    These are separate OSM NODES, not tags on the road way, so they need their
    own query and then snapping onto the road.
    """
    s, w, n, e = bbox
    clauses = "".join(
        f'node["{key}"]({s},{w},{n},{e});' for key in POINT_FEATURES)
    try:
        data = overpass(f"[out:json][timeout:120];({clauses});out;")
    except SystemExit as exc:
        print(f"point features unavailable: {exc}", file=sys.stderr)
        return []
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        for key, mapping in POINT_FEATURES.items():
            label = mapping.get(tags.get(key))
            if label:
                out.append({"lon": el["lon"], "lat": el["lat"], "type": label})
                break
    return out


def _epqs_point(lonlat, retries=2):
    lo, la = lonlat
    q = urllib.parse.urlencode({"x": lo, "y": la, "units": "Meters",
                                "wkid": 4326, "includeDate": "false"})
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(f"{USGS_EPQS}?{q}",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                v = float(json.load(resp)["value"])
            return v if v > NO_DATA_BELOW else None
        except Exception:  # noqa: BLE001 - transient; retry then give up
            continue
    return None


def fetch_elevation_3dep(lon, lat, workers=8):
    """USGS 3DEP elevation, one point per request but fetched concurrently.

    Preferred over Open-Elevation, which is unusable for crest detection.
    Measured on the same 40 points of the Tail of the Dragon:

        Open-Elevation  p95 |grade| 0.9%   max 425%   vertical res 1.000 m
        USGS 3DEP       p95 |grade| 7.2%   max 8.3%   vertical res 0.060 m

    Open-Elevation's integer-metre steps make most consecutive points read as
    dead flat and the rest as cliffs. 3DEP's profile is a real mountain road.

    One HTTP request per point is a poor API shape, but elevation is one-time
    preprocessing per route pack (the route-first architecture), so threading it
    is enough and avoids a GDAL/rasterio dependency. Returns None if too much of
    the road is outside coverage — 3DEP is US-only.
    """
    pts = list(zip(lon, lat))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        vals = list(pool.map(_epqs_point, pts))
    missing = sum(v is None for v in vals)
    if missing > 0.05 * len(vals):
        print(f"  3DEP: {missing}/{len(vals)} points outside coverage "
              f"— falling back")
        return None
    if missing:
        # interpolate the few gaps rather than discarding an otherwise good road
        print(f"  3DEP: interpolating {missing} missing point(s)")
        idx = [i for i, v in enumerate(vals) if v is not None]
        known = [vals[i] for i in idx]
        for i, v in enumerate(vals):
            if v is None:
                vals[i] = float(np.interp(i, idx, known))
    return [float(v) for v in vals]


def snap_points_to_road(lon, lat, points, max_off_m=25.0):
    """Attach point features to the nearest road node.

    The bbox query returns everything in the rectangle, including bumps on side
    streets, so anything further than `max_off_m` from this road is discarded —
    a speed-bump callout for a road you are not on is worse than none.
    """
    if not points:
        return []
    lat0 = np.radians(float(np.mean(lat)))
    rx = np.array(lon) * 111320.0 * np.cos(lat0)
    ry = np.array(lat) * 110540.0
    out = []
    for p in points:
        px = p["lon"] * 111320.0 * np.cos(lat0)
        py = p["lat"] * 110540.0
        d = np.hypot(rx - px, ry - py)
        i = int(np.argmin(d))
        if float(d[i]) <= max_off_m:
            out.append({"i": i, "type": p["type"]})
    return out


def fetch_elevation(lon, lat, batch=100):
    """Open-Elevation lookup (SRTM). For production, read SRTM tiles locally.

    Returns None if the service is unavailable. The pipeline handles missing
    elevation by emitting no crest warnings — which is a SILENT loss of a safety
    callout, so the caller must say so loudly rather than treating it as "no
    crests found".
    """
    ele = []
    for i in range(0, len(lon), batch):
        locs = [{"latitude": la, "longitude": lo}
                for lo, la in zip(lon[i:i + batch], lat[i:i + batch])]
        body = json.dumps({"locations": locs}).encode()
        try:
            out = _post(OPEN_ELEVATION, body, "application/json", timeout=90)
        except Exception as exc:  # noqa: BLE001
            print(f"  elevation unavailable ({type(exc).__name__}): {exc}")
            return None
        ele += [r["elevation"] for r in out["results"]]
        print(f"  elevation {min(i + batch, len(lon))}/{len(lon)}")
    return ele


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    name = sys.argv[1]
    bbox = tuple(float(v) for v in sys.argv[2].split(","))
    ref = None
    if "--ref" in sys.argv:
        ref = sys.argv[sys.argv.index("--ref") + 1]
    out_path = "road.json"
    if "-o" in sys.argv:
        out_path = sys.argv[sys.argv.index("-o") + 1]

    print(f"fetching '{ref or name}' from OSM...")
    lon, lat, structure = fetch_road(name, bbox, ref)
    spans = sum(1 for a, b in zip(structure, structure[1:]) if a != b and b)
    print(f"  {len(lon)} points, {spans} bridge/tunnel span(s)")

    print("fetching point features (speed bumps)...")
    points = fetch_point_features(bbox)
    snapped = snap_points_to_road(lon, lat, points)
    print(f"  {len(snapped)} on this road (of {len(points)} in the box)")

    # Raster first: 1426 nodes/sec against 4.7 for the point API, same source,
    # and it agrees to a median of 0.25 m. The point API remains as a fallback
    # for when a tile cannot be reached.
    print(f"sampling elevation from 3DEP rasters ({len(lon)} points)...")
    ele = sample_elevation(lon, lat)
    if ele is None:
        print("raster unavailable; falling back to 3DEP point queries "
              "(slow: minutes, not seconds)")
        ele = fetch_elevation_3dep(lon, lat)
    if ele is None:
        print("falling back to Open-Elevation (crest detection will likely be "
              "suppressed — see docs/ARCHITECTURE.md)")
        ele = fetch_elevation(lon, lat)
    if ele is None:
        print("\n*** NO ELEVATION: crest warnings will be absent from this road.")
        print("*** That is a missing safety callout, not an absence of crests.\n")
    with open(out_path, "w") as f:
        json.dump({"name": name, "lon": lon, "lat": lat, "ele": ele,
                   "structure": structure, "points": snapped}, f)
    print(f"wrote {out_path} - now run: python3 run_real.py {out_path}")

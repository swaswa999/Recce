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

OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OPEN_ELEVATION = "https://api.open-elevation.com/api/v1/lookup"
UA = "Recce/0.1 (pacenote engine; road geometry research)"


def _post(url, data, content_type, timeout=120):
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": content_type, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def overpass(query):
    """POST a query, trying mirrors in turn. Overpass rate-limits and 504s under
    load, so a single failure is not a reason to give up."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in OVERPASS_MIRRORS:
        try:
            return _post(url, body, "application/x-www-form-urlencoded")
        except Exception as exc:  # noqa: BLE001 - report and try the next mirror
            last = exc
            print(f"  {url.split('/')[2]}: {type(exc).__name__} {exc}")
    raise SystemExit(f"all Overpass mirrors failed; last error: {last}")


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

    # Stitch ways end-to-end (roads are split into many OSM ways).
    segments = [[(p["lon"], p["lat"]) for p in wy["geometry"]] for wy in ways]
    chain = segments.pop(0)
    changed = True
    while segments and changed:
        changed = False
        for i, seg in enumerate(segments):
            if seg[0] == chain[-1]:
                chain += seg[1:]
            elif seg[-1] == chain[-1]:
                chain += seg[-2::-1]
            elif seg[-1] == chain[0]:
                chain = seg[:-1] + chain
            elif seg[0] == chain[0]:
                chain = seg[::-1][:-1] + chain
            else:
                continue
            segments.pop(i)
            changed = True
            break
    if segments:
        print(f"warning: {len(segments)} disconnected segments dropped "
              "(road may have gaps in this bbox)")
    lon = [p[0] for p in chain]
    lat = [p[1] for p in chain]
    return lon, lat


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
    lon, lat = fetch_road(name, bbox, ref)
    print(f"  {len(lon)} points")
    print("fetching elevation...")
    ele = fetch_elevation(lon, lat)
    if ele is None:
        print("\n*** NO ELEVATION: crest warnings will be absent from this road.")
        print("*** That is a missing safety callout, not an absence of crests.\n")
    with open(out_path, "w") as f:
        json.dump({"name": name, "lon": lon, "lat": lat, "ele": ele}, f)
    print(f"wrote {out_path} - now run: python3 run_real.py {out_path}")

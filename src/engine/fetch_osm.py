"""Fetch real road geometry from OpenStreetMap and elevation from Open-Elevation.

Run this on your own machine (this sandbox blocks overpass-api.de).

Usage:
    python fetch_osm.py "Mulholland Highway" 34.05,-118.9,34.15,-118.6
    python fetch_osm.py "Tail of the Dragon" 35.45,-83.95,35.55,-83.90 --ref US-129

Outputs road.json: {"lon": [...], "lat": [...], "ele": [...]}
Then: python run_real.py road.json
"""
import json
import sys
import urllib.request

OVERPASS = "https://overpass-api.de/api/interpreter"
OPEN_ELEVATION = "https://api.open-elevation.com/api/v1/lookup"


def fetch_road(name, bbox, ref=None):
    """bbox = (south, west, north, east). Matches by name= or ref= tag."""
    s, w, n, e = bbox
    selector = f'["ref"="{ref}"]' if ref else f'["name"="{name}"]'
    query = f"""
    [out:json][timeout:60];
    way["highway"]{selector}({s},{w},{n},{e});
    (._;>;);
    out body;
    """
    req = urllib.request.Request(OVERPASS, data=query.encode(),
                                 headers={"Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.load(resp)

    nodes = {el["id"]: (el["lon"], el["lat"])
             for el in data["elements"] if el["type"] == "node"}
    ways = [el for el in data["elements"] if el["type"] == "way"]
    if not ways:
        raise SystemExit("No ways found - check name/ref spelling and bbox.")

    # Stitch ways end-to-end (roads are split into many OSM ways).
    segments = [[nodes[nid] for nid in wy["nodes"]] for wy in ways]
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
    """Open-Elevation lookup (SRTM). For production, read SRTM tiles locally."""
    ele = []
    for i in range(0, len(lon), batch):
        locs = [{"latitude": la, "longitude": lo}
                for lo, la in zip(lon[i:i + batch], lat[i:i + batch])]
        body = json.dumps({"locations": locs}).encode()
        req = urllib.request.Request(OPEN_ELEVATION, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            out = json.load(resp)
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
    print(f"fetching '{ref or name}' from OSM...")
    lon, lat = fetch_road(name, bbox, ref)
    print(f"  {len(lon)} points")
    print("fetching elevation...")
    ele = fetch_elevation(lon, lat)
    with open("road.json", "w") as f:
        json.dump({"name": name, "lon": lon, "lat": lat, "ele": ele}, f)
    print("wrote road.json - now run: python run_real.py road.json")

"""Elevation from 3DEP raster tiles instead of one HTTP request per node.

The point-query API is 4.7 nodes/sec at 8 concurrent. That is 6.5 minutes for a
30 km road, 88 hours for California's state highways, and it hammers a public
USGS endpoint that would rate-limit long before finishing. It is the single
thing that made statewide preprocessing impossible.

This reads the 3DEP 1/3 arc-second COGs instead: open the tile, read the one
window covering the road, interpolate every node locally. Same data, same
source, no per-node round trip.

Bilinear rather than nearest-neighbour, because at ~10 m post spacing on a steep
hillside the nearest post can be several metres off vertically, and crest
detection is called from a grade CHANGE of 0.05 — the same order as that error.

3DEP is US-only. Elsewhere this returns None and the caller falls back, which
means no crest callouts — see docs/ARCHITECTURE.md, "The information limit".
"""
import os

import numpy as np

# Anonymous S3 read, and don't list the bucket directory just to open one file.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

TILE_URL = ("/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation"
            "/13/TIFF/current/{tile}/USGS_13_{tile}.tif")

# 3DEP marks voids with a large negative sentinel rather than NaN.
NO_DATA_BELOW = -1e4


def tile_name(lon, lat):
    """3DEP tiles are 1x1 degree, named by their NORTH-WEST corner."""
    return f"n{int(np.ceil(lat)):02d}w{abs(int(np.floor(lon))):03d}"


def tiles_for(lon, lat):
    names = {tile_name(lo, la) for lo, la in zip(lon, lat)}
    return sorted(names)


def _sample_tile(name, lon, lat, mask, out, cache_dir=None):
    """Bilinear-sample the points selected by `mask` from one tile."""
    import rasterio

    src = TILE_URL.format(tile=name)
    if cache_dir:
        local = os.path.join(cache_dir, f"USGS_13_{name}.tif")
        if os.path.exists(local):
            src = local

    with rasterio.open(src) as ds:
        inv = ~ds.transform
        # Fractional pixel coordinates of every wanted point.
        cols, rows = [], []
        for lo, la in zip(lon[mask], lat[mask]):
            c, r = inv * (lo, la)
            cols.append(c - 0.5)   # transform gives pixel EDGE; centres are -0.5
            rows.append(r - 0.5)
        cols = np.asarray(cols)
        rows = np.asarray(rows)

        r0 = int(np.floor(rows.min())) - 1
        c0 = int(np.floor(cols.min())) - 1
        r1 = int(np.ceil(rows.max())) + 2
        c1 = int(np.ceil(cols.max())) + 2
        r0, c0 = max(r0, 0), max(c0, 0)
        r1, c1 = min(r1, ds.height), min(c1, ds.width)
        if r1 <= r0 or c1 <= c0:
            return

        window = ((r0, r1), (c0, c1))
        band = ds.read(1, window=window).astype(float)
        band[band < NO_DATA_BELOW] = np.nan

        rr = np.clip(rows - r0, 0, band.shape[0] - 1.001)
        cc = np.clip(cols - c0, 0, band.shape[1] - 1.001)
        ri, ci = np.floor(rr).astype(int), np.floor(cc).astype(int)
        fr, fc = rr - ri, cc - ci

        v = ((1 - fr) * (1 - fc) * band[ri, ci]
             + (1 - fr) * fc * band[ri, ci + 1]
             + fr * (1 - fc) * band[ri + 1, ci]
             + fr * fc * band[ri + 1, ci + 1])
        out[np.where(mask)[0]] = v


def sample_elevation(lon, lat, cache_dir=None, verbose=True):
    """Elevation in metres for each point, or None if no tile could be read.

    Points are grouped by tile so each tile is opened once. A road crossing a
    tile boundary is handled; a road outside 3DEP coverage returns None rather
    than silently producing zeros.
    """
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    out = np.full(len(lon), np.nan)

    names = tiles_for(lon, lat)
    if verbose:
        print(f"  3DEP tiles needed: {', '.join(names)}")

    for name in names:
        mask = np.array([tile_name(lo, la) == name
                         for lo, la in zip(lon, lat)])
        try:
            _sample_tile(name, lon, lat, mask, out, cache_dir=cache_dir)
        except Exception as exc:  # noqa: BLE001 - a missing tile is normal
            if verbose:
                print(f"  tile {name} unavailable: {type(exc).__name__} {exc}")

    good = np.isfinite(out)
    if good.sum() == 0:
        return None
    if good.sum() < len(out):
        # A few voids are worth interpolating; a mostly-empty road is not.
        if good.sum() < 0.95 * len(out):
            if verbose:
                print(f"  only {good.sum()}/{len(out)} points covered — "
                      f"treating as no elevation")
            return None
        idx = np.where(good)[0]
        out = np.interp(np.arange(len(out)), idx, out[idx])
        if verbose:
            print(f"  interpolated {len(out) - len(idx)} void point(s)")
    return [float(v) for v in out]

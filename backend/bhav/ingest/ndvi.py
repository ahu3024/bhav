"""Sentinel-2 NDVI history for the Nashik onion belt, via Google Earth Engine.

Roadmap §pre-hackathon: export 10-day NDVI composites to
`data/raw/ndvi_nashik.csv` **before** the event, then never call GEE live —
everything downstream reads the CSV / the sqlite `ndvi` table.

What comes back per composite:

    value       clear-pixel mean NDVI over the AOI  — how green the belt is
    pct_mature  share of clear pixels below NDVI_MATURITY_THRESHOLD — the
                "% area past maturity" the roadmap asks for, i.e. how much of
                the crop has dried down and is close to hitting the mandi
    clear_frac  how much of the AOI the composite actually saw
    obs_date    the last real satellite pass inside the window

Compositing happens in pandas rather than in Earth Engine on purpose: 10-day
windows are routinely empty over the monsoon, and an empty window has to stay
empty (carried as observation age) instead of silently becoming a zero-band
image. Auth (one time on the machine that runs this):

    earthengine authenticate      # or set EE_PROJECT + a service-account key
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import (
    DISTRICT,
    NDVI_AOI,
    NDVI_COMPOSITE_DAYS,
    NDVI_MATURITY_THRESHOLD,
    NDVI_MAX_CLOUD_PCT,
    NDVI_MIN_CLEAR_FRAC,
    NDVI_SCALE_M,
    NDVI_START,
    RAW_DIR,
)

OUT_CSV = RAW_DIR / "ndvi_nashik.csv"
COLUMNS = ["district", "date", "value", "pct_mature", "clear_frac", "obs_date", "n_obs"]

# Sentinel-2 scene-classification codes worth keeping: 4 vegetation,
# 5 not-vegetated (bare soil — a harvested onion field is exactly this),
# 7 unclassified. Everything else is cloud, shadow, water, snow or saturation.
_CLEAR_SCL = [4, 5, 7]


def _init_ee():
    """Initialise Earth Engine, preferring EE_PROJECT from the environment."""
    import ee

    project = os.getenv("EE_PROJECT") or None
    try:
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project)
    return ee


def _scene_stats(ee, aoi):
    """Build the per-scene reducer: mean NDVI, % past maturity, clear coverage."""

    def stats(img):
        clear = img.select("SCL").remap(_CLEAR_SCL, [1] * len(_CLEAR_SCL), 0)
        ndvi = img.normalizedDifference(["B8", "B4"]).rename("ndvi").updateMask(clear)
        mature = ndvi.lt(NDVI_MATURITY_THRESHOLD).rename("mature")
        agg = ndvi.addBands(mature).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi,
            scale=NDVI_SCALE_M, maxPixels=1e9, bestEffort=True,
        )
        cover = clear.rename("clear").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi,
            scale=NDVI_SCALE_M, maxPixels=1e9, bestEffort=True,
        )
        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "ndvi": agg.get("ndvi"),
            "pct_mature": agg.get("mature"),
            "clear_frac": cover.get("clear"),
        })

    return stats


def fetch_scenes(start: str = NDVI_START, end: str | None = None) -> pd.DataFrame:
    """One row per Sentinel-2 scene. Pulled a year at a time so a slow or
    failed chunk doesn't cost the whole decade."""
    ee = _init_ee()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.utcnow().normalize().tz_localize(None)

    aoi = ee.Geometry.Rectangle([
        NDVI_AOI["min_lon"], NDVI_AOI["min_lat"],
        NDVI_AOI["max_lon"], NDVI_AOI["max_lat"],
    ])
    reducer = _scene_stats(ee, aoi)

    frames = []
    for chunk_start in pd.date_range(start_ts, end_ts, freq="YS", inclusive="both").union(
        pd.DatetimeIndex([start_ts])
    ):
        chunk_end = min(chunk_start + pd.offsets.YearBegin(1), end_ts)
        if chunk_end <= chunk_start:
            continue
        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filterDate(chunk_start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d"))
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", NDVI_MAX_CLOUD_PCT))
        )
        rows = (
            col.map(reducer)
            .filter(ee.Filter.notNull(["ndvi", "clear_frac"]))
            .reduceColumns(ee.Reducer.toList(4),
                           ["date", "ndvi", "pct_mature", "clear_frac"])
            .get("list")
            .getInfo()
        )
        print(f"  {chunk_start.date()} .. {chunk_end.date()}: {len(rows)} scenes")
        if rows:
            frames.append(pd.DataFrame(
                rows, columns=["date", "ndvi", "pct_mature", "clear_frac"]))

    if not frames:
        raise RuntimeError("Earth Engine returned no Sentinel-2 scenes for the AOI")

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def to_composites(scenes: pd.DataFrame) -> pd.DataFrame:
    """Collapse scenes into NDVI_COMPOSITE_DAYS windows.

    The AOI straddles two Sentinel-2 tiles, so a single date usually yields two
    partial scenes. Averaging them weighted by clear coverage stops a mostly-
    clouded sliver from dragging the belt mean around.
    """
    if scenes.empty:
        return pd.DataFrame(columns=COLUMNS)

    df = scenes.dropna(subset=["ndvi", "clear_frac"]).copy()
    df = df[df["clear_frac"] > 0]

    period = f"{NDVI_COMPOSITE_DAYS}D"
    grouped = df.set_index("date").groupby(pd.Grouper(freq=period))

    out = grouped.apply(
        lambda g: pd.Series({
            "value": _wmean(g["ndvi"], g["clear_frac"]),
            "pct_mature": _wmean(g["pct_mature"], g["clear_frac"]),
            "clear_frac": g["clear_frac"].mean(),
            "obs_date": g.index.max(),
            "n_obs": len(g),
        }),
        include_groups=False,
    )
    out = out.dropna(subset=["value"])
    # A composite that saw almost nothing is worse than no composite: drop it
    # and let observation age carry the gap.
    out = out[out["clear_frac"] >= NDVI_MIN_CLEAR_FRAC]

    out = out.reset_index().rename(columns={"date": "date"})
    out["obs_date"] = pd.to_datetime(out["obs_date"]).dt.strftime("%Y-%m-%d")
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["n_obs"] = out["n_obs"].astype(int)
    out.insert(0, "district", DISTRICT)
    return out[COLUMNS]


def _wmean(values: pd.Series, weights: pd.Series) -> float:
    ok = values.notna() & weights.notna() & (weights > 0)
    if not ok.any():
        return float("nan")
    return float((values[ok] * weights[ok]).sum() / weights[ok].sum())


def fetch(start: str = NDVI_START, end: str | None = None) -> pd.DataFrame:
    """Scenes -> 10-day composites, ready for the `ndvi` table."""
    return to_composites(fetch_scenes(start, end))


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    span = f"{df['date'].min()} .. {df['date'].max()}" if len(df) else "empty"
    print(f"NDVI: {len(df)} composites ({span}) -> {OUT_CSV}")


if __name__ == "__main__":
    main()

"""Cash-need branch (roadmap §1.6): nearest WDRA-registered warehouse for a
receipt-based loan instead of a distress sale, plus a partial-sell heuristic.

Static table is fine for the hackathon — these are real WDRA-registered / NABARD
onion storage points in the Nashik belt (verify before demo day)."""

from __future__ import annotations

import math

from .config import DISTRICT, LAT, LON
from .db import cursor, read_df

_WAREHOUSES = [
    # name, district, lat, lon, capacity (tonnes)
    ("Lasalgaon APMC Warehouse", "Nashik", 20.1436, 74.2385, 5000),
    ("Pimpalgaon Baswant Storage", "Nashik", 20.1747, 74.0975, 3500),
    ("Nashik Central Warehouse (CWC)", "Nashik", 19.9975, 73.7898, 8000),
    ("Yeola Cooperative Godown", "Nashik", 20.0419, 74.4894, 2500),
    ("Chandwad Onion Storage Cluster", "Nashik", 20.3316, 74.2447, 2000),
    ("Deola Farmer Producer Warehouse", "Nashik", 20.5560, 74.0170, 1800),
    ("Manmad Rail-head Warehouse", "Nashik", 20.2510, 74.4380, 4200),
]


def seed_warehouses() -> None:
    with cursor() as cur:
        cur.executemany(
            "INSERT OR REPLACE INTO warehouses (name, district, lat, lon, "
            "capacity) VALUES (?,?,?,?,?)",
            _WAREHOUSES,
        )


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest(lat: float = LAT, lon: float = LON, limit: int = 3) -> list[dict]:
    df = read_df("SELECT * FROM warehouses WHERE district = ?", (DISTRICT,))
    if df.empty:
        seed_warehouses()
        df = read_df("SELECT * FROM warehouses WHERE district = ?", (DISTRICT,))
    df["distance_km"] = df.apply(
        lambda r: round(_haversine_km(lat, lon, r["lat"], r["lon"]), 1), axis=1
    )
    return df.sort_values("distance_km").head(limit).to_dict("records")


def partial_sell(cash_need_rupees: float, total_quintals: float,
                 price_per_quintal: float) -> dict:
    """Sell just enough to cover the stated cash need, store the rest against a
    warehouse receipt."""
    if price_per_quintal <= 0:
        raise ValueError("price_per_quintal must be positive")
    need_qtl = math.ceil(cash_need_rupees / price_per_quintal)
    sell_qtl = min(need_qtl, total_quintals)
    store_qtl = max(total_quintals - sell_qtl, 0)
    return {
        "cash_need_rupees": cash_need_rupees,
        "sell_quintals": sell_qtl,
        "store_quintals": round(store_qtl, 2),
        "cash_raised_now": round(sell_qtl * price_per_quintal, 0),
        "store_value_at_today_price": round(store_qtl * price_per_quintal, 0),
        "nearest_warehouses": nearest(),
    }

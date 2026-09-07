"""Registration store (roadmap MUST: "registration capturing phone + crop +
usual sell window").

Deliberately no auth and no OTP — the roadmap cuts both. What is kept is the
part that matters for delivery: one row per phone, an explicit opt-out, and a
log of every send attempt so a failed delivery is visible rather than silent.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .config import CROP, DISTRICT
from .db import cursor, init_db, read_df
from .message import LANGS, normalise_phone, valid_phone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def register(phone: str, name: str | None = None, crop: str = CROP,
             village_pin: str | None = None, lang: str = "en",
             sell_window: str | None = None,
             channel: str = "whatsapp") -> dict:
    """Add or update a subscriber. Re-registering reactivates and updates."""
    phone = normalise_phone(phone)
    if not valid_phone(phone):
        raise ValueError(f"'{phone}' is not a usable phone number")
    lang = lang if lang in LANGS else "en"

    init_db()
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO subscribers (phone, name, crop, district, village_pin,
                                     lang, sell_window, channel, active,
                                     created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                name        = COALESCE(excluded.name, subscribers.name),
                crop        = excluded.crop,
                village_pin = COALESCE(excluded.village_pin,
                                       subscribers.village_pin),
                lang        = excluded.lang,
                sell_window = COALESCE(excluded.sell_window,
                                       subscribers.sell_window),
                channel     = excluded.channel,
                active      = 1,
                updated_at  = excluded.updated_at
            """,
            (phone, name, crop, DISTRICT, village_pin, lang, sell_window,
             channel, _now(), _now()),
        )
    return get(phone)


def unsubscribe(phone: str) -> dict:
    """Soft opt-out — the row stays so a re-register keeps its history."""
    phone = normalise_phone(phone)
    init_db()
    with cursor() as cur:
        cur.execute(
            "UPDATE subscribers SET active = 0, updated_at = ? WHERE phone = ?",
            (_now(), phone),
        )
    return get(phone) or {"phone": phone, "active": 0}


def get(phone: str) -> dict | None:
    init_db()
    phone = normalise_phone(phone)
    df = read_df("SELECT * FROM subscribers WHERE phone = ?", (phone,))
    return None if df.empty else df.iloc[0].to_dict()


def active_subscribers() -> pd.DataFrame:
    init_db()
    return read_df(
        "SELECT * FROM subscribers WHERE active = 1 ORDER BY created_at")


def summary() -> dict:
    # Read paths init too: a fresh database has no subscriber tables until
    # someone registers, and "no one has signed up yet" should read as zero
    # rather than as a 500.
    init_db()
    df = read_df("SELECT lang, channel, active FROM subscribers")
    if df.empty:
        return {"total": 0, "active": 0, "by_lang": {}, "by_channel": {}}
    live = df[df["active"] == 1]
    return {
        "total": int(len(df)),
        "active": int(len(live)),
        "by_lang": live["lang"].value_counts().to_dict(),
        "by_channel": live["channel"].value_counts().to_dict(),
    }


def log_send(phone: str, alert_date: str, lang: str, result: dict,
             body: str) -> None:
    init_db()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO message_log (phone, alert_date, lang, channel, sent,
                                        provider_sid, error, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (normalise_phone(phone), alert_date, lang,
             result.get("channel"), int(bool(result.get("sent"))),
             result.get("sid"), result.get("reason"), body, _now()),
        )


def recent_log(limit: int = 50) -> pd.DataFrame:
    init_db()
    return read_df(
        "SELECT phone, alert_date, lang, channel, sent, provider_sid, error, "
        "created_at FROM message_log ORDER BY id DESC LIMIT ?", (limit,))

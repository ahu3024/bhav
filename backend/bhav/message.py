"""Delivery layer (roadmap §1.5): build the WhatsApp/SMS message body.

Real send via Twilio is optional and only fires if creds are set; otherwise the
API just returns the text for the chat-bubble UI fallback.
"""

from __future__ import annotations

import os

from .alert_engine import Alert

_EMOJI = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢"}

_TEMPLATES = {
    "en": (
        "{emoji} Bhav — {market} {crop}\n"
        "{label}. Best window: {w1} to {w2}.\n"
        "Expected: {impact:+,.0f} Rs/quintal vs selling today.\n"
        "Why: {reason}\n"
        "Confidence {confidence}%."
    ),
    "mr": (
        "{emoji} भाव — {market} {crop}\n"
        "{label_mr}. योग्य कालावधी: {w1} ते {w2}.\n"
        "अपेक्षित: {impact:+,.0f} रु/क्विंटल (आज विकण्यापेक्षा).\n"
        "कारण: {reason}\n"
        "विश्वास {confidence}%."
    ),
}

_LABEL_MR = {"Sell now": "आत्ता विका", "Caution": "सावध रहा", "Wait": "थांबा"}


def build_message(alert: Alert, crop: str = "Onion", market: str = "Lasalgaon",
                  lang: str = "en") -> str:
    tpl = _TEMPLATES.get(lang, _TEMPLATES["en"])
    return tpl.format(
        emoji=_EMOJI[alert.color],
        market=market,
        crop=crop,
        label=alert.label,
        label_mr=_LABEL_MR.get(alert.label, alert.label),
        w1=alert.window_start,
        w2=alert.window_end,
        impact=alert.expected_impact,
        reason=alert.reason,
        confidence=alert.confidence,
    )


def send_whatsapp(to: str, body: str) -> dict:
    """Send via Twilio if configured. Returns a status dict either way."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_ = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. 'whatsapp:+14155238886'
    if not (sid and token and from_):
        return {"sent": False, "reason": "twilio_not_configured", "preview": body}
    try:
        from twilio.rest import Client

        msg = Client(sid, token).messages.create(
            from_=from_, to=f"whatsapp:{to}", body=body
        )
        return {"sent": True, "sid": msg.sid, "preview": body}
    except Exception as exc:  # pragma: no cover - network
        return {"sent": False, "reason": str(exc), "preview": body}

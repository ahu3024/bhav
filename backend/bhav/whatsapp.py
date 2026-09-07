"""WhatsApp delivery over open-wa (https://open-wa.org).

open-wa drives a *real* WhatsApp account through WhatsApp Web. That choice is
the whole point: Meta's Cloud API only lets you send free-form text within 24
hours of the recipient's last inbound message, and outside that window nothing
goes but a pre-approved template. A weekly sell/wait alert to farmers who have
never messaged us is exactly the case that rule forbids. Through open-wa there
is no window and no template — the trade is that a phone must link the session
once by scanning a QR, and the account is a real one that Meta could ban if it
is used to spam.

open-wa is a Node library, so it runs as a small bridge process next to this
API (see `whatsapp/server.js`); everything here is an HTTP call to it.

Configuration (.env):

    WA_BRIDGE_URL     default http://localhost:3001
    WA_BRIDGE_TOKEN   shared secret, must match the bridge's
"""

from __future__ import annotations

import os

import requests

from .message import normalise_phone, valid_phone

DEFAULT_URL = "http://localhost:3001"
REQUEST_TIMEOUT = 45          # a cold WhatsApp Web send is not fast


def _base() -> str:
    return os.getenv("WA_BRIDGE_URL", DEFAULT_URL).rstrip("/")


def _headers() -> dict:
    token = os.getenv("WA_BRIDGE_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _err(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "bridge_unreachable"
    return str(exc)


def whatsapp_status() -> dict:
    """What delivery is possible right now. Sends nothing."""
    try:
        r = requests.get(f"{_base()}/health", timeout=10)
        r.raise_for_status()
        h = r.json()
    except Exception as exc:
        return {
            "provider": "open-wa",
            "configured": False,
            "bridge_url": _base(),
            "session_status": "unreachable",
            "linked_number": None,
            "qr_available": False,
            "whatsapp_ready": False,
            "reason": _err(exc),
        }

    return {
        "provider": "open-wa",
        "configured": True,
        "bridge_url": _base(),
        "session_status": h.get("status"),
        "linked_number": h.get("me"),
        "qr_available": bool(h.get("qr_available")),
        "whatsapp_ready": bool(h.get("connected")),
        "sent": h.get("sent"),
        "failed": h.get("failed"),
        "reason": h.get("error"),
    }


def verify_credentials() -> dict:
    """Read-only check that the session is actually linked and can send."""
    status = whatsapp_status()
    if not status["configured"]:
        return {"ok": False, "reason": status.get("reason", "bridge_unreachable")}
    if not status["whatsapp_ready"]:
        return {
            "ok": False,
            "reason": f"session_{status.get('session_status')}",
            "qr_available": status["qr_available"],
        }
    return {"ok": True, "display_phone_number": status["linked_number"]}


def qr_png() -> bytes | None:
    """The pairing QR, while the session is still unlinked."""
    try:
        r = requests.get(f"{_base()}/qr", headers=_headers(), timeout=10)
        return r.content if r.status_code == 200 else None
    except Exception:
        return None


def check_number(phone: str) -> dict:
    """Is this number actually reachable on WhatsApp?"""
    try:
        r = requests.post(f"{_base()}/check", json={"to": normalise_phone(phone)},
                          headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"on_whatsapp": None, "reason": _err(exc)}


def send_text(to: str, body: str) -> dict:
    """Send one message. No 24-hour window, no template — that's the point."""
    phone = normalise_phone(to)
    if not valid_phone(phone):
        return {"sent": False, "channel": "whatsapp", "to": phone,
                "reason": f"'{to}' is not a usable phone number", "preview": body}
    try:
        r = requests.post(f"{_base()}/send", json={"to": phone, "body": body},
                          headers=_headers(), timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        reason = _err(exc)
        return {"sent": False, "channel": "whatsapp", "to": phone,
                "reason": reason, "hint": explain_error(reason), "preview": body}

    if r.status_code == 200:
        data = r.json()
        return {"sent": True, "channel": "whatsapp", "kind": "text",
                "sid": data.get("id"), "to": phone, "preview": body}

    try:
        payload = r.json()
        reason = payload.get("error") or payload.get("hint") or r.text[:300]
    except Exception:
        reason = r.text[:300]
    return {"sent": False, "channel": "whatsapp", "kind": "text", "to": phone,
            "reason": reason, "hint": explain_error(reason), "preview": body}


def send_alert(to: str, body: str, channel: str = "whatsapp") -> dict:
    """Kept as the one entry point the API and broadcast script call."""
    return send_text(to, body)


def explain_error(reason: str | None) -> str | None:
    """Turn a failure into the thing you actually have to go and do."""
    if not reason:
        return None
    text = str(reason).lower()
    if "bridge_unreachable" in text or "connection" in text:
        return ("The open-wa bridge is not running. Start it with "
                "`npm start` in whatsapp/ (it listens on :3001).")
    if "not linked" in text or "session_qr" in text or "session_starting" in text:
        return ("The WhatsApp session is not linked. Run `npm run link` in "
                "whatsapp/ and scan the QR from the sending phone: WhatsApp → "
                "Settings → Linked devices → Link a device.")
    if "detached frame" in text or "execution context" in text or "target closed" in text:
        return ("WhatsApp Web reloaded under the bridge, so that send hit a dead "
                "browser page. The bridge relinks itself from the saved session "
                "— nothing to scan — so just send it again in a few seconds.")
    if "not a contact" in text:
        return ("Unlicensed open-wa only messages numbers already saved as "
                "contacts on the linked phone. Save the number as a contact "
                "there, or buy a licence at https://get.openwa.dev — this is "
                "an open-wa restriction, not a WhatsApp one.")
    if "401" in text or "bearer" in text:
        return "WA_BRIDGE_TOKEN in backend/.env does not match the bridge's."
    if "not a usable phone" in text:
        return "Use a 10-digit Indian mobile or a full +<country><number>."
    return None

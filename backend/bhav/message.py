"""Delivery layer — WhatsApp body + Meta WhatsApp Cloud API send.

Three languages (English, Hindi, Marathi) and four lines, because the message is
read on a cheap phone in a mandi, not on a dashboard. The order is fixed: what
to do, by when, what it is worth, and why — a farmer who reads only the first
line should still have the decision.

Sending goes straight to Meta's Graph API, no reseller in between:

    POST https://graph.facebook.com/{version}/{phone_number_id}/messages

Meta's 24-hour rule is the thing to design around. A free-form `text` message is
only allowed within 24 hours of the recipient's last inbound message; outside
that window only a **pre-approved template** is accepted. So `send_whatsapp`
tries text first and falls back to a template automatically when Meta rejects
the free-form send for that reason — which is the difference between a broadcast
that works on a Monday morning and one that silently reaches nobody.

Configuration (.env):

    WHATSAPP_ACCESS_TOKEN      required — a System User token, not a 24h dev one
    WHATSAPP_PHONE_NUMBER_ID   required — the *ID*, not the phone number
    WHATSAPP_TEMPLATE_NAME     optional — used outside the 24h window
    WHATSAPP_TEMPLATE_LANG     optional — defaults to en
    WHATSAPP_API_VERSION       optional — defaults to v21.0
"""

from __future__ import annotations

import os
import re

import requests

from .alert_engine import Alert

LANGS = ("en", "hi", "mr")

GRAPH_BASE = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v21.0"
REQUEST_TIMEOUT = 30

_EMOJI = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢"}

# Four lines: action · window · money · reason.
_TEMPLATES = {
    "en": (
        "{emoji} *Bhav* · {market} {crop} · {date}\n"
        "*{label}* — window {w1} to {w2}\n"
        "Impact: {impact} vs holding · {confidence}% confident\n"
        "Why: {reason}"
    ),
    "hi": (
        "{emoji} *भाव* · {market} {crop} · {date}\n"
        "*{label}* — अवधि {w1} से {w2}\n"
        "असर: {impact} रोकने की तुलना में · {confidence}% भरोसा\n"
        "कारण: {reason}"
    ),
    "mr": (
        "{emoji} *भाव* · {market} {crop} · {date}\n"
        "*{label}* — कालावधी {w1} ते {w2}\n"
        "परिणाम: {impact} थांबण्याच्या तुलनेत · {confidence}% खात्री\n"
        "कारण: {reason}"
    ),
}

_LABELS = {
    "Sell now": {"hi": "अभी बेचें", "mr": "आत्ता विका"},
    "Caution": {"hi": "सावधान", "mr": "सावध रहा"},
    "Wait": {"hi": "रुकें", "mr": "थांबा"},
}

_CROPS = {"Onion": {"hi": "प्याज", "mr": "कांदा"}}

_MARKETS = {
    "Lasalgaon": {"hi": "लासलगांव", "mr": "लासलगाव"},
    "Pimpalgaon Baswant": {"hi": "पिंपळगांव", "mr": "पिंपळगाव"},
    "Nashik": {"hi": "नासिक", "mr": "नाशिक"},
    "Yeola": {"hi": "येवला", "mr": "येवला"},
}

# Keyed on the English phrase scoring.py produces, so this stays a pure
# translation table — adding a feature there needs no change here, it just
# falls through to English until someone translates it.
_PHRASE_I18N = {
    "price level elevated in real terms": {
        "hi": "भाव पहले से ऊँचा", "mr": "भाव आधीच चढा"},
    "price level low in real terms": {
        "hi": "भाव नीचा", "mr": "भाव खाली"},
    "price well above its yearly median": {
        "hi": "भाव साल के औसत से काफी ऊपर",
        "mr": "भाव वर्षाच्या सरासरीपेक्षा बराच वर"},
    "price below its yearly median": {
        "hi": "भाव साल के औसत से नीचे", "mr": "भाव वर्षाच्या सरासरीपेक्षा खाली"},
    "month-long price rally — stretched": {
        "hi": "महीने भर की तेजी — अब खिंची हुई",
        "mr": "महिनाभराची तेजी — आता ताणलेली"},
    "month-long price slide": {
        "hi": "महीने भर से भाव गिर रहा", "mr": "महिनाभर भाव घसरत आहे"},
    "2-week price momentum up": {
        "hi": "दो हफ्ते से भाव चढ़ रहा", "mr": "दोन आठवडे भाव वाढतोय"},
    "2-week price momentum down": {
        "hi": "दो हफ्ते से भाव गिर रहा", "mr": "दोन आठवडे भाव घसरतोय"},
    "mandi arrivals heavy": {
        "hi": "मंडी में आवक भारी", "mr": "बाजारात आवक जास्त"},
    "mandi arrivals thin": {
        "hi": "मंडी में आवक कम", "mr": "बाजारात आवक कमी"},
    "arrivals accelerating — glut risk": {
        "hi": "आवक तेजी से बढ़ रही — भाव गिरने का खतरा",
        "mr": "आवक झपाट्याने वाढतेय — भाव पडण्याचा धोका"},
    "arrivals above the yearly norm": {
        "hi": "आवक सामान्य से ज्यादा", "mr": "आवक नेहमीपेक्षा जास्त"},
    "arrivals below the yearly norm": {
        "hi": "आवक सामान्य से कम", "mr": "आवक नेहमीपेक्षा कमी"},
    "long past the greenness peak — harvest due": {
        "hi": "फसल पक चुकी — कटाई का समय",
        "mr": "पीक तयार — काढणीची वेळ"},
    "much of the belt already past maturity": {
        "hi": "इलाके की ज्यादातर फसल पक चुकी",
        "mr": "भागातील बहुतांश पीक तयार"},
    "little of the belt past maturity": {
        "hi": "इलाके की फसल अभी कच्ची", "mr": "भागातील पीक अजून कच्चे"},
    "month-long crop senescence — harvest near": {
        "hi": "फसल सूख रही — कटाई नजदीक", "mr": "पीक वाळतंय — काढणी जवळ"},
    "hotter than normal — faster maturity": {
        "hi": "सामान्य से ज्यादा गर्मी — फसल जल्दी पकेगी",
        "mr": "नेहमीपेक्षा जास्त उष्णता — पीक लवकर तयार"},
    "wet month building": {"hi": "महीने भर बारिश", "mr": "महिनाभर पाऊस"},
    "rainfall above normal": {
        "hi": "बारिश सामान्य से ज्यादा", "mr": "पाऊस नेहमीपेक्षा जास्त"},
    "wet week — arrivals may stall": {
        "hi": "बारिश वाला हफ्ता — आवक रुक सकती है",
        "mr": "पावसाचा आठवडा — आवक थांबू शकते"},
    "rain has stopped harvesting": {
        "hi": "बारिश से कटाई रुकी", "mr": "पावसामुळे काढणी थांबली"},
    "humid fortnight — stored crop at risk": {
        "hi": "नमी ज्यादा — रखा माल खराब हो सकता है",
        "mr": "आर्द्रता जास्त — साठवलेला माल खराब होऊ शकतो"},
    "clear run of dry days — harvest can proceed": {
        "hi": "सूखे दिन — कटाई हो सकती है",
        "mr": "कोरडे दिवस — काढणी करता येईल"},
}

# The connective scaffolding alert_engine._reason wraps the driver phrases in.
_CONNECTIVES = {
    "; also ": {"hi": "; साथ ही ", "mr": "; तसेच "},
    "sell into the current window": {
        "hi": "इसी अवधि में बेच दें", "mr": "याच कालावधीत विका"},
    "part-sell and watch closely": {
        "hi": "कुछ बेचें, बाकी पर नजर रखें",
        "mr": "काही विका, बाकीवर लक्ष ठेवा"},
    "hold — conditions favour a better price": {
        "hi": "रोकें — बेहतर भाव मिलने के आसार",
        "mr": "थांबा — चांगला भाव मिळण्याची शक्यता"},
    "Model signal only; no single dominant driver.": {
        "hi": "मॉडल संकेत; कोई एक बड़ा कारण नहीं।",
        "mr": "मॉडेल संकेत; एकच मोठे कारण नाही."},
}

_SUFFIX = {
    "en": "\nReply STOP to unsubscribe.",
    "hi": "\nबंद करने के लिए STOP भेजें।",
    "mr": "\nबंद करण्यासाठी STOP पाठवा.",
}


def _localise_reason(reason: str, lang: str) -> str:
    """Swap translated fragments into `reason`, longest match first.

    The reason is assembled in English by the alert engine from feature phrases;
    translating fragments in place keeps one source of truth for the wording and
    lets an untranslated phrase pass through rather than blocking a send. The
    engine capitalises the leading phrase, so matching allows for that.
    """
    if lang == "en":
        return reason

    out = reason
    table = {**_PHRASE_I18N, **_CONNECTIVES}
    for english in sorted(table, key=len, reverse=True):
        translated = table[english].get(lang)
        if not translated:
            continue
        if english in out:
            out = out.replace(english, translated)
        else:
            capitalised = english[:1].upper() + english[1:]
            if capitalised in out:
                out = out.replace(capitalised, translated)
    return out


def _money(impact: float, lang: str) -> str:
    sign = "+" if impact >= 0 else "−"
    unit = {"en": "/qtl", "hi": "/क्विंटल", "mr": "/क्विंटल"}[lang]
    return f"{sign}₹{abs(round(impact)):,.0f}{unit}"


def build_message(alert: Alert, crop: str = "Onion", market: str = "Lasalgaon",
                  lang: str = "en", include_optout: bool = True) -> str:
    lang = lang if lang in LANGS else "en"
    label = alert.label if lang == "en" else _LABELS.get(
        alert.label, {}).get(lang, alert.label)
    crop_name = crop if lang == "en" else _CROPS.get(crop, {}).get(lang, crop)
    market_name = market if lang == "en" else _MARKETS.get(
        market, {}).get(lang, market)
    # Show the calibrated number — the raw score overstates itself at the top
    # end, and this one goes to a person who will act on it.
    confidence = getattr(alert, "calibrated_confidence", None) or alert.confidence

    body = _TEMPLATES[lang].format(
        emoji=_EMOJI[alert.color],
        market=market_name,
        crop=crop_name,
        date=alert.date,
        label=label,
        w1=alert.window_start,
        w2=alert.window_end,
        impact=_money(alert.expected_impact, lang),
        confidence=confidence,
        reason=_localise_reason(alert.reason, lang),
    )
    return body + (_SUFFIX[lang] if include_optout else "")


# --- phone handling --------------------------------------------------------

def normalise_phone(raw: str, default_cc: str = "91") -> str:
    """To E.164. A ten-digit Indian mobile typed bare is the common case."""
    digits = re.sub(r"[^\d+]", "", str(raw or ""))
    if digits.startswith("+"):
        return digits
    digits = digits.lstrip("0")
    if len(digits) == 10:
        return f"+{default_cc}{digits}"
    return f"+{digits}"


def valid_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"\+\d{10,15}", phone or ""))


def _wa_to(phone: str) -> str:
    """Meta wants the number without a leading +."""
    return normalise_phone(phone).lstrip("+")


# --- Meta WhatsApp Cloud API -----------------------------------------------

def _config() -> dict:
    return {
        "token": os.getenv("WHATSAPP_ACCESS_TOKEN"),
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID"),
        "template": os.getenv("WHATSAPP_TEMPLATE_NAME"),
        "template_lang": os.getenv("WHATSAPP_TEMPLATE_LANG", "en"),
        "version": os.getenv("WHATSAPP_API_VERSION", DEFAULT_API_VERSION),
    }


def whatsapp_status() -> dict:
    """What delivery is possible right now. Sends nothing."""
    cfg = _config()
    return {
        "provider": "meta_cloud_api",
        "configured": bool(cfg["token"] and cfg["phone_number_id"]),
        "phone_number_id": cfg["phone_number_id"],
        "api_version": cfg["version"],
        "template_name": cfg["template"],
        "template_ready": bool(cfg["template"]),
        "whatsapp_ready": bool(cfg["token"] and cfg["phone_number_id"]),
    }


def verify_credentials() -> dict:
    """Read-only check that the token and phone-number ID actually work."""
    cfg = _config()
    if not (cfg["token"] and cfg["phone_number_id"]):
        return {"ok": False, "reason": "whatsapp_not_configured"}
    url = f"{GRAPH_BASE}/{cfg['version']}/{cfg['phone_number_id']}"
    try:
        r = requests.get(
            url,
            params={"fields": "display_phone_number,verified_name,quality_rating"},
            headers={"Authorization": f"Bearer {cfg['token']}"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return {"ok": True, **r.json()}
        return {"ok": False, "status": r.status_code,
                "reason": _graph_error(r)}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _graph_error(response) -> str:
    try:
        err = response.json().get("error", {})
        parts = [err.get("message")]
        if err.get("error_subcode"):
            parts.append(f"subcode {err['error_subcode']}")
        if err.get("code"):
            parts.append(f"code {err['code']}")
        detail = (err.get("error_data") or {}).get("details")
        if detail:
            parts.append(detail)
        return " | ".join(str(p) for p in parts if p)
    except Exception:
        return response.text[:300]


def _post(payload: dict) -> tuple[bool, dict | str]:
    cfg = _config()
    url = f"{GRAPH_BASE}/{cfg['version']}/{cfg['phone_number_id']}/messages"
    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {cfg['token']}",
                 "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code in (200, 201):
        return True, r.json()
    return False, _graph_error(r)


def _outside_window(reason: str) -> bool:
    """Does this Graph error mean 'no open 24-hour session'?

    Meta signals it as error 131047 (re-engagement) or 131026 (undeliverable);
    the wording moves around, the codes don't.
    """
    text = str(reason).lower()
    return any(k in text for k in
               ("131047", "131026", "re-engagement", "outside", "24 hour",
                "24-hour", "message template"))


def send_text(to: str, body: str) -> dict:
    """Free-form text. Only allowed inside the 24-hour customer-service window."""
    cfg = _config()
    if not (cfg["token"] and cfg["phone_number_id"]):
        return {"sent": False, "channel": "whatsapp",
                "reason": "whatsapp_not_configured", "preview": body}
    ok, result = _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _wa_to(to),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    })
    if ok:
        return {"sent": True, "channel": "whatsapp", "kind": "text",
                "sid": _message_id(result), "to": normalise_phone(to),
                "preview": body}
    return {"sent": False, "channel": "whatsapp", "kind": "text",
            "to": normalise_phone(to), "reason": result, "preview": body}


def send_template(to: str, body: str, template: str | None = None,
                  lang: str | None = None) -> dict:
    """Pre-approved template send — the only thing Meta allows outside 24h.

    The template is expected to carry a single {{1}} body parameter; the whole
    rendered alert goes in there, so the wording still lives in this module
    rather than being frozen inside Meta's approval flow.
    """
    cfg = _config()
    name = template or cfg["template"]
    if not (cfg["token"] and cfg["phone_number_id"]):
        return {"sent": False, "channel": "whatsapp",
                "reason": "whatsapp_not_configured", "preview": body}
    if not name:
        return {"sent": False, "channel": "whatsapp", "kind": "template",
                "reason": "no_template_configured", "preview": body}

    ok, result = _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _wa_to(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang or cfg["template_lang"]},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": body}],
            }],
        },
    })
    if ok:
        return {"sent": True, "channel": "whatsapp", "kind": "template",
                "template": name, "sid": _message_id(result),
                "to": normalise_phone(to), "preview": body}
    return {"sent": False, "channel": "whatsapp", "kind": "template",
            "template": name, "to": normalise_phone(to),
            "reason": result, "preview": body}


def _message_id(result: dict) -> str | None:
    try:
        return result["messages"][0]["id"]
    except Exception:
        return None


def send_alert(to: str, body: str, channel: str = "whatsapp") -> dict:
    """Text first, template when Meta says the 24-hour window is shut.

    Trying text first keeps the common case (a farmer who just registered, so
    has messaged us seconds ago) free of template constraints, while the
    fallback keeps a Monday-morning broadcast working for everyone else.
    """
    if channel == "template":
        return send_template(to, body)

    result = send_text(to, body)
    if result["sent"] or channel == "text_only":
        return result

    if not _outside_window(result.get("reason", "")):
        result["hint"] = explain_error(result.get("reason"))
        return result

    fallback = send_template(to, body)
    fallback["text_error"] = result.get("reason")
    fallback["fell_back"] = True
    if not fallback["sent"]:
        fallback["reason"] = (
            f"text: {result.get('reason')} | template: {fallback.get('reason')}"
        )
        fallback["hint"] = explain_error(fallback["reason"])
    return fallback


def explain_error(reason: str | None) -> str | None:
    """Turn a Graph API failure into the thing you actually have to go and do."""
    if not reason:
        return None
    text = str(reason).lower()
    if "whatsapp_not_configured" in text:
        return ("Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID in "
                "backend/.env — both come from Meta for Developers → your app "
                "→ WhatsApp → API Setup.")
    if "no_template_configured" in text:
        return ("Outside the 24-hour window Meta only accepts a template. "
                "Create one under WhatsApp Manager → Message templates with a "
                "single {{1}} body variable, then set WHATSAPP_TEMPLATE_NAME.")
    if "131047" in text or "re-engagement" in text:
        return ("No open 24-hour session with this number. Either have the "
                "phone message the business number first, or configure "
                "WHATSAPP_TEMPLATE_NAME so the template fallback can fire.")
    if "131030" in text or "not in allowed list" in text:
        return ("This recipient is not on the test-number allow-list. In the "
                "Meta app under WhatsApp → API Setup, add the number under "
                "'To' — unverified apps can only message listed testers.")
    if "190" in text and "token" in text:
        return ("The access token has expired. The API Setup page issues a "
                "24-hour token; create a System User token for one that lasts.")
    if "133010" in text or "not registered" in text:
        return ("The sender phone number is not registered for Cloud API. "
                "Complete registration in WhatsApp Manager.")
    if "100" in text and "phone_number_id" in text:
        return ("WHATSAPP_PHONE_NUMBER_ID looks wrong — it is a long numeric "
                "ID from the API Setup page, not the phone number itself.")
    return None

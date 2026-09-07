"""Delivery layer — the WhatsApp message body itself.

Three languages (English, Hindi, Marathi) in four blocks, because the message is
read on a cheap phone in a mandi, not on a dashboard: who it is from, what to
do, what it is worth, and why. The order is fixed and the verdict sits on a line
of its own — a farmer who reads nothing else should still have the decision.

Formatting is WhatsApp's own, and *bold* only: the site mirrors this text in its
preview bubble and renders the same markup, so anything else would show up there
as stray punctuation.

This module only *builds* text and normalises phone numbers. Actually sending it
lives in `bhav.whatsapp`, which talks to the open-wa bridge.
"""

from __future__ import annotations

import re
from datetime import date

from .alert_engine import Alert

LANGS = ("en", "hi", "mr")

_EMOJI = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢"}

# Four blocks: who · verdict · numbers · why. The blank lines between them do
# the work the punctuation used to — on a small screen the eye needs somewhere
# to rest, and the verdict has to survive being read at a glance.
_TEMPLATES = {
    "en": (
        "{emoji} *Bhav* · {crop} · {market}\n"
        "{date}\n"
        "\n"
        "*{label}*\n"
        "{advice}\n"
        "\n"
        "📅 Window: *{window}*\n"
        "💰 Impact: *{impact}* vs holding\n"
        "📊 Confidence: *{confidence}%*\n"
        "\n"
        "*Why*\n"
        "{why}"
    ),
    "hi": (
        "{emoji} *भाव* · {crop} · {market}\n"
        "{date}\n"
        "\n"
        "*{label}*\n"
        "{advice}\n"
        "\n"
        "📅 अवधि: *{window}*\n"
        "💰 असर: *{impact}* रोकने की तुलना में\n"
        "📊 भरोसा: *{confidence}%*\n"
        "\n"
        "*कारण*\n"
        "{why}"
    ),
    "mr": (
        "{emoji} *भाव* · {crop} · {market}\n"
        "{date}\n"
        "\n"
        "*{label}*\n"
        "{advice}\n"
        "\n"
        "📅 कालावधी: *{window}*\n"
        "💰 परिणाम: *{impact}* थांबण्याच्या तुलनेत\n"
        "📊 खात्री: *{confidence}%*\n"
        "\n"
        "*कारण*\n"
        "{why}"
    ),
}

# Month names rather than an ISO date. `2026-09-14` is a machine's way of
# writing a day; nobody standing in a mandi parses it at a glance.
_MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "hi": ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
           "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"),
    "mr": ("जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून",
           "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"),
}

# What the colour means as an instruction. The wording is kept identical to the
# clauses alert_engine._reason appends, so _CONNECTIVES below already carries
# the Hindi and Marathi for all three.
_ADVICE = {
    "RED": "sell into the current window",
    "AMBER": "part-sell and watch closely",
    "GREEN": "hold — conditions favour a better price",
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
    # --- satellite / crop stage ---
    "crop canopy healthy and near peak": {
        "hi": "फसल हरी-भरी, चरम पर", "mr": "पीक हिरवेगार, ऐन बहरात"},
    "crop canopy thin / stressed": {
        "hi": "फसल कमजोर / तनाव में", "mr": "पीक कमकुवत / ताणाखाली"},
    "greenness rising week-on-week": {
        "hi": "हफ्ते दर हफ्ते हरियाली बढ़ रही",
        "mr": "आठवड्यागणिक हिरवाई वाढतेय"},
    "greenness dropping week-on-week": {
        "hi": "हफ्ते दर हफ्ते हरियाली घट रही",
        "mr": "आठवड्यागणिक हिरवाई घटतेय"},
    "2-week crop growth strong": {
        "hi": "दो हफ्ते से फसल अच्छी बढ़ रही",
        "mr": "दोन आठवडे पीक चांगले वाढतेय"},
    "2-week crop decline": {
        "hi": "दो हफ्ते से फसल उतार पर", "mr": "दोन आठवडे पीक उतरणीला"},
    "month-long crop build-up": {
        "hi": "महीने भर फसल बढ़ी", "mr": "महिनाभर पीक वाढले"},
    "crop ahead of the seasonal norm": {
        "hi": "फसल मौसम के औसत से आगे", "mr": "पीक हंगामी सरासरीच्या पुढे"},
    "crop behind the seasonal norm": {
        "hi": "फसल मौसम के औसत से पीछे", "mr": "पीक हंगामी सरासरीच्या मागे"},
    "canopy still greening up": {
        "hi": "फसल अभी हरी हो रही", "mr": "पीक अजून हिरवे होतेय"},
    "canopy drying down toward harvest": {
        "hi": "फसल कटाई की ओर सूख रही", "mr": "पीक काढणीकडे वाळतेय"},
    "recently past peak greenness": {
        "hi": "हरियाली अभी-अभी चरम पार कर गई",
        "mr": "हिरवाई नुकतीच शिखर ओलांडली"},
    "crop drying down fast": {
        "hi": "फसल तेजी से सूख रही", "mr": "पीक झपाट्याने वाळतेय"},
    "crop drying slowly": {
        "hi": "फसल धीरे सूख रही", "mr": "पीक हळू वाळतेय"},
    "satellite read is stale — cloud cover": {
        "hi": "बादलों से सैटेलाइट रीडिंग पुरानी",
        "mr": "ढगांमुळे उपग्रह नोंद जुनी"},
    "fresh satellite read": {
        "hi": "ताजा सैटेलाइट रीडिंग", "mr": "ताजी उपग्रह नोंद"},
    # --- weather ---
    "dry week — smooth harvesting": {
        "hi": "सूखा हफ्ता — कटाई आसान", "mr": "कोरडा आठवडा — काढणी सुलभ"},
    "dry month": {"hi": "सूखा महीना", "mr": "कोरडा महिना"},
    "rainfall below normal": {
        "hi": "बारिश सामान्य से कम", "mr": "पाऊस नेहमीपेक्षा कमी"},
    "cooler than normal": {"hi": "सामान्य से ठंडा", "mr": "नेहमीपेक्षा थंड"},
    "wide day-night temp swing": {
        "hi": "दिन-रात के तापमान में बड़ा फर्क",
        "mr": "दिवस-रात्र तापमानात मोठा फरक"},
    "narrow temp swing": {
        "hi": "तापमान में कम उतार-चढ़ाव", "mr": "तापमानात कमी चढउतार"},
    "dry air — crop stores well": {
        "hi": "सूखी हवा — माल अच्छा टिकेगा",
        "mr": "कोरडी हवा — माल चांगला टिकेल"},
    "more humid than normal for the season": {
        "hi": "मौसम से ज्यादा नमी", "mr": "हंगामापेक्षा जास्त आर्द्रता"},
    "drier than normal for the season": {
        "hi": "मौसम से ज्यादा सूखा", "mr": "हंगामापेक्षा जास्त कोरडे"},
    "few dry days — lifting is stalled": {
        "hi": "सूखे दिन कम — खुदाई रुकी",
        "mr": "कोरडे दिवस कमी — काढणी थांबली"},
    "no rain interrupting harvest": {
        "hi": "बारिश से कटाई में रुकावट नहीं",
        "mr": "पावसाचा काढणीत अडथळा नाही"},
    "repeated heat days — maturity pulled forward": {
        "hi": "लगातार गर्मी — फसल जल्दी पकी",
        "mr": "सलग उष्णता — पीक लवकर तयार"},
    "no heat stress": {"hi": "गर्मी का दबाव नहीं", "mr": "उष्णतेचा ताण नाही"},
    "strong drying conditions — good curing": {
        "hi": "सुखाने लायक मौसम — क्योरिंग अच्छी",
        "mr": "वाळवणीस पोषक हवामान — क्युरिंग चांगली"},
    "weak drying conditions — curing slow": {
        "hi": "सुखाने लायक मौसम नहीं — क्योरिंग धीमी",
        "mr": "वाळवणीस प्रतिकूल — क्युरिंग हळू"},
    # --- mandi ---
    "mandi has been shut — price is stale": {
        "hi": "मंडी बंद रही — भाव पुराना", "mr": "बाजार बंद होता — भाव जुना"},
    "mandi trading normally": {
        "hi": "मंडी सामान्य चल रही", "mr": "बाजार नेहमीप्रमाणे सुरू"},
    "price rising this week": {
        "hi": "इस हफ्ते भाव चढ़ रहा", "mr": "या आठवड्यात भाव वाढतोय"},
    "price falling this week": {
        "hi": "इस हफ्ते भाव गिर रहा", "mr": "या आठवड्यात भाव घसरतोय"},
    "price in the top of its yearly range": {
        "hi": "भाव साल की ऊपरी सीमा पर", "mr": "भाव वर्षाच्या वरच्या टप्प्यात"},
    "price in the bottom of its yearly range": {
        "hi": "भाव साल की निचली सीमा पर", "mr": "भाव वर्षाच्या खालच्या टप्प्यात"},
    "arrivals easing": {"hi": "आवक घट रही", "mr": "आवक कमी होतेय"},
    "seasonal timing": {"hi": "मौसम का समय", "mr": "हंगामाची वेळ"},
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
    "en": "\n\nReply STOP to unsubscribe.",
    "hi": "\n\nबंद करने के लिए STOP भेजें।",
    "mr": "\n\nबंद करण्यासाठी STOP पाठवा.",
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


def _phrase(english: str, lang: str) -> str:
    """One driver phrase, translated if we have it, capitalised for English."""
    if lang == "en":
        return english[:1].upper() + english[1:]
    return _PHRASE_I18N.get(english, {}).get(lang, english)


def _why(alert: Alert, lang: str) -> str:
    """The drivers as bullets rather than a semicolon-spliced sentence.

    Two of them, the same two the engine puts in `reason` — a third reads as
    hedging, and the whole point of the block is that it can be skipped. Falls
    back to the engine's own sentence when the model found no dominant driver,
    which is the one case where there is nothing to bullet.
    """
    factors = getattr(alert.score, "factors", None) or []
    phrases = [f.get("phrase") for f in factors[:2] if f.get("phrase")]
    if not phrases:
        return _localise_reason(alert.reason, lang)
    return "\n".join(f"• {_phrase(p, lang)}" for p in phrases)


def _advice(color: str, lang: str) -> str:
    """The line under the verdict — what the colour actually means.

    Where a clause is written as "verb — explanation" we keep only the
    explanation: the verb is already the bold word directly above it, and in
    Marathi it is the very same word ("थांबा / थांबा — …"), which reads like a
    stutter. Clauses with no dash carry no such repetition and are used whole.
    """
    english = _ADVICE.get(color, "")
    text = english if lang == "en" else _CONNECTIVES.get(
        english, {}).get(lang, english)
    _, dash, tail = text.partition(" — ")
    if dash:
        text = tail
    return text[:1].upper() + text[1:] if lang == "en" else text


def _day(iso: str) -> date | None:
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _fmt_date(iso: str, lang: str) -> str:
    """`2026-09-07` -> `7 Sep 2026`."""
    d = _day(iso)
    return f"{d.day} {_MONTHS[lang][d.month - 1]} {d.year}" if d else str(iso)


def _fmt_window(start: str, end: str, lang: str) -> str:
    """`14–18 Sep`, or `28 Sep – 2 Oct` when the window straddles two months.

    The month is what makes a date legible at a glance, so it is never dropped —
    only its repetition is.
    """
    a, b = _day(start), _day(end)
    if not a or not b:
        return f"{start} – {end}"
    months = _MONTHS[lang]
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {months[a.month - 1]}"
    return f"{a.day} {months[a.month - 1]} – {b.day} {months[b.month - 1]}"


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
        date=_fmt_date(alert.date, lang),
        # Upper-cases the English verdict and leaves Devanagari untouched, which
        # is exactly what we want: one loud token per script.
        label=label.upper(),
        advice=_advice(alert.color, lang),
        window=_fmt_window(alert.window_start, alert.window_end, lang),
        impact=_money(alert.expected_impact, lang),
        confidence=confidence,
        why=_why(alert, lang),
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

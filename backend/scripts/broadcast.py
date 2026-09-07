"""Compute today's signal and send it to every registered farmer.

Roadmap §H12–H20: "daily compute -> send script (manual trigger is fine for
demo)". Dry run by default — this is the script that can message a real room,
so sending has to be typed out in full.

    python -m scripts.broadcast                 # preview only, sends nothing
    python -m scripts.broadcast --send          # actually send
    python -m scripts.broadcast --send --to +919876543210   # one number
    python -m scripts.broadcast --date 2019-12-03 --lang mr # a past signal
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from bhav.config import BACKEND_DIR, CROP

load_dotenv(BACKEND_DIR / ".env")

from bhav.alert_engine import build_alert          # noqa: E402
from bhav.features import build_features           # noqa: E402
from bhav.message import build_message                            # noqa: E402
from bhav.whatsapp import (  # noqa: E402
    send_alert,
    verify_credentials,
    whatsapp_status,
)
from bhav.subscribers import active_subscribers, log_send          # noqa: E402


def _latest_date():
    return build_features(with_target=False).index.max()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true",
                    help="actually deliver (default is a dry run)")
    ap.add_argument("--to", help="one number, instead of the subscriber list")
    ap.add_argument("--lang", default=None, help="override language (en|hi|mr)")
    ap.add_argument("--date", default=None, help="signal as of YYYY-MM-DD")
    ap.add_argument("--market", default="Lasalgaon")
    args = ap.parse_args()

    status = whatsapp_status()
    print(f"open-wa bridge at {status['bridge_url']}: "
          f"session={status['session_status']}")
    creds = verify_credentials()
    if creds.get("ok"):
        print(f"  linked as {creds.get('display_phone_number') or 'unknown number'}")
    else:
        print(f"  NOT READY: {creds.get('reason')}")
        if status.get("qr_available"):
            print("  A pairing QR is waiting — scan it from the sending phone:")
            print("    open http://localhost:8000/message/qr")
        else:
            print("  Start the bridge:  cd whatsapp && npm start")
    print()

    alert = build_alert(args.date or _latest_date(), persist=False)
    print(f"Signal {alert.date}: {alert.color} — {alert.label}  "
          f"({alert.calibrated_confidence}% calibrated confidence)")
    print()

    if args.to:
        recipients = [{"phone": args.to, "lang": args.lang or "en"}]
    else:
        df = active_subscribers()
        if df.empty:
            print("No active subscribers. Register one:")
            print('  curl -X POST localhost:8000/subscribe '
                  '-H "Content-Type: application/json" '
                  '-d \'{"phone":"+919876543210","lang":"mr"}\'')
            return 0
        recipients = [
            {"phone": r["phone"], "lang": args.lang or r.get("lang") or "en"}
            for _, r in df.iterrows()
        ]

    print(f"{'DRY RUN — ' if not args.send else ''}{len(recipients)} recipient(s)")
    print("-" * 62)

    sent = 0
    for r in recipients:
        text = build_message(alert, crop=CROP.capitalize(),
                             market=args.market, lang=r["lang"])
        print(f"\nto {r['phone']}  [{r['lang']}]")
        print("  " + text.replace("\n", "\n  "))
        if not args.send:
            continue
        result = send_alert(r["phone"], text)
        log_send(r["phone"], alert.date, r["lang"], result, text)
        sent += bool(result.get("sent"))
        flag = "OK" if result.get("sent") else "FAILED"
        detail = result.get("sid") or result.get("reason", "")
        print(f"  -> {flag} via open-wa: {detail}")
        if result.get("hint"):
            print(f"     FIX: {result['hint']}")

    print()
    if args.send:
        print(f"delivered {sent}/{len(recipients)}")
    else:
        print("Nothing sent. Re-run with --send to deliver.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

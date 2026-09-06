"""Pull every raw source, then load into sqlite. Run before the event.

    python -m scripts.fetch_all           # all three sources + load
    python -m scripts.fetch_all --skip-ndvi   # if GEE auth isn't ready yet
"""

from __future__ import annotations

import argparse
import sys

from bhav.ingest import load, mandi, weather


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ndvi", action="store_true")
    ap.add_argument("--skip-mandi", action="store_true")
    ap.add_argument("--skip-weather", action="store_true")
    args = ap.parse_args()

    if not args.skip_ndvi:
        from bhav.ingest import ndvi
        print("== NDVI (Google Earth Engine) ==")
        ndvi.main()
    if not args.skip_weather:
        print("== weather (Open-Meteo archive) ==")
        weather.main()
    if not args.skip_mandi:
        print("== mandi (Agmarknet) ==")
        mandi.main()

    print("== load -> sqlite ==")
    load.load_all()
    print("done.")


if __name__ == "__main__":
    sys.exit(main())

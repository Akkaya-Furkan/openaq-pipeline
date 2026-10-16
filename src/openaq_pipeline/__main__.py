"""CLI entry point."""
import argparse
import json
import logging
import sys

from . import alerts, notify, store
from .config import CITIES, MissingApiKey
from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description="Load OpenAQ PM2.5 and NO2 into SQLite.")
    parser.add_argument("--db", default="data/air.db")
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--cities", nargs="+", choices=CITIES, default=list(CITIES))
    parser.add_argument("--alerts", action="store_true",
                        help="after the run, check WHO 24 h guidelines and notify (Telegram or dry-run)")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="do not call the API; only evaluate alerts on stored data")
    parser.add_argument("-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, stream=sys.stderr)
    # httpx DEBUG logs include request headers; keep the API key out of logging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    summary = {}
    try:
        if not args.skip_fetch:
            summary = run(db_path=args.db, cities=args.cities, hours=args.hours)
    except MissingApiKey as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.alerts or args.skip_fetch:
        conn = store.init(args.db)
        try:
            summary.update(alerts.check_and_notify(conn, notify.make_transport()))
        finally:
            conn.close()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

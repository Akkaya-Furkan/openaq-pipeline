"""CLI entry point."""
import argparse
import json
import logging
import sys

from .config import CITIES, MissingApiKey
from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description="Load OpenAQ PM2.5 and NO2 into SQLite.")
    parser.add_argument("--db", default="data/air.db")
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--cities", nargs="+", choices=CITIES, default=list(CITIES))
    parser.add_argument("-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, stream=sys.stderr)
    # httpx DEBUG logs include request headers; keep the API key out of logging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        summary = run(db_path=args.db, cities=args.cities, hours=args.hours)
    except MissingApiKey as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

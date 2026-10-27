"""
backfill_from_raw.py - rebuild the odds database from the raw JSON archive.

The raw files in data/raw/ are the source of truth. Run this to:
  * build data/odds.db for the first time from files you downloaded, or
  * rebuild it after changing the tables in storage.py (use --rebuild), or
  * add newly downloaded raw files to an existing database.

Running it again never creates duplicates.

    python scripts/backfill_from_raw.py
    python scripts/backfill_from_raw.py --rebuild
    python scripts/backfill_from_raw.py --raw-dir ../odds-history-data/raw --db data/odds.db
"""

import argparse
import sys
from pathlib import Path

# Let this script import storage.py from the project folder, wherever you run it from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild odds.db from the raw JSON archive.")
    parser.add_argument("--raw-dir", default=None,
                        help="folder holding the YYYY-MM-DD folders (default: data/raw)")
    parser.add_argument("--db", default=None, help="database file to write (default: data/odds.db)")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete the existing database first and rebuild it from scratch")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir) if args.raw_dir else storage.data_dir() / "raw"
    db_file = Path(args.db) if args.db else storage.db_path()
    if not raw_dir.is_dir():
        raise SystemExit(f"Raw folder not found: {raw_dir}")

    summary = storage.rebuild_from_raw(raw_dir, db_file, rebuild=args.rebuild)
    print(f"Read {summary['files']} raw file(s) from {raw_dir}")
    print(f"  {summary['events']} game rows and {summary['odds']} price rows processed "
          f"(rows already in the database are ignored)")
    if summary["skipped_files"]:
        print(f"  skipped {summary['skipped_files']} file(s), see the [storage] lines above")
    print(f"Database: {db_file}")


if __name__ == "__main__":
    main()

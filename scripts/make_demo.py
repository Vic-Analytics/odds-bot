"""
make_demo.py - build the public demo page from SYNTHETIC data.

    python scripts/make_demo.py                       writes docs/index.html
    python scripts/make_demo.py --seed 7 --out demo.html

The page looks like the real dashboard after a few weeks of data, but every number on it is
randomly generated (analysis/demo_data.py): no real odds, scores or history are used, and it
is clearly marked "DEMO: fake data". Run it again after changing the dashboard, and commit the
new docs/index.html (a test fails if the committed page is out of date).

GitHub Pages can serve docs/ as a free public demo link; see the README for the clicks.
"""

import argparse
import contextlib
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import dashboard  # noqa: E402
import demo_data  # noqa: E402

BANNER = "DEMO: fake data."
BANNER_NOTE = ("Every price, line and score on this page is randomly generated. It shows what the Odds Bot "
               "dashboard looks like after a few weeks of data; none of it is real odds or results.")
DEFAULT_OUT = ROOT / "docs" / "index.html"


def make_page(seed=demo_data.DEMO_SEED):
    """The demo dashboard as a string. The same seed always gives exactly the same page."""
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "demo.db"
        demo_data.build_database(database, seed)
        # The bot's emoji code prints a line for every club it has no kit colors for (it shows a plain
        # soccer ball instead). That is useful in the daily log but just noise here, so keep it out of the output.
        with contextlib.redirect_stdout(io.StringIO()):
            return dashboard.build(database, 48, now=demo_data.DEMO_NOW, banner=BANNER, banner_note=BANNER_NOTE)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the fake-data demo page.")
    parser.add_argument("--seed", type=int, default=demo_data.DEMO_SEED, help="random seed (default %(default)s)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="page to write (default: docs/index.html)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:       # the same bytes on every computer
        f.write(make_page(args.seed))
    (out.parent / ".nojekyll").write_text("", encoding="utf-8")      # GitHub Pages: serve the file as it is
    print(f"Wrote {out} (synthetic data, seed {args.seed})")


if __name__ == "__main__":
    main()

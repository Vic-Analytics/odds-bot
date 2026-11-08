"""Guards for the README's demo section and architecture diagram, so they cannot quietly rot."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def diagram():
    match = re.search(r"```mermaid\n(.*?)```", README, re.S)
    assert match, "the README has no mermaid diagram"
    return match.group(1)


def test_the_diagram_shows_every_part_of_the_system():
    text = diagram()
    for part in ("Daily digest", "Results job", "Results recap", "healthchecks.io", "odds-history-data", "Telegram",
                 "The Odds API", "free score APIs", "odds.db", "Dashboard page", "Fake-data generator", "GitHub Pages"):
        assert part in text, f"the diagram does not mention {part}"


def test_the_diagram_is_well_formed():
    text = diagram()
    assert text.lstrip().startswith("flowchart")
    assert len(re.findall(r"^\s*subgraph\b", text, re.M)) == len(re.findall(r"^\s*end\s*$", text, re.M))
    # every box an arrow points to or from is defined somewhere with a label
    defined = set(re.findall(r"^\s*(\w+)[\[\(]", text, re.M)) | set(re.findall(r"-->\s*(\w+)[\[\(]", text))
    used = set(re.findall(r"(?:-->|\|)\s*(\w+)\s*$", text, re.M)) | set(re.findall(r"^\s*(\w+)\s+-->", text, re.M))
    assert used <= defined, f"arrows use boxes that were never defined: {used - defined}"


def test_the_demo_section_points_at_files_that_exist():
    assert "## Dashboard demo" in README and "![The analysis dashboard, built from fake data](docs/screenshot.png)" in README
    for name in ("index.html", "screenshot.png", ".nojekyll"):
        assert (ROOT / "docs" / name).exists(), f"docs/{name} is missing"
    assert (ROOT / "docs" / "screenshot.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"        # a real PNG file
    assert "https://vic-analytics.github.io/odds-bot/" in README


def test_the_demo_page_in_docs_is_marked_as_fake():
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "DEMO: fake data." in page and "(DEMO)" in page

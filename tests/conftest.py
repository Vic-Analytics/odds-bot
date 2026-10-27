"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point odds-history storage at a throwaway folder for EVERY test, so no
    test can ever write into the real data/ folder."""
    monkeypatch.setenv("ODDS_DATA_DIR", str(tmp_path / "data"))

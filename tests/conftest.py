from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geoagent.config import load_settings  # noqa: E402
from geoagent.datasets import scan_dataset  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def bench_items(settings):
    return scan_dataset(settings.paths.image_dir, settings.paths.latex_dir)


@pytest.fixture(scope="session")
def semicircle_item(bench_items):
    """1035_q_fig1: semicircle with diameter, chords and six labels."""
    return next(item for item in bench_items if item.stem == "1035_q_fig1")


@pytest.fixture()
def tmp_out(tmp_path):
    return tmp_path / "geoagent_test"

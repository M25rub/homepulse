"""Shared test setup: every test gets its own empty home file and instant (no-delay) devices."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HOMEPULSE_LATENCY_MS"] = "0"          # must be set before commands.py is imported
os.environ["HOMEPULSE_WATCH_SECONDS"] = "0"      # tests run the watch by hand, never in the background

import pytest

import commands
import core
import watcher


@pytest.fixture(autouse=True)
def fresh_home(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "FILE", tmp_path / "home.json")
    monkeypatch.setattr(commands, "LATENCY_MS", 0)
    commands.reset()
    watcher.reset()
    yield tmp_path / "home.json"


@pytest.fixture
def sample_home():
    home = core.load_home()
    core.load_sample(home)
    core.save_home(home)
    return home

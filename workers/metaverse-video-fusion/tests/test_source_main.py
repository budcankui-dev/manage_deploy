"""Tests for metaverse source user-endpoint startup behavior."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = REPO_ROOT / "workers" / "metaverse-video-fusion" / "src"
WORKERS_ROOT = REPO_ROOT / "workers"
sys.path.insert(0, str(SOURCE_DIR))
sys.path.insert(0, str(WORKERS_ROOT))

spec = importlib.util.spec_from_file_location("metaverse_video_fusion_source_main", SOURCE_DIR / "source_main.py")
assert spec and spec.loader
source_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_main)


def test_external_user_source_can_skip_compute_ready_wait(monkeypatch):
    monkeypatch.setenv("WAIT_FOR_COMPUTE_READY", "false")
    assert source_main._should_wait_for_compute_ready() is False


def test_metaverse_source_waits_for_compute_ready_by_default(monkeypatch):
    monkeypatch.delenv("WAIT_FOR_COMPUTE_READY", raising=False)
    assert source_main._should_wait_for_compute_ready() is True


def test_external_user_source_can_disable_local_listener(monkeypatch):
    monkeypatch.setenv("SOURCE_LISTEN", "false")
    assert source_main._source_listen_enabled() is False


def test_metaverse_source_listens_by_default(monkeypatch):
    monkeypatch.delenv("SOURCE_LISTEN", raising=False)
    assert source_main._source_listen_enabled() is True

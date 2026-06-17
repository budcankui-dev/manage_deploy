"""Tests for video source user-endpoint startup behavior."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VIDEO_SRC = REPO_ROOT / "workers" / "low-latency-video" / "src"
WORKERS_ROOT = REPO_ROOT / "workers"
sys.path.insert(0, str(VIDEO_SRC))
sys.path.insert(0, str(WORKERS_ROOT))

import source_main as sm  # noqa: E402


def test_external_user_source_can_skip_compute_ready_wait(monkeypatch):
    monkeypatch.setenv("WAIT_FOR_COMPUTE_READY", "false")

    assert sm._should_wait_for_compute_ready() is False


def test_video_source_waits_for_compute_ready_by_default(monkeypatch):
    monkeypatch.delenv("WAIT_FOR_COMPUTE_READY", raising=False)

    assert sm._should_wait_for_compute_ready() is True

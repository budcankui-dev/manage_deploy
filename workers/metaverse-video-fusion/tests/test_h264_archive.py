"""Archive codec contract for the metaverse browser playback result."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src" / "fusion_core.py"


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe are provided by the metaverse worker image",
)
def test_h264_archive_is_ffprobe_playable(tmp_path):
    spec = importlib.util.spec_from_file_location("metaverse_fusion_core", SRC_PATH)
    assert spec and spec.loader
    fusion_core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fusion_core)

    archive = tmp_path / "fusion-result.mp4"
    encoder = fusion_core._start_h264_encoder(archive, width=2, height=2, fps=30)
    encoder.stdin.write(bytes((255, 0, 0)) * 4)
    encoder.stdin.write(bytes((0, 255, 0)) * 4)
    fusion_core._finish_h264_encoder(encoder)
    fusion_core._assert_h264_archive(archive)


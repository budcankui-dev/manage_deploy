"""Tests for object_io and INPUT_* handling in matmul source."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mimic Docker layout locally:
# /app/_common   -> workers/_common
# /app/src        -> workers/high-throughput-matmul/src
REPO_ROOT = Path(__file__).resolve().parents[3]  # manage_deploy/
WORKERS_COMMON = REPO_ROOT / "workers" / "_common"
MATMUL_SRC = REPO_ROOT / "workers" / "high-throughput-matmul" / "src"
sys.path.insert(0, str(WORKERS_COMMON))  # _common.object_io
sys.path.insert(0, str(MATMUL_SRC))  # source_main (as if /app/src/)

from _common.object_io import parse_s3_uri  # noqa: E402
import source_main as sm  # noqa: E402


# ---------------------------------------------------------------------------
# parse_s3_uri
# ---------------------------------------------------------------------------


def test_parse_s3_uri_basic():
    bucket, key = parse_s3_uri("s3://my-bucket/path/to/object.json")
    assert bucket == "my-bucket"
    assert key == "path/to/object.json"


def test_parse_s3_uri_root_object():
    bucket, key = parse_s3_uri("s3://bucket/manifest.json")
    assert bucket == "bucket"
    assert key == "manifest.json"


def test_parse_s3_uri_nested():
    bucket, key = parse_s3_uri("s3://task-inputs/user-123/order-456/job.json")
    assert bucket == "task-inputs"
    assert key == "user-123/order-456/job.json"


def test_parse_s3_uri_invalid_no_s3_prefix():
    with pytest.raises(ValueError, match="Invalid s3:// URI"):
        parse_s3_uri("https://bucket/key")


def test_parse_s3_uri_invalid_no_bucket():
    with pytest.raises(ValueError, match="Invalid s3:// URI"):
        parse_s3_uri("s3:///key")


def test_parse_s3_uri_invalid_no_key():
    with pytest.raises(ValueError, match="Invalid s3:// URI"):
        parse_s3_uri("s3://bucket")


# ---------------------------------------------------------------------------
# object_io helpers (mocked client)
# ---------------------------------------------------------------------------


def test_download_object_minio_client():
    """Test download_object with a MinIO-style mock client."""
    from _common.object_io import download_object

    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.read.return_value = b'{"matrix_size": 512}'
    mock_client.get_object.return_value = mock_result

    data = download_object(mock_client, "bucket", "key.json")
    assert data == b'{"matrix_size": 512}'
    mock_client.get_object.assert_called_once_with("bucket", "key.json")


def test_download_object_boto3_client():
    """Test download_object with a boto3-style mock client (not minio)."""
    from _common.object_io import download_object

    mock_client = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = b'{"batch_count": 4}'
    mock_client.get_object.return_value = {"Body": mock_body}

    data = download_object(mock_client, "bucket", "key.json")
    assert data == b'{"batch_count": 4}'
    mock_client.get_object.assert_called_with(Bucket="bucket", Key="key.json")


def test_download_json_object():
    """Test download_json_object parses JSON correctly."""
    from _common.object_io import download_json_object

    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.read.return_value = b'{"matrix_size": 1024, "seed": 7}'
    mock_client.get_object.return_value = mock_result

    result = download_json_object(mock_client, "bucket", "profile.json")
    assert result == {"matrix_size": 1024, "seed": 7}


# ---------------------------------------------------------------------------
# source INPUT_* fallback logic
# ---------------------------------------------------------------------------


def test_data_profile_synthetic_fallback(monkeypatch):
    """DATA_PROFILE synthetic fallback works when no INPUT_* vars are set."""
    monkeypatch.setenv("DATA_PROFILE", '{"matrix_size": 128, "batch_count": 3, "seed": 99}')
    monkeypatch.delenv("INPUT_MANIFEST_URI", raising=False)
    monkeypatch.delenv("INPUT_OBJECTS", raising=False)

    job = sm._build_job_from_data_profile()
    assert job["matrix_size"] == 128
    assert job["batch_count"] == 3
    assert job["seed"] == 99


def test_input_objects_json_overrides_profile():
    """INPUT_OBJECTS downloads JSON files and merges into DATA_PROFILE."""
    # Patch _build_minio_client_from_env to return our mock client
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.read.return_value = json.dumps({"batch_count": 8, "seed": 123}).encode()
    mock_client.get_object.return_value = mock_result

    with patch.object(sm, "_build_minio_client_from_env", return_value=mock_client):
        with patch.dict(
            os.environ,
            {
                "DATA_PROFILE": '{"matrix_size": 512, "batch_count": 4}',
                "INPUT_OBJECTS": '["s3://task-inputs/user-1/order-1/override.json"]',
            },
            clear=False,
        ):
            job = sm._build_job_from_input_objects('["s3://task-inputs/user-1/order-1/override.json"]')
            assert job["matrix_size"] == 512  # from DATA_PROFILE, not overridden
            assert job["batch_count"] == 8  # overridden from INPUT_OBJECTS JSON
            assert job["seed"] == 123  # overridden from INPUT_OBJECTS JSON


def test_input_objects_invalid_json():
    """INPUT_OBJECTS with invalid JSON raises a clear error."""
    with patch.dict(os.environ, {"INPUT_OBJECTS": "not valid json"}, clear=False):
        with pytest.raises(RuntimeError, match="INPUT_OBJECTS is not valid JSON"):
            sm._build_job_from_input_objects("not valid json")


def test_input_manifest_uri_parsing():
    """INPUT_MANIFEST_URI with valid s3:// format parses correctly."""
    bucket, key = parse_s3_uri("s3://task-inputs/user-1/manifest.json")
    assert bucket == "task-inputs"
    assert key == "user-1/manifest.json"


def test_input_manifest_uri_invalid_format():
    """INPUT_MANIFEST_URI with invalid format raises a clear error."""
    with patch.dict(os.environ, {"INPUT_MANIFEST_URI": "not-a-s3-uri"}, clear=False):
        with patch.object(sm, "_build_minio_client_from_env", return_value=MagicMock()):
            with pytest.raises(RuntimeError, match="Invalid INPUT_MANIFEST_URI format"):
                sm._build_job_from_manifest("not-a-s3-uri")


def test_input_manifest_download():
    """With mocked MinIO client, manifest is downloaded and parsed."""
    manifest_data = {"profile": {"matrix_size": 2048, "batch_count": 2, "seed": 55}}
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.read.return_value = json.dumps(manifest_data).encode()
    mock_client.get_object.return_value = mock_result

    with patch.dict(
        os.environ, {"INPUT_MANIFEST_URI": "s3://task-inputs/user-1/manifest.json"}, clear=False
    ):
        with patch.object(sm, "_build_minio_client_from_env", return_value=mock_client):
            job = sm._build_job_from_manifest("s3://task-inputs/user-1/manifest.json")
            assert job["matrix_size"] == 2048
            assert job["batch_count"] == 2
            assert job["seed"] == 55


def test_input_manifest_fallback_to_top_level_fields():
    """Manifest without 'profile' falls back to top-level fields."""
    manifest_data = {"matrix_size": 1024, "batch_count": 5, "seed": 10}
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.read.return_value = json.dumps(manifest_data).encode()
    mock_client.get_object.return_value = mock_result

    with patch.dict(
        os.environ, {"INPUT_MANIFEST_URI": "s3://task-inputs/user-1/manifest.json"}, clear=False
    ):
        with patch.object(sm, "_build_minio_client_from_env", return_value=mock_client):
            job = sm._build_job_from_manifest("s3://task-inputs/user-1/manifest.json")
            assert job["matrix_size"] == 1024
            assert job["batch_count"] == 5
            assert job["seed"] == 10
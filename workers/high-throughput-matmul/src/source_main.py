#!/usr/bin/env python3
"""Matmul pipeline source: POST job to compute via HTTP."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (
    get_listen_port,
    post_json_to_peer,
    PostDataHandler,
    start_server,
)
from _common.object_io import (
    build_minio_client,
    download_json_object,
    parse_s3_uri,
)


def _parse_json_env(name: str, default: dict | None = None) -> dict:
    raw = os.environ.get(name, "")
    if not raw:
        return default or {}
    return json.loads(raw)


def _build_minio_client_from_env():
    """Build MinIO client from environment variables, or None if credentials are missing."""
    access = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER")
    secret = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD")
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://host.docker.internal:9000")
    if not access or not secret:
        return None
    return build_minio_client(endpoint, access, secret)


def _build_job_from_inputs() -> dict:
    """Build matmul job from INPUT_* environment variables or DATA_PROFILE fallback."""
    manifest_uri = os.environ.get("INPUT_MANIFEST_URI", "")
    if manifest_uri:
        return _build_job_from_manifest(manifest_uri)

    input_objects_raw = os.environ.get("INPUT_OBJECTS", "")
    if input_objects_raw:
        return _build_job_from_input_objects(input_objects_raw)

    return _build_job_from_data_profile()


def _build_job_from_manifest(manifest_uri: str) -> dict:
    """Download and parse manifest from MinIO, build job from it."""
    client = _build_minio_client_from_env()
    if not client:
        raise RuntimeError("INPUT_MANIFEST_URI is set but MinIO credentials are missing")

    try:
        bucket, key = parse_s3_uri(manifest_uri)
    except ValueError as exc:
        raise RuntimeError(f"Invalid INPUT_MANIFEST_URI format: {exc}")

    try:
        manifest = download_json_object(client, bucket, key)
    except Exception as exc:
        raise RuntimeError(f"Failed to download manifest from {manifest_uri}: {exc}")

    # manifest may contain profile and/or objects
    profile = manifest.get("profile", {})
    # extract matrix_size, batch_count, seed from profile or manifest top-level
    matrix_size = profile.get("matrix_size") or manifest.get("matrix_size", 512)
    batch_count = profile.get("batch_count") or manifest.get("batch_count", 4)
    seed = profile.get("seed") or manifest.get("seed", 42)

    job = {
        "matrix_size": int(matrix_size),
        "batch_count": int(batch_count),
        "seed": int(seed),
        "profile_id": profile.get("profile_id", "matmul_manifest"),
    }
    return job


def _build_job_from_input_objects(input_objects_raw: str) -> dict:
    """Parse INPUT_OBJECTS as JSON array of S3 URIs, download and merge into DATA_PROFILE."""
    try:
        input_objects = json.loads(input_objects_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"INPUT_OBJECTS is not valid JSON: {exc}")

    if not isinstance(input_objects, list):
        raise RuntimeError(f"INPUT_OBJECTS must be a JSON array, got {type(input_objects).__name__}")

    client = _build_minio_client_from_env()
    if not client:
        raise RuntimeError("INPUT_OBJECTS is set but MinIO credentials are missing")

    # start with DATA_PROFILE as base
    job = _parse_json_env("DATA_PROFILE")

    for obj_uri in input_objects:
        if not isinstance(obj_uri, str):
            raise RuntimeError(f"INPUT_OBJECTS entries must be strings, got {type(obj_uri).__name__}")

        try:
            bucket, key = parse_s3_uri(obj_uri)
        except ValueError as exc:
            raise RuntimeError(f"Invalid S3 URI in INPUT_OBJECTS: {obj_uri} — {exc}")

        try:
            obj_data = download_json_object(client, bucket, key)
        except Exception as exc:
            raise RuntimeError(f"Failed to download object {obj_uri}: {exc}")

        # merge: INPUT_OBJECTS overrides DATA_PROFILE
        if isinstance(obj_data, dict):
            job.update(obj_data)

    return job


def _build_job_from_data_profile() -> dict:
    """Build job from DATA_PROFILE (synthetic fallback)."""
    profile = _parse_json_env("DATA_PROFILE")
    matrix_size = int(profile.get("matrix_size") or 512)
    batch_count = int(profile.get("batch_count") or 4)
    seed = int(profile.get("seed") or 42)

    job = {
        "matrix_size": matrix_size,
        "batch_count": batch_count,
        "seed": seed,
        "profile_id": profile.get("profile_id", "matmul_dev"),
    }
    for key in (
        "observation_duration_sec",
        "sample_interval_sec",
        "sample_batch_count",
        "warmup_batches",
        "min_samples",
        "max_samples",
    ):
        if profile.get(key) is not None:
            job[key] = profile[key]
    return job


def _source_listen_enabled() -> bool:
    raw = os.environ.get("SOURCE_LISTEN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def main() -> int:
    job = _build_job_from_inputs()

    listen_enabled = _source_listen_enabled()
    port = get_listen_port("source") if listen_enabled else None
    print(f"SOURCE_STARTING port={port or 'disabled'} job={job}", flush=True)

    if listen_enabled:
        # 自动化测评模式保留 source 监听，用于兼容受控三容器链路。
        time.sleep(2)
        start_server(port, PostDataHandler)

    # 直接 POST job 给 compute，带重试因为 compute 可能还在启动中
    # 推送成功即认为 job 已送达，后续 compute 会处理
    post_json_to_peer("source", "/data", job, timeout_sec=120.0)
    print(f"SOURCE_POSTED_JOB to compute", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SOURCE_FAILED {exc}", flush=True)
        sys.exit(1)

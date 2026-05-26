"""MinIO / S3 object storage helpers for worker containers."""

from __future__ import annotations

import re
from typing import Any


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse an s3:// URI into (bucket, key).

    Args:
        uri: An s3:// URI, e.g. "s3://my-bucket/path/to/object.json"

    Returns:
        A (bucket, key) tuple.

    Raises:
        ValueError: If the URI is not a valid s3:// URI.
    """
    match = re.match(r"^s3://([^/]+)/(.+)$", uri)
    if not match:
        raise ValueError(f"Invalid s3:// URI: {uri!r}")
    return match.group(1), match.group(2)


def build_minio_client(endpoint: str, access_key: str, secret_key: str) -> Any:
    """Build a Minio client from environment variables.

    Uses the 'minio' package if available, otherwise falls back to boto3.

    Args:
        endpoint: MinIO API endpoint URL (e.g. "http://host.docker.internal:9000")
        access_key: MinIO access key / username
        secret_key: MinIO secret key / password

    Returns:
        A Minio client instance (or boto3 S3 client as fallback).
    """
    # Try minio package first
    try:
        from minio import Minio

        host = endpoint.replace("http://", "").replace("https://", "")
        secure = endpoint.startswith("https://")
        return Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
    except ImportError:
        pass

    # Fall back to boto3
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def download_object(client: Any, bucket: str, key: str) -> bytes:
    """Download an object from MinIO/S3 as raw bytes.

    Args:
        client: A Minio or boto3 S3 client.
        bucket: The bucket name.
        key: The object key (path in bucket).

    Returns:
        The object's content as bytes.

    Raises:
        Exception: If the download fails.
    """
    import io

    try:
        # minio client
        result = client.get_object(bucket, key)
        return result.read()
    except AttributeError:
        pass

    # boto3 client
    response = client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def download_json_object(client: Any, bucket: str, key: str) -> dict[str, Any]:
    """Download a JSON object from MinIO/S3 and parse it.

    Args:
        client: A Minio or boto3 S3 client.
        bucket: The bucket name.
        key: The object key (path in bucket).

    Returns:
        The parsed JSON as a dict.

    Raises:
        ValueError: If the content is not valid JSON.
        Exception: If the download fails.
    """
    import json

    data = download_object(client, bucket, key)
    return json.loads(data.decode("utf-8"))


def ensure_bucket_exists(client: Any, bucket: str) -> None:
    """Ensure the bucket exists, creating it if necessary.

    Args:
        client: A Minio or boto3 S3 client.
        bucket: The bucket name.
    """
    try:
        # minio client
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        return
    except AttributeError:
        pass

    # boto3 client
    import botocore

    try:
        client.head_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError:
        client.create_bucket(Bucket=bucket)
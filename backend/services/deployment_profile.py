"""Central defaults for development and acceptance network profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeploymentProfile:
    name: str
    registry: str
    manager_api_base: str
    minio_endpoint: str


_PROFILE_DEFAULTS = {
    "current": DeploymentProfile(
        name="current",
        registry="10.112.244.94:5000",
        manager_api_base="http://10.112.244.94:8181",
        minio_endpoint="http://10.112.244.94:9000",
    ),
    "acceptance": DeploymentProfile(
        name="acceptance",
        registry="172.16.0.254:5000",
        manager_api_base="http://172.16.0.254:8181",
        minio_endpoint="http://172.16.0.254:9000",
    ),
}


def _normalize_profile_name(value: str | None) -> str:
    text = (value or "acceptance").strip().lower()
    if text in {"dev", "development", "campus"}:
        return "current"
    if text in {"accept", "acceptance", "prod", "production"}:
        return "acceptance"
    if text not in _PROFILE_DEFAULTS:
        raise ValueError(f"unsupported NETWORK_PROFILE={value!r}; expected current or acceptance")
    return text


def deployment_profile(profile_name: str | None = None) -> DeploymentProfile:
    name = _normalize_profile_name(profile_name or os.environ.get("NETWORK_PROFILE"))
    defaults = _PROFILE_DEFAULTS[name]
    return DeploymentProfile(
        name=name,
        registry=(os.environ.get("PRIVATE_REGISTRY") or defaults.registry).rstrip("/"),
        manager_api_base=(os.environ.get("MANAGER_API_BASE") or defaults.manager_api_base).rstrip("/"),
        minio_endpoint=(os.environ.get("MINIO_ENDPOINT") or defaults.minio_endpoint).rstrip("/"),
    )


def current_deployment_profile() -> DeploymentProfile:
    return deployment_profile()


def image_repo(name: str) -> str:
    clean_name = name.strip().lstrip("/")
    if not clean_name:
        raise ValueError("image name cannot be empty")
    return f"{current_deployment_profile().registry}/{clean_name}"


def image_ref(name: str, tag: str = "dev") -> str:
    clean_tag = (tag or "dev").strip()
    return f"{image_repo(name)}:{clean_tag}"

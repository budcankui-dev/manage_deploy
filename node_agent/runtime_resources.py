"""Docker 运行时参数解析：GPU / CPU / 内存 / 挂载。"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from docker.types import DeviceRequest, Mount

_GPU_SPLIT = re.compile(r"[\s,;]+")


def parse_gpu_spec(gpu_id: Optional[str]) -> list[DeviceRequest] | None:
    """解析 GPU：all | 单个 0 | 多个 0,1,2。"""
    if not gpu_id or not str(gpu_id).strip():
        return None

    raw = str(gpu_id).strip().lower()
    if raw in {"all", "*"}:
        return [DeviceRequest(count=-1, capabilities=[["gpu"]])]

    device_ids = [part.strip() for part in _GPU_SPLIT.split(str(gpu_id).strip()) if part.strip()]
    if not device_ids:
        return None

    return [DeviceRequest(device_ids=device_ids, capabilities=[["gpu"]])]


def _parse_memory_bytes(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if text.isdigit():
        return int(text)
    multipliers = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    if text[-1] in multipliers:
        return int(float(text[:-1]) * multipliers[text[-1]])
    return int(float(text))


def build_resource_kwargs(
    *,
    cpu_limit: Optional[float] = None,
    cpu_reservation: Optional[float] = None,
    cpu_shares: Optional[int] = None,
    cpuset_cpus: Optional[str] = None,
    cpu_quota: Optional[int] = None,
    cpu_period: Optional[int] = None,
    memory_limit: Optional[str] = None,
    memory_reservation: Optional[str] = None,
    memory_swap_limit: Optional[str] = None,
) -> dict[str, Any]:
    """组装 docker-py containers.run 资源参数。"""
    kwargs: dict[str, Any] = {}

    # CPU 上限：优先 nano_cpus (--cpus)，否则 quota/period
    if cpu_limit and cpu_limit > 0:
        kwargs["nano_cpus"] = int(cpu_limit * 1_000_000_000)
    elif cpu_quota and cpu_period:
        kwargs["cpu_quota"] = int(cpu_quota)
        kwargs["cpu_period"] = int(cpu_period)

    if cpu_shares is not None and cpu_shares > 0:
        kwargs["cpu_shares"] = int(cpu_shares)
    elif cpu_reservation and cpu_reservation > 0 and not cpu_shares:
        # 无显式 shares 时，按预留核数相对加权（1024 = 1 核基准）
        kwargs["cpu_shares"] = max(2, int(cpu_reservation * 1024))

    if cpuset_cpus and str(cpuset_cpus).strip():
        kwargs["cpuset_cpus"] = str(cpuset_cpus).strip()

    if cpu_quota and cpu_period and "cpu_quota" not in kwargs:
        kwargs["cpu_quota"] = int(cpu_quota)
        kwargs["cpu_period"] = int(cpu_period)

    mem_limit = _parse_memory_bytes(memory_limit)
    if mem_limit:
        kwargs["mem_limit"] = mem_limit

    mem_res = _parse_memory_bytes(memory_reservation)
    if mem_res:
        kwargs["mem_reservation"] = mem_res

    if memory_swap_limit is not None and str(memory_swap_limit).strip() != "":
        swap = str(memory_swap_limit).strip().lower()
        if swap == "-1":
            kwargs["memswap_limit"] = -1
        else:
            parsed_swap = _parse_memory_bytes(memory_swap_limit)
            if parsed_swap is not None:
                kwargs["memswap_limit"] = parsed_swap

    return kwargs


def _ensure_host_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _managed_host_path(data_root: str, task_id: str, node_id: str, key: str) -> str:
    safe_key = re.sub(r"[^\w.-]", "_", key.strip()) or "data"
    return str(Path(data_root) / task_id / node_id / safe_key)


def _normalize_mount_spec(raw: Any, target: str) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"target": target, "type": "bind", "source": raw, "auto_create": True, "read_only": False}
    if isinstance(raw, dict):
        return {
            "target": raw.get("target") or target,
            "type": (raw.get("type") or "bind").lower(),
            "source": raw.get("source") or raw.get("name") or raw.get("key") or "",
            "auto_create": raw.get("auto_create", True),
            "read_only": bool(raw.get("read_only", False)),
        }
    raise ValueError(f"无法解析挂载配置: {target}={raw!r}")


def resolve_mounts(
    *,
    task_id: str,
    node_id: str,
    volumes: Optional[dict[str, Any]] = None,
    volume_mounts: Optional[list[dict[str, Any]]] = None,
    data_root: str = "/var/lib/manage_deploy/tasks",
    docker_client=None,
) -> list[Mount]:
    """解析挂载：bind / named volume / managed（屏蔽节点目录差异）。"""
    specs: list[dict[str, Any]] = []

    for container_path, host_or_spec in (volumes or {}).items():
        specs.append(_normalize_mount_spec(host_or_spec, container_path))

    for item in volume_mounts or []:
        if isinstance(item, dict):
            specs.append(
                {
                    "target": item.get("target") or item.get("container") or "",
                    "type": (item.get("type") or "bind").lower(),
                    "source": item.get("source") or item.get("name") or item.get("key") or "",
                    "auto_create": item.get("auto_create", True),
                    "read_only": bool(item.get("read_only", False)),
                }
            )

    mounts: list[Mount] = []
    for spec in specs:
        target = spec["target"]
        mount_type = spec["type"]
        source = str(spec["source"]).strip()
        auto_create = spec["auto_create"]
        read_only = spec["read_only"]

        if not target:
            continue

        if mount_type == "managed":
            host_path = _managed_host_path(data_root, task_id, node_id, source or target.strip("/"))
            if auto_create:
                _ensure_host_dir(host_path)
            mounts.append(Mount(target=target, source=host_path, type="bind", read_only=read_only))
            continue

        if mount_type == "volume":
            vol_name = source or target.strip("/").replace("/", "-")
            if auto_create and docker_client is not None:
                try:
                    docker_client.volumes.get(vol_name)
                except Exception:
                    docker_client.volumes.create(name=vol_name)
            mounts.append(Mount(target=target, source=vol_name, type="volume", read_only=read_only))
            continue

        # bind (default)
        host_path = source
        if not host_path:
            raise ValueError(f"bind 挂载 {target} 缺少 source")
        if auto_create:
            _ensure_host_dir(host_path)
        mounts.append(Mount(target=target, source=host_path, type="bind", read_only=read_only))

    return mounts


def collect_host_resources() -> dict[str, Any]:
    """Collect host resource facts for the manager node registry.

    All fields are best-effort. Missing CUDA/NVIDIA tooling should not make
    node registration fail; the manager UI will show those fields as unsynced.
    """
    facts: dict[str, Any] = {
        "cpu_cores": os.cpu_count(),
        "cpu_model": _read_cpu_model(),
        "memory_mb": _read_memory_mb(),
        "gpu_count": 0,
        "gpu_model": None,
        "gpu_memory_mb": None,
        "driver_version": None,
        "cuda_version": None,
        "diagnostics": {},
    }
    nvidia = _collect_nvidia_smi()
    facts.update({key: value for key, value in nvidia.items() if key != "diagnostics"})
    facts["diagnostics"].update(nvidia.get("diagnostics") or {})
    return facts


def _read_cpu_model() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text(errors="ignore").splitlines():
                if line.lower().startswith("model name"):
                    value = line.split(":", 1)[-1].strip()
                    if value:
                        return value
        except OSError:
            pass
    return None


def _read_memory_mb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    try:
        for line in meminfo.read_text(errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    return round(int(parts[1]) / 1024)
    except (OSError, ValueError):
        return None
    return None


def _run_command(args: list[str], timeout: int = 5) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def _collect_nvidia_smi() -> dict[str, Any]:
    result: dict[str, Any] = {
        "gpu_count": 0,
        "gpu_model": None,
        "gpu_memory_mb": None,
        "driver_version": None,
        "cuda_version": None,
        "diagnostics": {},
    }

    code, stdout, stderr = _run_command([
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ])
    if code != 0:
        if stderr:
            result["diagnostics"]["nvidia_smi_error"] = stderr
        return result

    models: list[str] = []
    memories: list[int] = []
    driver_versions: list[str] = []
    for line in stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        model, memory, driver = parts[:3]
        if model:
            models.append(model)
        try:
            memories.append(round(float(memory)))
        except ValueError:
            pass
        if driver:
            driver_versions.append(driver)

    result["gpu_count"] = len(models)
    if models:
        # Keep common single-model display compact; mixed rigs remain readable.
        unique_models = list(dict.fromkeys(models))
        result["gpu_model"] = unique_models[0] if len(unique_models) == 1 else " / ".join(unique_models)
    if memories:
        result["gpu_memory_mb"] = memories[0] if len(set(memories)) == 1 else max(memories)
    if driver_versions:
        result["driver_version"] = driver_versions[0]

    result["cuda_version"] = _read_cuda_version_from_nvidia_smi()
    return result


def _read_cuda_version_from_nvidia_smi() -> str | None:
    code, stdout, _stderr = _run_command(["nvidia-smi"], timeout=5)
    if code != 0:
        return None
    match = re.search(r"CUDA Version:\s*([0-9.]+)", stdout)
    return match.group(1) if match else None

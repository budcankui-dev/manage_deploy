"""Docker 运行时 Pydantic 模型（与 node_agent 语义对齐）。"""

from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class PortDefSpec(BaseModel):
    """模板中定义的端口变量（实例创建时填具体端口号）。"""

    name: str = Field(..., description="变量名，如 api / grpc / metrics")
    label: Optional[str] = Field(default=None, description="用途说明")
    default: Optional[int] = Field(default=None, description="实例未填时的默认端口")


class MacroDefSpec(BaseModel):
    """模板级宏变量（实例创建时填具体值，注入所有节点 env）。"""

    name: str = Field(..., description="变量名，如 DB_URL / MINIO_ENDPOINT")
    label: Optional[str] = Field(default=None, description="用途说明")
    default: Optional[str] = Field(default=None, description="默认值")


class VolumeMountSpec(BaseModel):
    """挂载：bind / volume / managed。"""

    target: str = Field(..., description="容器内路径")
    type: str = Field(default="bind", description="bind | volume | managed")
    source: str = Field(default="", description="宿主机路径、卷名或 managed 键")
    auto_create: bool = True
    read_only: bool = False


class ContainerResources(BaseModel):
    """容器资源限制与预留。"""

    gpu_id: Optional[str] = Field(
        default=None,
        description='GPU：all | "0" | "0,1,2"',
    )
    cpu_limit: Optional[float] = Field(default=None, description="CPU 上限（核），→ NanoCPUs")
    cpu_reservation: Optional[float] = Field(
        default=None,
        description="CPU 预留（核），无 shares 时映射为 cpu_shares",
    )
    cpu_shares: Optional[int] = Field(default=None, description="CPU 权重，默认 1024")
    cpuset_cpus: Optional[str] = Field(default=None, description='绑核，如 "0-3"')
    cpu_quota: Optional[int] = Field(default=None, description="CPU 配额（微秒/周期）")
    cpu_period: Optional[int] = Field(default=None, description="CPU 周期（微秒），默认 100000")
    memory_limit: Optional[str] = Field(default=None, description="内存上限，如 512m / 4g")
    memory_reservation: Optional[str] = Field(default=None, description="内存预留（下限）")
    memory_swap_limit: Optional[str] = Field(
        default=None,
        description='Swap 上限；-1 表示等于 memory_limit（禁用 swap 扩展）',
    )


VolumeMap = dict[str, Union[str, dict[str, Any]]]

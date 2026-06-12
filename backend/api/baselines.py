"""Node baseline CRUD API — 管理节点基线性能数据。"""

import asyncio
import statistics
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Node as NodeModel, NodeBaseline

router = APIRouter(prefix="/api/baselines", tags=["baselines"])


class BaselineCreate(BaseModel):
    node_id: str
    task_type: str
    metric_key: str
    baseline_value: float
    operator: str = ">="
    unit: Optional[str] = None
    run_count: int = 3
    raw_values: Optional[list[float]] = None
    diagnostics: Optional[dict[str, Any]] = None


class BaselineResponse(BaseModel):
    id: str
    node_id: str
    node_hostname: Optional[str] = None
    task_type: str
    metric_key: str
    baseline_value: float
    operator: str
    unit: Optional[str] = None
    run_count: int
    raw_values: Optional[list[float]] = None
    diagnostics: Optional[dict[str, Any]] = None
    std_dev: Optional[float] = None
    stable: Optional[bool] = None
    created_at: Any
    updated_at: Optional[Any] = None


class BaselineUpdate(BaseModel):
    baseline_value: Optional[float] = None
    operator: Optional[str] = None
    unit: Optional[str] = None
    run_count: Optional[int] = None
    raw_values: Optional[list[float]] = None
    diagnostics: Optional[dict[str, Any]] = None


class BaselineRunRequest(BaseModel):
    node_id: str
    task_type: str
    runs: int = 3
    allow_local_fallback: bool = False


class BaselineRunResponse(BaseModel):
    status: str
    baseline_id: Optional[str] = None
    baseline_value: Optional[float] = None
    raw_values: Optional[list[float]] = None
    unit: Optional[str] = None
    std_dev: Optional[float] = None
    stable: Optional[bool] = None
    diagnostics: Optional[dict[str, Any]] = None


@router.post("/run", response_model=BaselineRunResponse)
async def run_baseline_endpoint(payload: BaselineRunRequest, db: AsyncSession = Depends(get_db)):
    """在指定 Node Agent 上运行基准测试并保存结果。"""
    from services.baseline_runner import BENCHMARK_PROFILES, run_baseline_on_node, run_benchmark

    node = (await db.execute(
        select(NodeModel).where(NodeModel.id == payload.node_id)
    )).scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if payload.task_type not in BENCHMARK_PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown task_type: {payload.task_type}")

    try:
        result = await run_baseline_on_node(
            node.agent_address,
            payload.task_type,
            payload.runs,
        )
    except Exception as exc:
        if not payload.allow_local_fallback:
            raise HTTPException(
                status_code=502,
                detail=f"Remote baseline failed on {node.hostname}: {exc}",
            ) from exc
        result = await asyncio.to_thread(run_benchmark, payload.task_type, payload.runs)

    existing = (await db.execute(
        select(NodeBaseline).where(
            NodeBaseline.node_id == payload.node_id,
            NodeBaseline.task_type == payload.task_type,
            NodeBaseline.metric_key == result["metric_key"],
        )
    )).scalar_one_or_none()

    if existing:
        existing.baseline_value = result["baseline_value"]
        existing.raw_values = result["raw_values"]
        existing.run_count = result["run_count"]
        existing.diagnostics = result.get("diagnostics")
        await db.commit()
        await db.refresh(existing)
        baseline_id = existing.id
    else:
        row = NodeBaseline(
            node_id=payload.node_id,
            task_type=payload.task_type,
            metric_key=result["metric_key"],
            baseline_value=result["baseline_value"],
            operator=result["operator"],
            unit=result["unit"],
            run_count=result["run_count"],
            raw_values=result["raw_values"],
            diagnostics=result.get("diagnostics"),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        baseline_id = row.id

    return BaselineRunResponse(
        status="completed",
        baseline_id=baseline_id,
        baseline_value=result["baseline_value"],
        raw_values=result["raw_values"],
        unit=result["unit"],
        std_dev=result.get("std_dev"),
        stable=result.get("stable"),
        diagnostics=result.get("diagnostics"),
    )


class BatchBaselineRunRequest(BaseModel):
    task_type: str = "high_throughput_matmul"
    runs: int = 3
    allow_local_fallback: bool = False


@router.post("/batch-run")
async def batch_run_baseline(payload: BatchBaselineRunRequest, db: AsyncSession = Depends(get_db)):
    """对所有可调度节点批量运行远程基准测试。"""
    from services.baseline_runner import BENCHMARK_PROFILES, run_baseline_on_node, run_benchmark

    if payload.task_type not in BENCHMARK_PROFILES:
        raise HTTPException(status_code=400, detail=f"不支持的任务类型: {payload.task_type}")

    nodes = (await db.execute(
        select(NodeModel).where(NodeModel.is_schedulable == True, NodeModel.deleted_at.is_(None))
    )).scalars().all()

    succeeded, failed = [], []
    for node in nodes:
        try:
            try:
                result = await run_baseline_on_node(
                    node.agent_address,
                    payload.task_type,
                    payload.runs,
                )
            except Exception:
                if not payload.allow_local_fallback:
                    raise
                result = await asyncio.to_thread(run_benchmark, payload.task_type, payload.runs)
            existing = (await db.execute(
                select(NodeBaseline).where(
                    NodeBaseline.node_id == node.id,
                    NodeBaseline.task_type == payload.task_type,
                    NodeBaseline.metric_key == result["metric_key"],
                )
            )).scalar_one_or_none()
            if existing:
                existing.baseline_value = result["baseline_value"]
                existing.raw_values = result["raw_values"]
                existing.run_count = result["run_count"]
                existing.diagnostics = result.get("diagnostics")
            else:
                db.add(NodeBaseline(
                    node_id=node.id, task_type=payload.task_type,
                    metric_key=result["metric_key"], baseline_value=result["baseline_value"],
                    operator=result["operator"], unit=result["unit"],
                    run_count=result["run_count"], raw_values=result["raw_values"],
                    diagnostics=result.get("diagnostics"),
                ))
            await db.commit()
            succeeded.append(node.hostname)
        except Exception as e:
            failed.append({"node": node.hostname, "error": str(e)})

    return {"succeeded": len(succeeded), "failed": failed, "nodes": succeeded}


def _baseline_stats(raw_values: Optional[list[float]]) -> tuple[float | None, bool | None]:
    if not raw_values:
        return None, None
    if len(raw_values) == 1:
        return 0.0, True
    median = statistics.median(raw_values)
    std_dev = statistics.stdev(raw_values)
    stable = std_dev < median * 0.10 if median > 0 else True
    return round(std_dev, 4), stable


@router.get("", response_model=list[BaselineResponse])
async def list_baselines(
    node_id: Optional[str] = None,
    task_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(NodeBaseline)
    if node_id:
        query = query.where(NodeBaseline.node_id == node_id)
    if task_type:
        query = query.where(NodeBaseline.task_type == task_type)
    result = await db.execute(query.order_by(NodeBaseline.created_at.desc()))
    baselines = result.scalars().all()
    # Enrich with hostname
    responses = []
    for b in baselines:
        std_dev, stable = _baseline_stats(b.raw_values)
        node = (await db.execute(
            select(NodeModel).where(NodeModel.id == b.node_id)
        )).scalar_one_or_none()
        responses.append(BaselineResponse(
            id=b.id,
            node_id=b.node_id,
            node_hostname=node.hostname if node else None,
            task_type=b.task_type,
            metric_key=b.metric_key,
            baseline_value=b.baseline_value,
            operator=b.operator,
            unit=b.unit,
            run_count=b.run_count,
            raw_values=b.raw_values,
            diagnostics=b.diagnostics,
            std_dev=std_dev,
            stable=stable,
            created_at=b.created_at,
            updated_at=b.updated_at,
        ))
    return responses


@router.post("", response_model=BaselineResponse, status_code=201)
async def create_baseline(payload: BaselineCreate, db: AsyncSession = Depends(get_db)):
    node = (await db.execute(
        select(NodeModel).where(NodeModel.id == payload.node_id)
    )).scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    existing = (await db.execute(
        select(NodeBaseline).where(
            NodeBaseline.node_id == payload.node_id,
            NodeBaseline.task_type == payload.task_type,
            NodeBaseline.metric_key == payload.metric_key,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Baseline already exists for this node/task_type/metric_key")

    row = NodeBaseline(
        node_id=payload.node_id,
        task_type=payload.task_type,
        metric_key=payload.metric_key,
        baseline_value=payload.baseline_value,
        operator=payload.operator,
        unit=payload.unit,
        run_count=payload.run_count,
        raw_values=payload.raw_values,
        diagnostics=payload.diagnostics,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return BaselineResponse(
        id=row.id,
        node_id=row.node_id,
        node_hostname=node.hostname,
        task_type=row.task_type,
        metric_key=row.metric_key,
        baseline_value=row.baseline_value,
        operator=row.operator,
        unit=row.unit,
        run_count=row.run_count,
        raw_values=row.raw_values,
        diagnostics=row.diagnostics,
        std_dev=_baseline_stats(row.raw_values)[0],
        stable=_baseline_stats(row.raw_values)[1],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/{baseline_id}", response_model=BaselineResponse)
async def update_baseline(
    baseline_id: str, payload: BaselineUpdate, db: AsyncSession = Depends(get_db)
):
    row = (await db.execute(
        select(NodeBaseline).where(NodeBaseline.id == baseline_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Baseline not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)

    node = (await db.execute(
        select(NodeModel).where(NodeModel.id == row.node_id)
    )).scalar_one_or_none()
    return BaselineResponse(
        id=row.id,
        node_id=row.node_id,
        node_hostname=node.hostname if node else None,
        task_type=row.task_type,
        metric_key=row.metric_key,
        baseline_value=row.baseline_value,
        operator=row.operator,
        unit=row.unit,
        run_count=row.run_count,
        raw_values=row.raw_values,
        diagnostics=row.diagnostics,
        std_dev=_baseline_stats(row.raw_values)[0],
        stable=_baseline_stats(row.raw_values)[1],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/{baseline_id}", status_code=204)
async def delete_baseline(baseline_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(NodeBaseline).where(NodeBaseline.id == baseline_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Baseline not found")
    await db.delete(row)
    await db.commit()

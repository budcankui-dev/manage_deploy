"""Node baseline CRUD API — 管理节点基线性能数据。"""

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
    created_at: Any
    updated_at: Optional[Any] = None


class BaselineUpdate(BaseModel):
    baseline_value: Optional[float] = None
    operator: Optional[str] = None
    unit: Optional[str] = None
    run_count: Optional[int] = None
    raw_values: Optional[list[float]] = None


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

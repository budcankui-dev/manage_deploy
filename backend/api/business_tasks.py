import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from enums import OrderStatus
from models import (
    BusinessObjectiveEvaluation,
    BusinessTemplateCatalog,
    TaskOrder,
    TaskResultObject,
)
from schemas import (
    BusinessObjective,
    BusinessObjectiveEvaluationResponse,
    BusinessObjectiveEvaluationResult,
    BusinessTaskCreate,
    BusinessTaskResponse,
    BusinessTemplateCatalogCreate,
    BusinessTemplateCatalogResponse,
    TaskInstanceCreate,
    TaskInstanceNodeOverride,
    TaskResultObjectResponse,
)
from services.business_evaluator import evaluate_business_objective

from .instances import _create_instance_from_template

router = APIRouter(prefix="/api", tags=["business-tasks"])


def build_instance_create_from_business_task(
    payload: BusinessTaskCreate,
    template_id: str,
    role_node_names: dict[str, str],
) -> TaskInstanceCreate:
    shared_env = {
        "BUSINESS_TASK_ID": payload.external_task_id,
        "TASK_TYPE": payload.task_type,
        "MODALITY": payload.modality or "",
        "DATA_PROFILE": _json_env(payload.data_profile),
        "BUSINESS_OBJECTIVE": payload.business_objective.model_dump_json(),
        "RUNTIME_PLAN": _json_env(payload.runtime_plan),
        "RESOURCE_REQUIREMENT": _json_env(payload.resource_requirement),
        "ROUTING_RESULT": payload.routing_result.model_dump_json(),
        "RESULT_STORAGE": _json_env(payload.result_storage),
    }
    overrides: list[TaskInstanceNodeOverride] = []
    for role, template_node_name in role_node_names.items():
        node_id = payload.routing_result.placements.get(role)
        if not node_id:
            raise HTTPException(status_code=400, detail=f"Missing placement for role: {role}")
        env = dict(shared_env)
        env["TASK_ROLE"] = role
        overrides.append(
            TaskInstanceNodeOverride(
                template_node_name=template_node_name,
                node_id=node_id,
                env=env,
            )
        )

    return TaskInstanceCreate(
        template_id=template_id,
        name=payload.name or f"{payload.task_type}-{payload.external_task_id}",
        auto_start=payload.auto_start,
        node_overrides=overrides,
    )


@router.post("/business-template-catalog", response_model=BusinessTemplateCatalogResponse)
async def create_business_template_catalog(
    payload: BusinessTemplateCatalogCreate,
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == payload.task_type)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="task_type already exists")

    row = BusinessTemplateCatalog(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/business-template-catalog", response_model=list[BusinessTemplateCatalogResponse])
async def list_business_template_catalog(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(BusinessTemplateCatalog).order_by(BusinessTemplateCatalog.task_type.asc()))
    return rows.scalars().all()


@router.post("/business-tasks", response_model=BusinessTaskResponse)
async def create_business_task(payload: BusinessTaskCreate, db: AsyncSession = Depends(get_db)):
    existing_order = await db.execute(
        select(TaskOrder).where(TaskOrder.external_task_id == payload.external_task_id)
    )
    if existing_order.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="external_task_id already exists")

    catalog = await _get_catalog(db, payload.task_type)
    role_node_names = {
        "source": catalog.source_node_name,
        "compute": catalog.compute_node_name,
        "sink": catalog.sink_node_name,
    }
    instance_create = build_instance_create_from_business_task(
        payload,
        template_id=catalog.template_id,
        role_node_names=role_node_names,
    )

    order = TaskOrder(
        external_task_id=payload.external_task_id,
        template_id=catalog.template_id,
        name=instance_create.name,
        description=payload.description,
        auto_start=payload.auto_start,
        runtime_config={
            "business_task": payload.model_dump(mode="json"),
            "node_overrides": [item.model_dump() for item in instance_create.node_overrides],
        },
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()

    try:
        instance = await _create_instance_from_template(db, instance_create, source_order_id=order.id)
        order.materialized_instance_id = instance.id
        order.status = OrderStatus.MATERIALIZED
        order.error_message = None
        await db.commit()
        return BusinessTaskResponse(
            order_id=order.id,
            instance_id=instance.id,
            task_type=payload.task_type,
            status="materialized",
        )
    except Exception as exc:
        order.status = OrderStatus.FAILED
        order.error_message = str(exc)
        await db.commit()
        raise


@router.get("/business-tasks/{instance_id}/evaluation", response_model=BusinessObjectiveEvaluationResponse)
async def get_business_task_evaluation(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BusinessObjectiveEvaluation)
        .where(BusinessObjectiveEvaluation.instance_id == instance_id)
        .order_by(BusinessObjectiveEvaluation.created_at.desc())
    )
    row = result.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Business evaluation not found")
    return row


@router.get("/business-tasks/{instance_id}/results", response_model=list[TaskResultObjectResponse])
async def list_business_task_results(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskResultObject)
        .where(TaskResultObject.instance_id == instance_id)
        .order_by(TaskResultObject.created_at.asc())
    )
    return result.scalars().all()


@router.get("/business-tasks/summary")
async def business_task_summary(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(
            BusinessObjectiveEvaluation.task_type,
            BusinessObjectiveEvaluation.routing_strategy,
            func.count(BusinessObjectiveEvaluation.id),
            func.sum(BusinessObjectiveEvaluation.business_success),
            func.avg(BusinessObjectiveEvaluation.estimation_error_ratio),
        )
        .group_by(BusinessObjectiveEvaluation.task_type, BusinessObjectiveEvaluation.routing_strategy)
    )
    return [
        {
            "task_type": row[0],
            "routing_strategy": row[1],
            "count": row[2],
            "success_count": int(row[3] or 0),
            "business_success_rate": float((row[3] or 0) / row[2]) if row[2] else 0.0,
            "avg_estimation_error_ratio": float(row[4]) if row[4] is not None else None,
        }
        for row in rows.all()
    ]


async def evaluate_and_store_business_metric(
    db: AsyncSession,
    instance_id: str,
    metric_key: str,
    metric_value: float,
    tags: dict[str, Any] | None,
) -> BusinessObjectiveEvaluation | None:
    order = await _get_order_for_instance(db, instance_id)
    if not order or not order.runtime_config:
        return None

    business_task = order.runtime_config.get("business_task") or order.runtime_config.get("extra")
    if not business_task:
        return None

    objective_data = business_task.get("business_objective")
    if not objective_data:
        return None

    objective = BusinessObjective(**objective_data)
    routing_result = business_task.get("routing_result") or {}
    estimated_metric = routing_result.get("estimated_metric") or {}
    estimated_value = estimated_metric.get("metric_value")
    object_uris = _extract_object_uris(tags)
    evaluation = evaluate_business_objective(
        objective,
        actual_metric_key=metric_key,
        actual_value=metric_value,
        object_uris=object_uris,
        task_type=business_task.get("task_type"),
        estimated_value=estimated_value,
    )
    row = BusinessObjectiveEvaluation(
        instance_id=instance_id,
        task_type=business_task.get("task_type") or "unknown",
        routing_strategy=routing_result.get("strategy"),
        metric_key=evaluation.metric_key,
        actual_value=evaluation.actual_value,
        target_value=evaluation.target_value,
        operator=evaluation.operator,
        unit=evaluation.unit,
        business_success=evaluation.business_success,
        failure_reason=evaluation.failure_reason,
        estimated_value=evaluation.estimated_value,
        estimation_error_ratio=evaluation.estimation_error_ratio,
        object_uris={"uris": evaluation.object_uris},
    )
    db.add(row)
    for obj in _extract_objects(tags):
        db.add(
            TaskResultObject(
                instance_id=instance_id,
                name=obj["name"],
                uri=obj["uri"],
                content_type=obj.get("content_type"),
            )
        )
    await db.flush()
    return row


async def _get_catalog(db: AsyncSession, task_type: str) -> BusinessTemplateCatalog:
    result = await db.execute(
        select(BusinessTemplateCatalog).where(BusinessTemplateCatalog.task_type == task_type)
    )
    catalog = result.scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=404, detail=f"Business template catalog not found: {task_type}")
    return catalog


async def _get_order_for_instance(db: AsyncSession, instance_id: str) -> TaskOrder | None:
    result = await db.execute(select(TaskOrder).where(TaskOrder.materialized_instance_id == instance_id))
    return result.scalar_one_or_none()


def _json_env(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _extract_object_uris(tags: dict[str, Any] | None) -> list[str]:
    return [item["uri"] for item in _extract_objects(tags)]


def _extract_objects(tags: dict[str, Any] | None) -> list[dict[str, str]]:
    if not tags:
        return []
    raw_objects = tags.get("objects")
    if isinstance(raw_objects, list):
        return [
            item
            for item in raw_objects
            if isinstance(item, dict) and item.get("name") and item.get("uri")
        ]
    raw_uris = tags.get("object_uris") or []
    if isinstance(raw_uris, list):
        return [
            {"name": uri.rsplit("/", 1)[-1] or "object", "uri": uri}
            for uri in raw_uris
            if isinstance(uri, str)
        ]
    return []


__all__ = ["build_instance_create_from_business_task", "evaluate_business_objective"]

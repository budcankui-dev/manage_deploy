from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import (
    BusinessTemplateCatalog,
    TaskInstance,
    TaskMetric,
    TaskOrder,
    TaskTemplate,
    TaskTemplateNode,
    TaskTemplateEdge,
)
from schemas import (
    TaskTemplateCreate,
    TaskTemplateUpdate,
    TaskTemplateResponse,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


async def _get_template_by_name(db: AsyncSession, name: str) -> TaskTemplate | None:
    result = await db.execute(select(TaskTemplate).where(TaskTemplate.name == name))
    return result.scalar_one_or_none()


async def _ensure_unique_template_name(
    db: AsyncSession,
    name: str,
    exclude_id: str | None = None,
) -> None:
    existing = await _get_template_by_name(db, name)
    if existing and existing.id != exclude_id:
        raise HTTPException(status_code=409, detail=f"模板名称「{name}」已存在")


async def _count_template_references(db: AsyncSession, template_id: str) -> dict[str, int]:
    """Return references that make a template part of existing evidence."""
    checks = {
        "task_instances": select(func.count(TaskInstance.id)).where(TaskInstance.template_id == template_id),
        "task_orders": select(func.count(TaskOrder.id)).where(TaskOrder.template_id == template_id),
        "business_catalogs": select(func.count(BusinessTemplateCatalog.id)).where(
            BusinessTemplateCatalog.template_id == template_id
        ),
        "task_metrics": select(func.count(TaskMetric.id)).where(TaskMetric.template_id == template_id),
    }
    counts: dict[str, int] = {}
    for key, query in checks.items():
        counts[key] = int((await db.execute(query)).scalar_one() or 0)
    return counts


def _template_reference_message(counts: dict[str, int]) -> str:
    labels = {
        "task_instances": "任务实例",
        "task_orders": "任务工单",
        "business_catalogs": "业务模板目录",
        "task_metrics": "历史指标",
    }
    parts = [f"{labels[key]} {count} 条" for key, count in counts.items() if count > 0]
    return (
        "模板已被"
        + "、".join(parts)
        + "引用，不能直接删除。请先清理关联实例/工单，或取消业务模板目录绑定后再删除。"
    )


async def _populate_template_graph(
    db: AsyncSession,
    db_template: TaskTemplate,
    nodes_data,
    edges_data,
):
    node_id_map = {}
    for node_data in nodes_data:
        node_payload = node_data.model_dump(exclude={"client_id"})
        db_node = TaskTemplateNode(
            template_id=db_template.id,
            **node_payload,
        )
        db.add(db_node)
        await db.flush()
        node_id_map[node_data.client_id or node_data.node_id] = db_node.id

    for edge_data in edges_data:
        db_edge = TaskTemplateEdge(
            template_id=db_template.id,
            from_node_id=node_id_map.get(edge_data.from_node_id, edge_data.from_node_id),
            to_node_id=node_id_map.get(edge_data.to_node_id, edge_data.to_node_id),
        )
        db.add(db_edge)


@router.post("", response_model=TaskTemplateResponse)
async def create_template(
    template: TaskTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    await _ensure_unique_template_name(db, template.name)

    nodes_data = template.nodes
    edges_data = template.edges
    template_data = template.model_dump(exclude={"nodes", "edges"})

    db_template = TaskTemplate(**template_data)
    db.add(db_template)
    await db.flush()

    await _populate_template_graph(db, db_template, nodes_data, edges_data)

    await db.commit()

    result = await db.execute(
        select(TaskTemplate)
        .options(
            selectinload(TaskTemplate.nodes),
            selectinload(TaskTemplate.edges),
        )
        .where(TaskTemplate.id == db_template.id)
    )
    db_template = result.scalar_one()

    return db_template


@router.get("", response_model=list[TaskTemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskTemplate).options(
            selectinload(TaskTemplate.nodes),
            selectinload(TaskTemplate.edges),
        )
    )
    templates = result.scalars().all()
    return templates


@router.get("/{template_id}", response_model=TaskTemplateResponse)
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskTemplate)
        .options(
            selectinload(TaskTemplate.nodes),
            selectinload(TaskTemplate.edges),
        )
        .where(TaskTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/{template_id}", response_model=TaskTemplateResponse)
async def update_template(
    template_id: str,
    template: TaskTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskTemplate)
        .options(
            selectinload(TaskTemplate.nodes),
            selectinload(TaskTemplate.edges),
        )
        .where(TaskTemplate.id == template_id)
    )
    db_template = result.scalar_one_or_none()
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = template.model_dump(exclude_unset=True, exclude={"nodes", "edges"})
    new_name = update_data.get("name")
    if new_name is not None:
        await _ensure_unique_template_name(db, new_name, exclude_id=template_id)

    for field, value in update_data.items():
        setattr(db_template, field, value)

    if template.nodes is not None or template.edges is not None:
        db_template.edges.clear()
        db_template.nodes.clear()
        await db.flush()
        await _populate_template_graph(
            db,
            db_template,
            template.nodes or [],
            template.edges or [],
        )

    await db.commit()
    result = await db.execute(
        select(TaskTemplate)
        .options(
            selectinload(TaskTemplate.nodes),
            selectinload(TaskTemplate.edges),
        )
        .where(TaskTemplate.id == template_id)
    )
    return result.scalar_one()


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TaskTemplate).where(TaskTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    reference_counts = await _count_template_references(db, template_id)
    if any(count > 0 for count in reference_counts.values()):
        raise HTTPException(
            status_code=409,
            detail=_template_reference_message(reference_counts),
        )

    await db.delete(template)
    await db.commit()
    return {"message": "模板已删除"}

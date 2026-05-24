from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import TaskTemplate, TaskTemplateNode, TaskTemplateEdge
from schemas import (
    TaskTemplateCreate,
    TaskTemplateUpdate,
    TaskTemplateResponse,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


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

    await db.delete(template)
    await db.commit()
    return {"message": "Template deleted"}

"""Scheduled lifecycle auto cleanup 相关测试。

覆盖：
1. TaskInstanceCreate / TaskOrderCreate 在 SCHEDULED + 缺 end_time 时自动补 start+2h。
2. POST /api/business-tasks 走 SCHEDULED 默认填充 end_time。
3. IMMEDIATE 模式行为不变（end_time 可空，不会自动写入）。
4. keep_after_stop 字段持久化与读出。
5. auto_cleanup_instance / mark_orders_completed_for_instance 物理清理实例 + 工单 COMPLETED。
6. restore_pending_jobs 会重注册未到期的 end job。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from enums import DeploymentMode, OrderStatus, TaskStatus
from models import Node, TaskInstance, TaskOrder, TaskTemplate, TaskTemplateNode
from schemas import TaskInstanceCreate, TaskOrderCreate
from services.instance_lifecycle import auto_cleanup_instance
from services.order_sync import mark_orders_completed_for_instance
from services.scheduler import TaskScheduler, restore_pending_jobs, scheduler as ap_scheduler


# ---------- schema 默认值 ----------


def test_task_instance_create_scheduled_fills_default_end_time():
    start = datetime.utcnow() + timedelta(minutes=30)
    payload = TaskInstanceCreate(
        template_id="tpl-1",
        name="demo",
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=start,
    )
    assert payload.scheduled_end_time is not None
    delta = payload.scheduled_end_time - payload.scheduled_start_time
    assert delta == timedelta(hours=2)


def test_task_instance_create_scheduled_defaults_start_to_now():
    payload = TaskInstanceCreate(
        template_id="tpl-1",
        name="demo",
        deployment_mode=DeploymentMode.SCHEDULED,
    )
    assert payload.scheduled_start_time is not None
    assert payload.scheduled_end_time is not None
    delta = payload.scheduled_end_time - payload.scheduled_start_time
    assert delta == timedelta(hours=2)


def test_task_instance_create_immediate_does_not_inject_defaults():
    payload = TaskInstanceCreate(
        template_id="tpl-1",
        name="demo",
        deployment_mode=DeploymentMode.IMMEDIATE,
    )
    assert payload.scheduled_start_time is None
    assert payload.scheduled_end_time is None
    assert payload.keep_after_stop is False


def test_task_order_create_scheduled_fills_default_end_time():
    payload = TaskOrderCreate(
        template_id="tpl-1",
        name="demo",
        deployment_mode=DeploymentMode.SCHEDULED,
    )
    assert payload.scheduled_start_time is not None
    assert payload.scheduled_end_time is not None
    delta = payload.scheduled_end_time - payload.scheduled_start_time
    assert delta == timedelta(hours=2)


# ---------- 数据库辅助：直接造一个 instance + order ----------


@pytest_asyncio.fixture
async def seeded_instance(db_session):
    # 注册 worker 节点
    node = Node(
        hostname="worker-l",
        agent_address="http://127.0.0.1:8011",
        management_ip="10.0.0.11",
        business_ip="10.0.1.11",
    )
    db_session.add(node)
    await db_session.flush()

    # 模板 + 1 个节点
    template = TaskTemplate(name="lifecycle-demo", description="t")
    db_session.add(template)
    await db_session.flush()

    t_node = TaskTemplateNode(
        template_id=template.id,
        name="single",
        image="busybox:latest",
        command="sleep 3600",
        node_id=node.id,
    )
    db_session.add(t_node)
    await db_session.flush()

    # 实例 + 节点
    now = datetime.utcnow()
    instance = TaskInstance(
        template_id=template.id,
        name="lifecycle-instance",
        status=TaskStatus.RUNNING,
        scheduled_start_time=now,
        scheduled_end_time=now + timedelta(hours=2),
        keep_after_stop=False,
    )
    db_session.add(instance)
    await db_session.flush()

    # 工单（MATERIALIZED）
    order = TaskOrder(
        external_task_id="lc-001",
        template_id=template.id,
        name="lifecycle-order",
        deployment_mode=DeploymentMode.SCHEDULED,
        scheduled_start_time=now,
        scheduled_end_time=now + timedelta(hours=2),
        status=OrderStatus.MATERIALIZED,
        materialized_instance_id=instance.id,
        runtime_config={"business_task": {"task_type": "demo"}},
    )
    db_session.add(order)
    await db_session.flush()

    return instance.id, order.id


# ---------- order_sync ----------


@pytest.mark.asyncio
async def test_mark_orders_completed_only_affects_materialized(db_session, seeded_instance):
    instance_id, order_id = seeded_instance

    affected = await mark_orders_completed_for_instance(db_session, instance_id)
    assert affected == 1
    await db_session.flush()

    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    ).scalar_one()
    assert order.status == OrderStatus.COMPLETED
    # 保留 instance 引用，由 instance_exists 字段呈现是否还在
    assert order.materialized_instance_id == instance_id

    # 二次调用幂等：状态已是 COMPLETED 不再被覆盖
    affected = await mark_orders_completed_for_instance(db_session, instance_id)
    assert affected == 0


# ---------- instance_lifecycle ----------


@pytest.mark.asyncio
async def test_auto_cleanup_instance_deletes_instance(db_session, seeded_instance):
    instance_id, order_id = seeded_instance

    instance = (
        await db_session.execute(
            select(TaskInstance)
            .options(selectinload(TaskInstance.nodes))
            .where(TaskInstance.id == instance_id)
        )
    ).scalar_one()

    # 先标 COMPLETED（scheduler 实际流程是先 mark 再 cleanup）
    await mark_orders_completed_for_instance(db_session, instance_id)
    warnings = await auto_cleanup_instance(db_session, instance)
    await db_session.commit()

    # instance 应已物理删除
    remaining = (
        await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance_id))
    ).scalar_one_or_none()
    assert remaining is None, "auto_cleanup_instance 应删除 instance"

    # 工单仍存在且状态为 COMPLETED
    order = (
        await db_session.execute(select(TaskOrder).where(TaskOrder.id == order_id))
    ).scalar_one()
    assert order.status == OrderStatus.COMPLETED

    # warnings 不应该挂掉（节点表无对应 worker container，所以 remove_node 应该顺利 noop）
    assert isinstance(warnings, list)


# ---------- scheduler.restore_pending_jobs ----------


@pytest.mark.asyncio
async def test_restore_pending_jobs_registers_future_end_jobs(db_session, seeded_instance):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    instance_id, _order_id = seeded_instance

    # 清理 scheduler 中可能存在的旧 job
    job_id = f"end_{instance_id}"
    if ap_scheduler.get_job(job_id):
        ap_scheduler.remove_job(job_id)

    await db_session.commit()

    # 注入与 fixture 共享 engine 的 sessionmaker，保证 restore_pending_jobs 看得见数据
    test_session_maker = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    await restore_pending_jobs(session_maker=test_session_maker)

    job = ap_scheduler.get_job(job_id)
    assert job is not None, "restore_pending_jobs 应重注册未到期的 end job"

    # 清理副作用
    ap_scheduler.remove_job(job_id)


@pytest.mark.asyncio
async def test_schedule_task_start_treats_naive_time_as_configured_timezone():
    run_time = datetime.now() + timedelta(minutes=5)
    instance_id = "tz-naive-demo"
    job_id = f"start_{instance_id}"
    if ap_scheduler.get_job(job_id):
        ap_scheduler.remove_job(job_id)

    task_scheduler = TaskScheduler()
    await task_scheduler.schedule_task_start(instance_id, run_time)

    job = ap_scheduler.get_job(job_id)
    assert job is not None
    assert str(job.trigger.run_date.tzinfo) == "Asia/Shanghai"
    assert job.trigger.run_date.hour == run_time.hour
    assert job.trigger.run_date.minute == run_time.minute

    ap_scheduler.remove_job(job_id)


@pytest.mark.asyncio
async def test_schedule_task_start_reschedules_due_time_to_near_future():
    run_time = datetime.now() - timedelta(seconds=2)
    instance_id = "tz-due-demo"
    job_id = f"start_{instance_id}"
    if ap_scheduler.get_job(job_id):
        ap_scheduler.remove_job(job_id)

    task_scheduler = TaskScheduler()
    await task_scheduler.schedule_task_start(instance_id, run_time)

    job = ap_scheduler.get_job(job_id)
    assert job is not None
    assert str(job.trigger.run_date.tzinfo) == "Asia/Shanghai"
    assert job.trigger.run_date.replace(tzinfo=None) > run_time

    ap_scheduler.remove_job(job_id)


@pytest.mark.asyncio
async def test_restore_pending_jobs_registers_overdue_running_end_jobs(db_session, seeded_instance):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    instance_id, _order_id = seeded_instance
    job_id = f"end_{instance_id}"
    if ap_scheduler.get_job(job_id):
        ap_scheduler.remove_job(job_id)

    instance = (
        await db_session.execute(select(TaskInstance).where(TaskInstance.id == instance_id))
    ).scalar_one()
    instance.status = TaskStatus.RUNNING
    instance.scheduled_end_time = datetime.utcnow() - timedelta(minutes=5)
    await db_session.commit()

    test_session_maker = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    await restore_pending_jobs(session_maker=test_session_maker)

    job = ap_scheduler.get_job(job_id)
    assert job is not None, "超时但仍运行的实例应在恢复时注册立即停止 job"
    assert job.trigger.run_date is not None

    ap_scheduler.remove_job(job_id)


@pytest.mark.asyncio
async def test_restore_pending_jobs_registers_overdue_running_end_job(db_session, seeded_instance):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    instance_id, _order_id = seeded_instance
    instance = await db_session.get(TaskInstance, instance_id)
    instance.status = TaskStatus.RUNNING
    instance.scheduled_end_time = datetime.utcnow() - timedelta(minutes=5)
    await db_session.commit()

    job_id = f"end_{instance_id}"
    if ap_scheduler.get_job(job_id):
        ap_scheduler.remove_job(job_id)

    test_session_maker = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    await restore_pending_jobs(session_maker=test_session_maker)

    job = ap_scheduler.get_job(job_id)
    assert job is not None, "超时仍运行的 scheduled 实例应在重启恢复时注册立即停止 job"
    assert job.trigger.run_date.replace(tzinfo=None) > datetime.utcnow() - timedelta(seconds=2)

    ap_scheduler.remove_job(job_id)


# ---------- API：business-tasks 默认 SCHEDULED + end_time ----------


async def _seed_minimum_business_fixture(client):
    node_ids = []
    for idx, hostname in enumerate(["lc-worker-a", "lc-worker-b", "lc-worker-c"], start=1):
        response = await client.post(
            "/api/nodes",
            json={
                "hostname": hostname,
                "agent_address": f"http://127.0.0.1:803{idx}",
                "management_ip": f"10.0.0.{20 + idx}",
                "business_ip": f"10.0.1.{20 + idx}",
            },
        )
        assert response.status_code == 200
        node_ids.append(response.json()["id"])

    template_response = await client.post(
        "/api/templates",
        json={
            "name": "lifecycle-business-tpl",
            "description": "lc",
            "nodes": [
                {"client_id": role, "name": role, "image": "busybox:latest", "command": "sleep 3600", "node_id": node_ids[i]}
                for i, role in enumerate(["source", "compute", "sink"])
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "compute"},
                {"from_node_id": "compute", "to_node_id": "sink"},
            ],
        },
    )
    assert template_response.status_code == 200
    template_id = template_response.json()["id"]

    catalog_response = await client.post(
        "/api/business-template-catalog",
        json={
            "task_type": "lifecycle_demo",
            "template_id": template_id,
            "source_node_name": "source",
            "compute_node_name": "compute",
            "sink_node_name": "sink",
        },
    )
    assert catalog_response.status_code == 200
    return node_ids, template_id


@pytest.mark.asyncio
async def test_business_task_defaults_to_scheduled_with_end_time(client, db_session):
    node_ids, _template_id = await _seed_minimum_business_fixture(client)

    payload = {
        "external_task_id": "lc-bt-001",
        "task_type": "lifecycle_demo",
        "name": "lifecycle business",
        "data_profile": {"profile_id": "demo"},
        "business_objective": {
            "metric_key": "end_to_end_latency_ms",
            "operator": "<=",
            "target_value": 1000,
            "unit": "ms",
        },
        "routing_result": {
            "strategy": "completion_time_first",
            "placements": [
                {"task_node_id": "source", "topology_node_id": "lc-worker-a"},
                {"task_node_id": "compute", "topology_node_id": "lc-worker-b", "gpu_device": "0"},
                {"task_node_id": "sink", "topology_node_id": "lc-worker-c"},
            ],
        },
    }
    response = await client.post("/api/business-tasks", json=payload)
    assert response.status_code == 200
    body = response.json()

    # 读 instance 查 scheduled_*
    instance_response = await client.get(f"/api/instances/{body['instance_id']}")
    assert instance_response.status_code == 200
    instance = instance_response.json()
    assert instance["status"] == "scheduled"
    assert instance["scheduled_start_time"] is not None
    assert instance["scheduled_end_time"] is not None
    assert instance["keep_after_stop"] is False
    start = datetime.fromisoformat(instance["scheduled_start_time"])
    end = datetime.fromisoformat(instance["scheduled_end_time"])
    assert (end - start) == timedelta(hours=2)

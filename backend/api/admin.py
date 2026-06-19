"""管理员专用 API。

提供跨用户的对话审计、路由审计、用户管理和意图解析测试能力。
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import get_current_user, hash_password, require_admin
from database import get_db
from enums import RoutingRequestStatus, UserRole
from models import Conversation, ConversationMessage, IntentDraft, Node, RoutingRequest, TaskOrder, User
from schemas import UserResponse
from schemas.conversation import (
    ConversationResponse,
    ConversationSummary,
    IntentDraftResponse,
    RoutingRequestResponse,
)
from services.intent_batch_eval import (
    VALID_NODES,
    BATCH_DIR,
    DATASET_PATH,
    LLM_REPORT_PATH,
    RULE_REPORT_PATH,
    latest_status,
    cancel_latest_llm_batch,
    read_report,
    read_latest_batch_job,
    refresh_latest_llm_batch,
    run_rule_evaluation,
    submit_llm_batch_evaluation,
    score_parsed_result,
)
from services.intent_online_eval import (
    ONLINE_REPORT_PATH,
    DEFAULT_ONLINE_EVAL_CONCURRENCY,
    DEFAULT_ONLINE_EVAL_RETRIES,
    DEFAULT_ONLINE_EVAL_RETRY_DELAY_SECONDS,
    fail_online_evaluation,
    online_evaluation_is_running,
    read_online_status,
    run_online_evaluation,
    start_online_evaluation,
)
from services.intent_workflow import run_intent_workflow
from services.endpoint_resolver import is_user_endpoint_node
from services.routing_payload_builder import build_routing_payload
from services.system_settings import (
    get_runtime_settings,
    modality_priority_map_from_settings,
    routing_resource_options_from_settings,
    update_runtime_settings,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _format_dt(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.replace(microsecond=0).isoformat(sep=" ")


def _parse_result_payload(result) -> dict[str, Any]:
    return {
        "task_type": result.task_type,
        "modality": result.modality,
        "source_name": result.source_name,
        "destination_name": result.destination_name,
        "business_start_time": _format_dt(result.business_start_time),
        "business_end_time": _format_dt(result.business_end_time),
        "data_profile": result.data_profile,
        "business_objective": result.business_objective,
        "runtime_plan": result.runtime_plan,
        "resource_requirement": result.resource_requirement,
        "parse_status": result.parse_status,
        "validation_errors": result.validation_errors,
        "assistant_message": result.assistant_message,
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
    }


def _optional_int(payload: dict[str, Any], key: str, default: int | None = None) -> int | None:
    value = payload.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _optional_float(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key)
    if value is None or value == "":
        return default
    return float(value)


def _optional_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def _online_eval_params(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": payload.get("model"),
        "limit": _optional_int(payload, "limit"),
        "concurrency": _optional_int(payload, "concurrency", DEFAULT_ONLINE_EVAL_CONCURRENCY),
        "retries": _optional_int(payload, "retries", DEFAULT_ONLINE_EVAL_RETRIES),
        "retry_delay_seconds": _optional_float(
            payload,
            "retry_delay_seconds",
            DEFAULT_ONLINE_EVAL_RETRY_DELAY_SECONDS,
        ),
        "resume": _optional_bool(payload, "resume", False),
    }


def _node_endpoint_payload(node: Node | None) -> dict[str, Any] | None:
    if not node:
        return None
    return {
        "hostname": node.hostname,
        "display_name": node.display_name,
        "topology_node_id": node.topology_node_id,
        "topology_zone": node.topology_zone,
        "management_ip": node.management_ip,
        "business_ip": node.business_ip,
        "business_ipv6": node.business_ipv6,
        "node_kind": node.node_kind,
    }


async def _endpoint_map_for_names(db: AsyncSession, names: list[str | None]) -> dict[str, dict[str, Any]]:
    clean_names = sorted({name for name in names if name})
    if not clean_names:
        return {}
    rows = await db.execute(select(Node).where(Node.hostname.in_(clean_names), Node.deleted_at.is_(None)))
    return {node.hostname: _node_endpoint_payload(node) for node in rows.scalars().all()}


def _routing_dag_preview(
    result,
    order_id: str = "preview",
    runtime_settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not (
        result.task_type
        and result.source_name
        and result.destination_name
        and result.business_start_time
        and result.business_end_time
    ):
        return None
    resource_options = routing_resource_options_from_settings(runtime_settings)
    return build_routing_payload(
        order_id=order_id,
        order_name=f"{result.task_type}-{order_id}",
        task_type=result.task_type,
        modality=result.modality,
        source_name=result.source_name,
        destination_name=result.destination_name,
        business_start_time=result.business_start_time,
        business_end_time=result.business_end_time,
        data_profile=result.data_profile,
        resource_requirement=result.resource_requirement,
        modality_priority_map=modality_priority_map_from_settings(runtime_settings),
        routing_strategy=(result.runtime_plan or {}).get("routing_strategy"),
        **resource_options,
    )


# ─── 系统设置 ───────────────────────────────────────────────

@router.get("/system-settings")
async def get_system_settings(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return await get_runtime_settings(db)


@router.put("/system-settings")
async def put_system_settings(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await update_runtime_settings(db, payload, updated_by=admin.id)


# ─── 用户管理 ───────────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    return {"ok": True}


@router.post("/users", response_model=UserResponse)
async def admin_create_user(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    username = payload.get("username")
    password = payload.get("password")
    role_str = payload.get("role", UserRole.USER)
    if not username or not password:
        raise HTTPException(status_code=422, detail="username and password are required")
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="username already exists")
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role: {role_str}")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def admin_update_user(
    user_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if "role" in payload:
        try:
            user.role = UserRole(payload["role"])
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid role: {payload['role']}")
    if "password" in payload and payload["password"]:
        user.password_hash = hash_password(payload["password"])
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    order_count_r = await db.execute(
        select(func.count()).select_from(TaskOrder).where(TaskOrder.user_id == user_id)
    )
    order_count = order_count_r.scalar_one()
    conv_count_r = await db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )
    conv_count = conv_count_r.scalar_one()
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at,
        "order_count": order_count,
        "conversation_count": conv_count,
    }

# ─── 对话审计 ───────────────────────────────────────────────

@router.get("/conversations")
async def list_all_conversations(
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(Conversation).order_by(Conversation.updated_at.desc())
    if user_id:
        query = query.where(Conversation.user_id == user_id)
    if status:
        query = query.where(Conversation.status == status)
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    drafts_r = await db.execute(
        select(IntentDraft).where(IntentDraft.conversation_id == conversation_id)
        .order_by(IntentDraft.version.desc())
    )
    drafts = drafts_r.scalars().all()
    routing_r = await db.execute(
        select(RoutingRequest).where(RoutingRequest.conversation_id == conversation_id)
        .order_by(RoutingRequest.created_at.desc())
    )
    routings = routing_r.scalars().all()
    return {
        "conversation": conv,
        "messages": sorted(conv.messages, key=lambda m: m.created_at),
        "drafts": drafts,
        "routing_requests": routings,
    }


# ─── 路由审计 ───────────────────────────────────────────────

@router.get("/routing-requests")
async def list_all_routing_requests(
    status: str | None = Query(None),
    order_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(RoutingRequest).where(RoutingRequest.deleted_at.is_(None))
    if status:
        query = query.where(RoutingRequest.status == status)
    if order_id:
        query = query.where(RoutingRequest.order_id == order_id)
    query = query.order_by(RoutingRequest.created_at.desc())
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ─── 工单审计 ───────────────────────────────────────────────

@router.get("/orders")
async def list_all_orders(
    user_id: str | None = Query(None),
    routing_status: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = select(TaskOrder).where(TaskOrder.deleted_at.is_(None))
    if user_id:
        query = query.where(TaskOrder.user_id == user_id)
    if routing_status:
        query = query.where(TaskOrder.routing_status == routing_status)
    if status:
        query = query.where(TaskOrder.status == status)
    query = query.order_by(TaskOrder.created_at.desc())
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ─── 意图解析测试 ─────────────────────────────────────────────

@router.post("/intent-parser/parse-one")
async def parse_one(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员测试单条意图解析。"""
    utterance = payload.get("utterance", "")
    context = payload.get("context")
    expected = payload.get("expected")
    runtime_settings = await get_runtime_settings(db)
    nodes_result = await db.execute(
        select(Node).where(Node.deleted_at.is_(None)).order_by(Node.hostname.asc())
    )
    valid_nodes = [node.hostname for node in nodes_result.scalars().all() if is_user_endpoint_node(node)]
    result, trace = await run_intent_workflow(
        utterance,
        context,
        valid_nodes=valid_nodes,
        runtime_settings=runtime_settings,
    )
    response = _parse_result_payload(result)
    response["trace"] = trace
    response["engine"] = trace.get("engine")
    response["runtime_settings"] = runtime_settings
    response["model"] = trace.get("model")
    endpoints = await _endpoint_map_for_names(db, [result.source_name, result.destination_name])
    response["source_endpoint"] = endpoints.get(result.source_name or "")
    response["destination_endpoint"] = endpoints.get(result.destination_name or "")
    response["routing_dag"] = _routing_dag_preview(result, runtime_settings=runtime_settings)
    if isinstance(expected, dict):
        response["expected_result"] = expected
        response["scoring"] = score_parsed_result(result, expected)
    return response


@router.get("/intent-parser/evaluations/latest")
async def get_intent_eval_latest(
    _admin: User = Depends(require_admin),
):
    """返回固定意图数据集的最新评测摘要。"""
    return latest_status()


@router.get("/intent-parser/evaluations/reports/{report_type}")
async def get_intent_eval_report(
    report_type: str,
    _admin: User = Depends(require_admin),
):
    """读取完整评测报告。report_type 支持 rule、llm 或 online。"""
    report_paths = {
        "rule": RULE_REPORT_PATH,
        "llm": LLM_REPORT_PATH,
        "online": ONLINE_REPORT_PATH,
    }
    path = report_paths.get(report_type)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown report type: {report_type}")
    report = read_report(path)
    if not report:
        raise HTTPException(status_code=404, detail=f"{report_type} report not found")
    return report


@router.get("/intent-parser/evaluations/files/{file_type}")
async def download_intent_eval_file(
    file_type: str,
    _admin: User = Depends(require_admin),
):
    """下载固定数据集、评测报告和历史 Batch 相关文件。"""
    latest_job = read_latest_batch_job()
    paths = {
        "dataset": DATASET_PATH,
        "rule-report": RULE_REPORT_PATH,
        "llm-report": LLM_REPORT_PATH,
        "online-report": ONLINE_REPORT_PATH,
        "batch-job": BATCH_DIR / "latest.json",
    }
    if latest_job:
        job_dir = BATCH_DIR / latest_job["job_id"]
        paths["batch-input"] = job_dir / "input.jsonl"
        paths["batch-output"] = job_dir / "output.jsonl"

    path = paths.get(file_type)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown intent evaluation file: {file_type}")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_type}")

    media_type = "application/jsonl" if path.suffix == ".jsonl" else "application/json"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/intent-parser/evaluations/rule/run")
async def run_intent_eval_rule(
    _admin: User = Depends(require_admin),
):
    """运行固定数据集的本地规则解析评测，用于快速回归。"""
    return run_rule_evaluation()


@router.post("/intent-parser/evaluations/llm-online/run")
async def run_intent_eval_llm_online(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
    _admin: User = Depends(require_admin),
):
    """使用在线 chat/completions API 逐条运行固定数据集评测。"""
    payload = payload or {}
    try:
        if online_evaluation_is_running():
            raise HTTPException(status_code=409, detail="在线意图评测正在运行，请等待完成后再启动")
        params = _online_eval_params(payload)
        status = start_online_evaluation(**params)
        background_tasks.add_task(_run_online_evaluation_background, {
            **params,
            "evaluation_id": status.get("evaluation_id"),
            "started_at": status.get("started_at"),
        })
        return status
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _run_online_evaluation_background(params: dict[str, Any]) -> None:
    try:
        await run_online_evaluation(**params)
    except Exception as exc:  # noqa: BLE001 - surface background failure to UI.
        fail_online_evaluation(params.get("evaluation_id"), str(exc))


@router.post("/intent-parser/evaluations/llm-online/run-sync")
async def run_intent_eval_llm_online_sync(
    payload: dict[str, Any] | None = None,
    _admin: User = Depends(require_admin),
):
    """同步运行在线评测，主要用于脚本和排障。"""
    payload = payload or {}
    try:
        return await run_online_evaluation(**_online_eval_params(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/intent-parser/evaluations/llm-online/status")
async def get_intent_eval_llm_online_status(
    _admin: User = Depends(require_admin),
):
    """返回在线逐条评测的最近进度。"""
    return read_online_status() or {"status": "idle"}


@router.post("/intent-parser/evaluations/llm-batch/submit")
async def submit_intent_eval_llm_batch(
    payload: dict[str, Any] | None = None,
    _admin: User = Depends(require_admin),
):
    """提交固定数据集到阿里云百炼 DashScope Batch API。"""
    try:
        return await submit_llm_batch_evaluation((payload or {}).get("model"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/intent-parser/evaluations/llm-batch/refresh")
async def refresh_intent_eval_llm_batch(
    _admin: User = Depends(require_admin),
):
    """刷新最近一次 LLM Batch 任务；完成后下载输出并生成评分报告。"""
    try:
        return await refresh_latest_llm_batch()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/intent-parser/evaluations/llm-batch/cancel")
async def cancel_intent_eval_llm_batch(
    _admin: User = Depends(require_admin),
):
    """取消最近一次仍在运行中的 LLM Batch 评测任务。"""
    try:
        return await cancel_latest_llm_batch()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

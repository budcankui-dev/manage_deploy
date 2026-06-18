"""业务目标评估器 — 支持 >= 和 <= 操作符，以及基于 baseline 的评估。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schemas import BusinessObjective, BusinessObjectiveEvaluationResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SUPPORTED_OPERATORS = ("<=", ">=")

# 吞吐类业务保持节点历史基线的 80%；视频时延按单独验收裕量判定。
# higher-is-better: actual >= baseline * 0.8
# video latency: actual <= baseline * 1.5
# other lower-is-better: actual <= baseline / 0.8
BASELINE_CAPABILITY_RETENTION = 0.8

# 验收阶段视频推理链路先按显式裕量判定：P90 时延不超过节点基线 1.5 倍。
VIDEO_LATENCY_BASELINE_MULTIPLIER = 1.5


def evaluate_business_objective(
    objective: BusinessObjective,
    actual_metric_key: str,
    actual_value: float,
    object_uris: list[str],
    task_type: str | None = None,
    estimated_value: float | None = None,
    baseline_value: float | None = None,
) -> BusinessObjectiveEvaluationResult:
    """评估业务目标是否达成。

    如果提供了 baseline_value，则按业务类型计算 target_value：
      - >= 操作符: target = baseline * 0.8
      - 视频 P90 时延: target = baseline * 1.5
      - 其他 <= 操作符: target = baseline / 0.8
    否则使用 objective.target_value。
    """
    if actual_metric_key != objective.metric_key:
        return BusinessObjectiveEvaluationResult(
            task_type=task_type,
            metric_key=actual_metric_key,
            actual_value=actual_value,
            target_value=objective.target_value,
            operator=objective.operator,
            unit=objective.unit,
            business_success=False,
            failure_reason=f"Metric key mismatch: expected {objective.metric_key}, got {actual_metric_key}",
            estimated_value=estimated_value,
            estimation_error_ratio=_error_ratio(estimated_value, actual_value),
            object_uris=object_uris,
        )

    if objective.operator not in SUPPORTED_OPERATORS:
        return BusinessObjectiveEvaluationResult(
            task_type=task_type,
            metric_key=actual_metric_key,
            actual_value=actual_value,
            target_value=objective.target_value,
            operator=objective.operator,
            unit=objective.unit,
            business_success=False,
            failure_reason=f"Unsupported operator: {objective.operator}",
            estimated_value=estimated_value,
            estimation_error_ratio=_error_ratio(estimated_value, actual_value),
            object_uris=object_uris,
        )

    # Determine effective target: use baseline with tolerance if provided
    if baseline_value is not None and baseline_value > 0:
        if objective.operator == ">=":
            target = baseline_value * BASELINE_CAPABILITY_RETENTION
        elif _uses_video_latency_multiplier(task_type, actual_metric_key):
            target = baseline_value * VIDEO_LATENCY_BASELINE_MULTIPLIER
        else:
            target = baseline_value / BASELINE_CAPABILITY_RETENTION
    elif objective.target_value is not None and objective.target_value > 0:
        target = objective.target_value
    else:
        return BusinessObjectiveEvaluationResult(
            task_type=task_type,
            metric_key=actual_metric_key,
            actual_value=actual_value,
            target_value=None,
            operator=objective.operator,
            unit=objective.unit,
            business_success=None,
            failure_reason="无基线数据，无法评估",
            estimated_value=estimated_value,
            estimation_error_ratio=_error_ratio(estimated_value, actual_value),
            object_uris=object_uris,
        )

    # Evaluate
    if objective.operator == ">=":
        success = actual_value >= target
        failure_reason = f"{actual_value:.4f} < {target:.4f} (baseline={baseline_value})" if not success else None
    else:
        success = actual_value <= target
        failure_reason = f"{actual_value:.4f} > {target:.4f} (baseline={baseline_value})" if not success else None

    return BusinessObjectiveEvaluationResult(
        task_type=task_type,
        metric_key=actual_metric_key,
        actual_value=actual_value,
        target_value=target,
        operator=objective.operator,
        unit=objective.unit,
        business_success=success,
        failure_reason=failure_reason,
        estimated_value=estimated_value,
        estimation_error_ratio=_error_ratio(estimated_value, actual_value),
        object_uris=object_uris,
    )


def _error_ratio(estimated_value: float | None, actual_value: float) -> float | None:
    if estimated_value in (None, 0):
        return None
    return abs(actual_value - estimated_value) / abs(estimated_value)


def _uses_video_latency_multiplier(task_type: str | None, metric_key: str) -> bool:
    return task_type == "low_latency_video_pipeline" and metric_key == "frame_latency_p90_ms"

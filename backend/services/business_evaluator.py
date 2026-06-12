"""业务目标评估器 — 支持 >= 和 <= 操作符，以及基于 baseline 的评估。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schemas import BusinessObjective, BusinessObjectiveEvaluationResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SUPPORTED_OPERATORS = ("<=", ">=")

# 统一业务能力保持率：端到端运行后的业务能力至少保持节点历史基线的 80%。
# higher-is-better: actual >= baseline * 0.8
# lower-is-better: baseline / actual >= 0.8 => actual <= baseline / 0.8
BASELINE_CAPABILITY_RETENTION = 0.8


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

    如果提供了 baseline_value，则按统一“业务能力保持率 >= 80%”计算 target_value：
      - >= 操作符: target = baseline * 0.8
      - <= 操作符: target = baseline / 0.8
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

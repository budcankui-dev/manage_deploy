"""业务目标评估器 — 支持 >= 和 <= 操作符，以及基于 baseline 的评估。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from schemas import BusinessObjective, BusinessObjectiveEvaluationResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SUPPORTED_OPERATORS = ("<=", ">=")

# baseline 容忍系数：actual >= baseline * HIGHER_FACTOR 或 actual <= baseline * LOWER_FACTOR
BASELINE_TOLERANCE_HIGHER = 0.8  # higher-is-better: actual >= baseline * 0.8
BASELINE_TOLERANCE_LOWER = 1.2   # lower-is-better: actual <= baseline * 1.2


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

    如果提供了 baseline_value，则使用 baseline 容忍系数计算 target_value：
      - >= 操作符: target = baseline * BASELINE_TOLERANCE_HIGHER (0.8)
      - <= 操作符: target = baseline * BASELINE_TOLERANCE_LOWER (1.2)
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
            target = baseline_value * BASELINE_TOLERANCE_HIGHER
        else:
            target = baseline_value * BASELINE_TOLERANCE_LOWER
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

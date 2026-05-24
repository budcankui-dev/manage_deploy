from schemas import BusinessObjective, BusinessObjectiveEvaluationResult


def evaluate_business_objective(
    objective: BusinessObjective,
    actual_metric_key: str,
    actual_value: float,
    object_uris: list[str],
    task_type: str | None = None,
    estimated_value: float | None = None,
) -> BusinessObjectiveEvaluationResult:
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

    if objective.operator != "<=":
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

    success = actual_value <= objective.target_value
    return BusinessObjectiveEvaluationResult(
        task_type=task_type,
        metric_key=actual_metric_key,
        actual_value=actual_value,
        target_value=objective.target_value,
        operator=objective.operator,
        unit=objective.unit,
        business_success=success,
        failure_reason=None if success else f"{actual_value} > {objective.target_value}",
        estimated_value=estimated_value,
        estimation_error_ratio=_error_ratio(estimated_value, actual_value),
        object_uris=object_uris,
    )


def _error_ratio(estimated_value: float | None, actual_value: float) -> float | None:
    if estimated_value in (None, 0):
        return None
    return abs(actual_value - estimated_value) / abs(estimated_value)

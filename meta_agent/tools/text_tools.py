from __future__ import annotations

from typing import Any, Mapping


def normalize_requirement_analysis_result(
	requirement_analysis_result: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
	if not isinstance(requirement_analysis_result, Mapping):
		return None

	is_cron_task = bool(requirement_analysis_result.get("is_cron_task"))
	task_type = str(requirement_analysis_result.get("task_type", "")).strip()
	crontab_expression = requirement_analysis_result.get("crontab_expression")
	if isinstance(crontab_expression, str):
		crontab_expression = crontab_expression.strip() or None
	else:
		crontab_expression = None

	return {
		"is_cron_task": is_cron_task,
		"task_type": task_type,
		"crontab_expression": crontab_expression,
	}

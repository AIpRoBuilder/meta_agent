from __future__ import annotations

from pathlib import Path
from typing import List

from meta_agent.auditor.base_auditor import BaseAuditor
from meta_agent.auditor.data import RuleViolation


class FrontendAuditor(BaseAuditor):
	"""Audit generated frontend HTML files for required AG-UI lifecycle contracts."""

	def __post_init__(self) -> None:  # pragma: no cover - deterministic setup
		return

	def _audit_frontend_file(self, frontend_path: str) -> tuple[bool, List[RuleViolation]]:
		path = Path(frontend_path)
		if not path.is_file():
			return False, [
				RuleViolation(
					class_name="(frontend)",
					rule="frontend_file_missing",
					detail=f"frontend file not found: {frontend_path}",
					lineno=1,
				)
			]

		text = path.read_text(encoding="utf-8")
		checks = {
			"run_step_endpoint_missing": "/api/run-step",
			"reset_session_endpoint_missing": "/api/reset-session",
			"step_card_handler_missing": "step_card",
			"session_id_usage_missing": "sessionId",
		}

		violations: List[RuleViolation] = []
		for rule, token in checks.items():
			if token in text:
				continue
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule=rule,
					detail=f"Missing required token in frontend.html: {token}",
					lineno=1,
				)
			)

		return len(violations) == 0, violations

	def audit_frontend_file(self, frontend_path: str) -> tuple[bool, List[RuleViolation]]:
		return self._audit_frontend_file(frontend_path)


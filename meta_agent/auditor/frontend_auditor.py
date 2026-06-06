from __future__ import annotations

import json
from pathlib import Path
from typing import List

from meta_agent.auditor.base_auditor import BaseAuditor
from meta_agent.auditor.data import RuleViolation
from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema


class FrontendAuditor(BaseAuditor):
	"""Audit generated frontend HTML files for required AG-UI lifecycle contracts."""

	SCHEMA_RENDER_HELPER_NAME = "renderCardSchemaSections"

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
		violations: List[RuleViolation] = []
		if "/api/run-step" not in text and "/cron/start" not in text:
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="execution_endpoint_missing",
					detail="Missing required execution endpoint token in frontend.html: expected /api/run-step or /cron/start",
					lineno=1,
				)
			)

		for rule, token in {
			"reset_session_endpoint_missing": "/api/reset-session",
			"step_card_handler_missing": "step_card",
			"session_id_usage_missing": "sessionId",
		}.items():
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

		if self._has_step_output_card_schemas(path) and self.SCHEMA_RENDER_HELPER_NAME not in text:
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="step_output_schema_renderer_missing",
					detail=(
						"Frontend is missing required schema-aware response card renderer "
						f"helper: {self.SCHEMA_RENDER_HELPER_NAME}"
					),
					lineno=1,
				)
			)

		return len(violations) == 0, violations

	def _has_step_output_card_schemas(self, frontend_path: Path) -> bool:
		workflow_path = frontend_path.parent / "workflow.json"
		if not workflow_path.is_file():
			return False

		try:
			workflow_data = json.loads(workflow_path.read_text(encoding="utf-8"))
		except Exception:
			return False

		nodes = workflow_data.get("nodes")
		if not isinstance(nodes, list):
			return False

		for node in nodes:
			if not isinstance(node, dict):
				continue
			node_name = str(node.get("name", "")).strip()
			if not node_name:
				continue
			node_file = frontend_path.parent / f"{node_name}.py"
			if not node_file.is_file():
				continue
			if compile_node_file_and_get_step_output_card_schema(str(node_file)):
				return True

		return False

	def audit_frontend_file(self, frontend_path: str) -> tuple[bool, List[RuleViolation]]:
		return self._audit_frontend_file(frontend_path)


from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping
import shutil

from meta_agent.auditor.base_auditor import BaseAuditor
from meta_agent.auditor.data import RuleViolation
from meta_agent.tools import _load_graph_json
from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema


class FrontendAuditor(BaseAuditor):
	"""Audit generated frontend src files for required AG-UI lifecycle contracts."""

	SCHEMA_RENDER_HELPER_NAME = "renderCardSchemaSections"
	VUE_REQUIRED_FILES = {
		"api": Path("api/workflow.js"),
		"store": Path("store/workflow.js"),
		"app_shell": Path("components/AppShell.vue"),
		"app": Path("App.vue"),
	}
	FORBIDDEN_VUE_SET_PATTERN = r"\bthis\.\$set\s*\("

	def __init__(self, base_dir: str | Path | None = None) -> None:
		super().__init__()
		self.base_dir = Path(base_dir).expanduser().resolve() if base_dir is not None else None

	def __post_init__(self) -> None:  # pragma: no cover - deterministic setup
		return

	def _resolve_context_base_dir(self, output_path: Path) -> Path:
		if self.base_dir is not None:
			return self.base_dir
		if output_path.is_dir():
			return output_path.resolve()
		return output_path.parent.resolve()

	@staticmethod
	def _find_frontend_project_dir(frontend_path: Path) -> Path | None:
		current = frontend_path.resolve()
		if current.is_file():
			current = current.parent

		for candidate in [current, *current.parents]:
			if (candidate / "package.json").is_file():
				return candidate

		return None

	@staticmethod
	def _parse_eslint_json_output(log_text: str) -> Dict[str, str]:
		if not log_text.strip():
			return {}

		json_payload = log_text.strip()
		if not json_payload.startswith(("[", "{")):
			array_start = json_payload.find("[")
			object_start = json_payload.find("{")
			candidate_starts = [index for index in [array_start, object_start] if index >= 0]
			if not candidate_starts:
				return {}
			json_payload = json_payload[min(candidate_starts):]

		try:
			entries = json.loads(json_payload)
		except json.JSONDecodeError:
			return {}

		if not isinstance(entries, list):
			return {}

		errors_by_file: Dict[str, str] = {}
		for entry in entries:
			if not isinstance(entry, Mapping):
				continue
			file_path = str(entry.get("filePath", "")).strip()
			messages = entry.get("messages")
			if not file_path or not isinstance(messages, list):
				continue

			error_lines: List[str] = []
			for message in messages:
				if not isinstance(message, Mapping):
					continue
				severity = int(message.get("severity", 0) or 0)
				fatal = bool(message.get("fatal", False))
				if severity < 2 and not fatal:
					continue
				line = int(message.get("line", 0) or 0)
				column = int(message.get("column", 0) or 0)
				text = str(message.get("message", "")).strip()
				rule_id = str(message.get("ruleId", "")).strip()
				if not text:
					continue
				location = f"line {line}, col {column}: " if line > 0 and column > 0 else ""
				rule_suffix = f" ({rule_id})" if rule_id and rule_id != "None" else ""
				error_lines.append(f"{location}{text}{rule_suffix}")

			if error_lines:
				errors_by_file[file_path] = "\n".join(error_lines)

		return errors_by_file

	@staticmethod
	def _parse_eslint_stylish_output(log_text: str) -> Dict[str, str]:
		errors_by_file: Dict[str, str] = {}
		current_file: str | None = None
		current_messages: List[str] = []

		for raw_line in log_text.splitlines():
			line = raw_line.rstrip()
			if not line.strip():
				continue

			if line.startswith("/"):
				if current_file and current_messages:
					errors_by_file[current_file] = "\n".join(current_messages)
				current_file = line.strip()
				current_messages = []
				continue

			if current_file and re.match(r"^\s*\d+:\d+\s+", line):
				current_messages.append(re.sub(r"^\s*", "", line))

		if current_file and current_messages:
			errors_by_file[current_file] = "\n".join(current_messages)

		return errors_by_file

	def audit_frontend_lint_errors(self, frontend_path: str) -> Dict[str, str]:
		path = Path(frontend_path)
		project_dir = self._find_frontend_project_dir(path)
		if project_dir is None:
			return {}
		npm_executable = shutil.which("npm")
		if npm_executable is None:
			return {}

		try:
			completed = subprocess.run(
				[npm_executable, "run", "lint", "--", "--format", "json"],
				cwd=str(project_dir),
				capture_output=True,
				text=True,
				check=False,
			)
		except FileNotFoundError:
			return {}

		combined_output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
		lint_errors = self._parse_eslint_json_output(combined_output)
		if lint_errors:
			return lint_errors

		lint_errors = self._parse_eslint_stylish_output(combined_output)
		if lint_errors:
			return lint_errors

		if completed.returncode != 0:
			failure_message = combined_output or f"npm run lint failed with exit code {completed.returncode}"
			return {str(path): f"npm run lint failed: {failure_message}"}

		return {}

	@staticmethod
	def _lint_error_lineno(message: str) -> int:
		line_match = re.match(r"line\s+(\d+),\s*col\s+\d+:", message)
		if line_match:
			return int(line_match.group(1))

		stylish_match = re.match(r"(\d+):(\d+)\s+", message)
		if stylish_match:
			return int(stylish_match.group(1))

		return 1

	def _collect_lint_violations(self, frontend_path: Path) -> List[RuleViolation]:
		violations: List[RuleViolation] = []
		for file_path, message in self.audit_frontend_lint_errors(str(frontend_path)).items():
			violations.append(
				RuleViolation(
					class_name=file_path,
					rule="frontend_lint_error",
					detail=f"{file_path}: {message}",
					lineno=self._lint_error_lineno(message),
				)
			)
		return violations

	def _collect_forbidden_vue2_syntax_violations(
		self,
		resolved_files: Mapping[str, Path],
	) -> List[RuleViolation]:
		violations: List[RuleViolation] = []
		for path in resolved_files.values():
			file_text = path.read_text(encoding="utf-8")
			if not re.search(self.FORBIDDEN_VUE_SET_PATTERN, file_text):
				continue

			violations.append(
				RuleViolation(
					class_name=str(path),
					rule="vue_set_syntax_forbidden",
					detail=(
						f"{path}: Detected forbidden Vue 2 syntax 'this.$set(...)'. "
						"Use direct assignment, object spread, or Object.assign for reactive updates."
					),
					lineno=self._line_number_for_pattern(file_text, self.FORBIDDEN_VUE_SET_PATTERN),
				)
			)

		return violations

	def _audit_frontend_file(self, frontend_path: str) -> tuple[bool, List[RuleViolation]]:
		path = Path(frontend_path)
		return self._audit_frontend_src_dir(path)

	def _audit_frontend_src_dir(self, frontend_dir: Path) -> tuple[bool, List[RuleViolation]]:
		violations: List[RuleViolation] = []
		resolved_base_dir = self._resolve_context_base_dir(frontend_dir)
		resolved_files = {
			name: frontend_dir / relative_path
			for name, relative_path in self.VUE_REQUIRED_FILES.items()
		}

		for name, path in resolved_files.items():
			if path.is_file():
				continue
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="frontend_src_file_missing",
					detail=f"Missing required frontend src file: {name} -> {path}",
					lineno=1,
				)
			)

		if violations:
			return False, violations

		api_text = resolved_files["api"].read_text(encoding="utf-8")
		store_text = resolved_files["store"].read_text(encoding="utf-8")
		app_shell_text = resolved_files["app_shell"].read_text(encoding="utf-8")
		app_text = resolved_files["app"].read_text(encoding="utf-8")
		combined_text = "\n".join([api_text, store_text, app_shell_text, app_text])
		workflow_data = None
		try:
			workflow_data = _load_graph_json(resolved_base_dir / "workflow.json")
		except Exception:
			workflow_data = None

		if "/api/run-step" not in combined_text and "/cron/start" not in combined_text:
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="execution_endpoint_missing",
					detail="Missing required execution endpoint token in frontend src files: expected /api/run-step or /cron/start",
					lineno=1,
				)
			)

		for rule, token in {
			"reset_session_endpoint_missing": "/api/reset-session",
			"step_card_handler_missing": "step_card",
			"session_id_usage_missing": "sessionId",
		}.items():
			if token in combined_text:
				continue
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule=rule,
					detail=f"Missing required token in frontend src files: {token}",
					lineno=1,
				)
			)

		if self._has_step_output_card_schemas(frontend_dir) and self.SCHEMA_RENDER_HELPER_NAME not in combined_text:
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="step_output_schema_renderer_missing",
					detail=(
						"Frontend src files are missing required schema-aware response card renderer "
						f"helper: {self.SCHEMA_RENDER_HELPER_NAME}"
					),
					lineno=1,
				)
			)

		violations.extend(self._audit_app_vue_imports(app_text, workflow_data))
		violations.extend(self._audit_view_store_imports(frontend_dir))
		violations.extend(self._collect_forbidden_vue2_syntax_violations(resolved_files))
		violations.extend(self._collect_lint_violations(frontend_dir))

		return len(violations) == 0, violations

	@staticmethod
	def _line_number_for_pattern(text: str, pattern: str) -> int:
		match = re.search(pattern, text, flags=re.MULTILINE)
		if not match:
			return 1
		return text.count("\n", 0, match.start()) + 1

	@classmethod
	def _audit_view_store_imports(cls, frontend_dir: Path) -> List[RuleViolation]:
		violations: List[RuleViolation] = []
		views_dir = frontend_dir / "views"
		if not views_dir.is_dir():
			return violations

		for view_file in sorted(views_dir.glob("*.vue")):
			view_text = view_file.read_text(encoding="utf-8")
			invalid_import_pattern = r'import\s+[^\n]*from\s+["\']\.\./stores/workflowStore(?:\.js)?["\']'
			if not re.search(invalid_import_pattern, view_text):
				continue

			violations.append(
				RuleViolation(
					class_name=str(view_file),
					rule="view_store_import_invalid",
					detail=(
						f"{view_file}: Node view files must not import workflow store modules via ../stores/workflowStore; "
						"use injected workflowStore instead."
					),
					lineno=cls._line_number_for_pattern(view_text, r"\.\./stores/workflowStore"),
				)
			)

		return violations

	@classmethod
	def _audit_app_vue_imports(
		cls,
		app_text: str,
		workflow_data: Mapping[str, Any] | None,
	) -> List[RuleViolation]:
		violations: List[RuleViolation] = []
		app_shell_pattern = r'import\s+AppShell\s+from\s+["\']\./components/AppShell\.vue["\']'
		if not re.search(app_shell_pattern, app_text):
			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="app_shell_import_missing",
					detail="App.vue must import AppShell from ./components/AppShell.vue",
					lineno=1,
				)
			)

		if not isinstance(workflow_data, Mapping):
			return violations

		nodes = workflow_data.get("nodes", [])
		if not isinstance(nodes, list):
			return violations

		for node in nodes:
			if not isinstance(node, Mapping):
				continue
			if node.get("enable", True) is False:
				continue
			node_name = str(node.get("name", "")).strip()
			if not node_name:
				continue

			import_pattern = rf'import\s+{re.escape(node_name)}\s+from\s+["\']\./views/{re.escape(node_name)}\.vue["\']'
			if re.search(import_pattern, app_text):
				continue

			violations.append(
				RuleViolation(
					class_name="(frontend)",
					rule="app_view_import_missing",
					detail=f"App.vue must import {node_name} from ./views/{node_name}.vue",
					lineno=cls._line_number_for_pattern(app_text, r"<script|import\s"),
				)
			)

		return violations

	def _has_step_output_card_schemas(self, frontend_path: Path) -> bool:
		context_root = self._resolve_context_base_dir(frontend_path)
		workflow_data = None
		try:
			workflow_data = _load_graph_json(context_root / "workflow.json")
		except Exception:
			workflow_data = None
		if not isinstance(workflow_data, dict):
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
			node_file = context_root / f"{node_name}.py"
			if not node_file.is_file():
				continue
			if compile_node_file_and_get_step_output_card_schema(str(node_file)):
				return True

		return False

	def audit_frontend_file(self, frontend_path: str) -> tuple[bool, List[RuleViolation]]:
		return self._audit_frontend_file(frontend_path)


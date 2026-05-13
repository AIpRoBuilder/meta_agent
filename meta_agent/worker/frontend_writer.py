"""Generate AG-UI HTML frontend files via an LLM."""

from __future__ import annotations

import sys
import json
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

# Resolve package root consistently for both source checkout and pip-installed layouts.
_DEFAULT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_META_AGENT_SPEC = importlib.util.find_spec("meta_agent")
if _META_AGENT_SPEC and _META_AGENT_SPEC.origin:
	ROOT_DIR = Path(_META_AGENT_SPEC.origin).resolve().parent
else:
	ROOT_DIR = _DEFAULT_PACKAGE_ROOT

if str(ROOT_DIR.parent) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR.parent))

from meta_agent.llm_client.coder import Coder


@dataclass
class PromptFrontendCoder(Coder):
	"""Coder that emits AG-UI lifecycle frontend HTML from step metadata."""

	prompt_path: str = "worker/prompts/pydaograph_frontend_prompt.md"

	def __post_init__(self) -> None:
		prompt_file = ROOT_DIR / self.prompt_path
		if not prompt_file.exists():
			raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

		self.system_prompt = prompt_file.read_text(encoding="utf-8")
		super().__post_init__()

	def _normalize_steps(self, steps_meta: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
		normalized: list[dict[str, Any]] = []
		for item in steps_meta:
			step_id = str(item.get("id", "")).strip()
			title = str(item.get("title", "")).strip()
			if not step_id or not title:
				raise ValueError("Each step must contain non-empty 'id' and 'title'.")

			dependencies = item.get("dependencies") or []
			if not isinstance(dependencies, Sequence) or isinstance(dependencies, (str, bytes)):
				raise ValueError(f"dependencies must be a list for step: {step_id}")

			services_raw = item.get("services") or []
			services: list[dict[str, str]] = []
			if isinstance(services_raw, Sequence) and not isinstance(services_raw, (str, bytes)):
				for service_item in services_raw:
					if not isinstance(service_item, Mapping):
						continue
					service_name = str(service_item.get("service_name", "")).strip()
					use_desc = str(service_item.get("use_desc", "")).strip()
					if not service_name:
						continue
					services.append(
						{
							"service_name": service_name,
							"use_desc": use_desc,
						}
					)

			ext_data_raw = item.get("extData") or item.get("ext_data") or {}
			if isinstance(ext_data_raw, Mapping):
				ext_type = str(ext_data_raw.get("type", "none")).strip().lower()
				ext_desc = str(ext_data_raw.get("desc", "")).strip()
				raw_inputs_format = ext_data_raw.get("inputs_format", {})
			else:
				ext_type = str(ext_data_raw).strip().lower() or "none"
				ext_desc = ""
				raw_inputs_format = {}

			inputs_format: dict[str, str] = {}
			if isinstance(raw_inputs_format, Mapping):
				for key, value in raw_inputs_format.items():
					field_name = str(key).strip()
					field_type = str(value).strip().lower()
					if field_name and field_type:
						inputs_format[field_name] = field_type

			input_required = bool(item.get("inputRequired", True))
			node_kind = str(item.get("nodeKind", "input")).strip() or "input"
			if ext_type == "chat_input":
				node_kind = "chat"
			if ext_type == "user_file_input":
				node_kind = "file"
			if ext_type == "image":
				node_kind = "image"
				input_required = False
			if ext_type == "service":
				node_kind = "service"
			if ext_type == "skill" or str(ext_data_raw.get("skill_name", "") if isinstance(ext_data_raw, Mapping) else "").strip():
				node_kind = "skill"
			if ext_type == "none" and node_kind in {"operation", "service"}:
				input_required = False
			if node_kind in {"service", "skill"}:
				input_required = False
			if ext_type in {"user_input", "user_file_input", "chat_input"}:
				input_required = True

			normalized.append(
				{
					"id": step_id,
					"title": title,
					"prompt": str(item.get("prompt", "")).strip(),
					"dependencies": [str(dep).strip() for dep in dependencies if str(dep).strip()],
					"services": services,
					"inputRequired": input_required,
					"nodeKind": node_kind,
					"extData": {
						"type": ext_type,
						"desc": ext_desc,
						"inputs_format": inputs_format if ext_type == "user_input" else {},
					},
				}
			)

		if not normalized:
			raise ValueError("steps_meta cannot be empty.")

		return normalized

	def _build_user_prompt(
		self,
		*,
		steps_meta: list[dict[str, Any]],
		run_step_endpoint: str,
		run_all_cron_endpoint: str | None,
		reset_session_endpoint: str,
		reference_frontend: str,
		node_ui_context: str,
		graph_plan_context: str,
		frontend_style_prompt: str | None = None,
	) -> str:
		steps_json = json.dumps(steps_meta, ensure_ascii=False, indent=2)
		style_block = ""
		if frontend_style_prompt and frontend_style_prompt.strip():
			style_block = (
				"User-defined frontend style guidance (must follow while preserving required behavior and event semantics):\n"
				f"{frontend_style_prompt.strip()}\n\n"
			)

		return (
			"Generate one runnable frontend.html for an AG-UI lifecycle step workflow.\n"
			"Use plain HTML + CSS + browser JavaScript (no frameworks).\n"
			"Use the provided reference HTML style and behavior as the baseline.\n\n"
			f"{style_block}"
			f"run-step endpoint: {run_step_endpoint}\n"
			f"run-all-cron endpoint: {run_all_cron_endpoint or '(disabled)'}\n"
			f"reset-session endpoint: {reset_session_endpoint}\n\n"
			"Graph plan JSON context:\n"
			f"{graph_plan_context}\n\n"
			"Node UI HTML context loaded from default node_ui folder:\n"
			f"{node_ui_context}\n\n"
			"The backend emits SSE AG-UI events, including CUSTOM event name='step_card'.\n"
			"Each step returns StepRunOutput (input nodes via process_input, file nodes via build_step_output after persistence, chat nodes via build_step_output, image nodes via build_step_output, operation nodes via process_operation) with fields:\n"
			"- summary: string\n"
			"- card: object (render rows from card.rows where each row has name/value; also render card.actions when present)\n"
			"- derived: object (for backend chaining and possible final display)\n\n"
			"step_card event payload shape:\n"
			"- stepId, title, prompt, state, summary, card, derived, unlocked, isFinal\n\n"
			"Required UI behavior:\n"
			"1) Build one step card per step from this metadata.\n"
			"2) Enforce dependency-gated input enabling (only unlocked step can submit).\n"
			"2.1) For the card of the currently running step, show a visible running-circle loading indicator while waiting for backend result events, then hide it when the step finishes or errors.\n"
			"3) Stream SSE from run-step endpoint and react to STEP_STARTED, STEP_FINISHED, TEXT_MESSAGE_CONTENT, CUSTOM(step_card), RUN_ERROR, RUN_FINISHED. TEXT_MESSAGE_CONTENT is streamed in multiple chunks for chat nodes; append chunks in order and render live.\n"
			"4) Render step_card.state, step_card.summary, step_card.card.rows, and step_card.card.actions into the matching step card.\n"
			"5) Maintain sessionId in localStorage and show it in a badge.\n"
			"6) Include New Session + Reset Session actions that call reset-session endpoint.\n"
			"6.1) If run-all-cron endpoint is provided (not '(disabled)'), include Start Cron and Stop Cron controls.\n"
			"6.2) Start Cron should POST to run-all-cron with payload at least {sessionId, resetBeforeEachRun}; consume SSE continuously using the same event handler as run-step events.\n"
			"6.3) Stop Cron should cancel the active cron stream (for example via AbortController) and update UI state to idle.\n"
			"6.4) Ensure only one cron stream is active at a time and disable Start Cron while running.\n"
			"7) If step metadata includes inputRequired=false or nodeKind in ('operation','service','skill'), do not require text input for submission.\n"
			"7.1) For any step that does not require direct user input (for example operation/service/skill/image/dependency-driven steps), auto-submit it immediately when it becomes unlocked and visible; do not require a click on a Run button.\n"
			"8) If step extData.type == 'user_file_input' (or nodeKind='file'), treat it as WorkflowFileNode input: render a multi-file upload control (allow selecting multiple files).\n"
			"9) For file upload nodes, read selected files as encoded byte strings and submit input as {'files':[{'fileName','fileBytes'}, ...]} where fileBytes is a data-url/byte-string derived from each uploaded file.\n"
			"10) If step extData.type == 'image' (or nodeKind='image'), treat it as dependency-driven WorkflowImageNode step: do not require or render direct user image/file inputs for this step.\n"
			"11) For image nodes, submit without manual input payload and rely on image file locations from dependency_results upstream.\n"
			"12) If only one file is selected in file-upload nodes, still use the same files array shape with one item for consistency.\n"
			"13) For extData.type == 'user_input', 'chat_input', or 'skill': if extData.inputs_format is non-empty, render structured form controls by field type (string/number/boolean), then stringify the collected object (e.g., JSON.stringify) and submit that serialized value as input string; if inputs_format is empty, keep plain text input behavior.\n"
			"13.0) Concrete example: extData.inputs_format={'email_address':'string','password':'number','remember_me':'boolean'} => render text/number/checkbox controls, build {'email_address':'user@example.com','password':123456,'remember_me':true}, then submit input='{\"email_address\":\"user@example.com\",\"password\":123456,\"remember_me\":true}'.\n"
			"13.1) For extData.type == 'chat_input' (or nodeKind='chat') with no inputs_format, keep plain text input submission behavior.\n"
			"14) For nodeKind='chat', render labels/status as chat-oriented, keep the same step-card event flow and payload handling, and surface progressive LLM text as chunks arrive over SSE.\n"
			"15) For nodeKind='file', render labels/status as file-upload/storage oriented; for nodeKind='image', render labels/status as image-analysis oriented; for nodeKind='service', render labels/status as service startup/orchestration oriented; for nodeKind='skill', render labels/status as skill-execution oriented; keep the same step-card event flow and payload handling.\n"
			"15.1) For auto-run steps, show non-interactive UI (informational text only) and rely on card running indicator/state rather than clickable run controls.\n"
			"16) Render step cards progressively in metadata order: show only the first card initially, and reveal each next card only after the previous card has finished.\n"
			"17) Make step cards visually polished and modern: clear hierarchy, elegant spacing, subtle gradients/shadows, rounded card shells, and compact status/meta chips.\n"
			"18) Treat step card sections distinctly (header/body/input/results) and improve readability for summary, rows, and actions without changing backend event semantics.\n"
			"19) For nodeKind='chat', use chat-oriented labels; for nodeKind='file', use upload/storage labels; for nodeKind='image', use dependency-analysis labels.\n"
			"20) Keep implementation minimal and robust; no extra features beyond the polished card styling and required behavior.\n\n"
			"If any behavior in the reference frontend conflicts with these requirements, follow these requirements.\n\n"
			"Step metadata JSON:\n"
			f"{steps_json}\n\n"
			"Reference frontend example (adapt this structure and event handling):\n"
			f"{reference_frontend}\n"
		)

	def _load_default_frontend_context(
		self,
		output_path: Path,
		base_dir: str | Path | None = None,
	) -> tuple[str, str]:
		"""Load workflow.json and node_ui/*.html from a user-provided or default base dir."""

		if base_dir is None:
			resolved_base_dir = output_path.parent.resolve()
		else:
			resolved_base_dir = Path(base_dir).expanduser().resolve()
		graph_plan_path = resolved_base_dir / "workflow.json"
		node_ui_dir = resolved_base_dir / "node_ui"

		if graph_plan_path.exists():
			graph_plan_context = graph_plan_path.read_text(encoding="utf-8")
		else:
			graph_plan_context = f"[missing] workflow.json not found at: {graph_plan_path}"

		node_html_chunks: list[str] = []
		if node_ui_dir.exists() and node_ui_dir.is_dir():
			for html_file in sorted(node_ui_dir.glob("*.html")):
				try:
					html_text = html_file.read_text(encoding="utf-8")
				except UnicodeDecodeError:
					html_text = html_file.read_text(encoding="utf-8", errors="replace")
				node_html_chunks.append(
					f"\n=== {html_file.name} ===\n{html_text}\n"
				)

		if node_html_chunks:
			node_ui_context = "\n".join(node_html_chunks)
		else:
			node_ui_context = f"[missing] no *.html files found under: {node_ui_dir}"

		return node_ui_context, graph_plan_context

	def write_frontend_html(
		self,
		*,
		steps_meta: Sequence[Mapping[str, Any]],
		output_path: str,
		context_base_dir: str | None = None,
		run_step_endpoint: str = "/api/run-step",
		run_all_cron_endpoint: str | None = "/api/run-all-cron",
		reset_session_endpoint: str = "/api/reset-session",
		reference_frontend_path: str | None = None,
		frontend_style_prompt: str | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = 20000,
	) -> Path:
		normalized_steps = self._normalize_steps(steps_meta)

		if reference_frontend_path:
			reference_path = Path(reference_frontend_path).expanduser().resolve()
		else:
			reference_path = ROOT_DIR / "library/frontend_reference.html"

		if not reference_path.exists():
			raise FileNotFoundError(f"reference_frontend_path not found: {reference_path}")

		reference_frontend = reference_path.read_text(encoding="utf-8")

		target_path = Path(output_path).expanduser()
		if target_path.suffix.lower() != ".html":
			target_path = target_path.with_suffix(".html")
		target_path.parent.mkdir(parents=True, exist_ok=True)
		node_ui_context, graph_plan_context = self._load_default_frontend_context(
			target_path,
			base_dir=context_base_dir,
		)

		user_prompt = self._build_user_prompt(
			steps_meta=normalized_steps,
			run_step_endpoint=run_step_endpoint,
			run_all_cron_endpoint=run_all_cron_endpoint,
			reset_session_endpoint=reset_session_endpoint,
			reference_frontend=reference_frontend,
			node_ui_context=node_ui_context,
			graph_plan_context=graph_plan_context,
			frontend_style_prompt=frontend_style_prompt,
		)

		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def amend_code_with_feedback(
		self,
		code_path: str,
		amendment: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = 20000,
	) -> Path:
		"""Amend existing frontend HTML using feedback and write updated file."""

		target_path = Path(code_path).expanduser()
		if target_path.suffix.lower() != ".html":
			target_path = target_path.with_suffix(".html")

		if not target_path.exists():
			raise FileNotFoundError(f"Frontend file not found: {target_path}")

		original_html = target_path.read_text(encoding="utf-8")
		user_prompt = (
			"You are updating an AG-UI lifecycle frontend HTML file.\n"
			"Keep it as a single runnable frontend.html file using plain HTML/CSS/JS.\n"
			"Preserve existing behavior and fix only the issues in the amendment.\n"
			"Return only runnable HTML with no explanation.\n\n"
			"Existing frontend:\n"
			f"{original_html}\n\n"
			"Amendment / feedback to apply:\n"
			f"{amendment}\n"
		)

		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def _amend_frontend_with_feedback(
		self,
		frontend_path: str,
		amendment: str,
		*,
		temperature: float = 0.2,
		max_tokens: int = 20000,
	) -> Path:
		"""Private helper that delegates to amend_code_with_feedback."""

		return self.amend_code_with_feedback(
			frontend_path,
			amendment,
			temperature=temperature,
		)


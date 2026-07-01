"""Generate AG-UI Vue frontend files via an LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from meta_agent._paths import bootstrap_package_root


ROOT_DIR = bootstrap_package_root(__file__)

from meta_agent.llm_client.coder import Coder, MAX_TOKENS
from meta_agent.architect.graph import NodeMeta
from meta_agent.tools import graph_to_nodes
from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema
from meta_agent.tools.function_tools import _run_stage
from meta_agent.tools.text_tools import normalize_requirement_analysis_result, truncate_context


_DEFAULT_VUE_FRONTEND_REFERENCE_DIR = Path("/Users/xiechuxi/Desktop/codes/education_workflow/frontend/src")
_BUNDLED_VUE_FRONTEND_REFERENCE_DIR = ROOT_DIR / "library" / "frontend_reference" / "src"


@dataclass
class PromptFrontendCoder(Coder):
	"""Coder that emits AG-UI lifecycle frontend src files from step metadata."""

	prompt_path: str = "worker/prompts/pydaograph_frontend_prompt.md"
	node_ui_context_max_chars: int = 18000
	graph_plan_context_max_chars: int = 12000
	step_output_card_context_max_chars: int = 12000
	vue_reference_context_max_chars: int = 12000
	generation_request_label: str = "frontend generation request"
	amendment_request_label: str = "frontend amendment request"

	def __post_init__(self) -> None:
		prompt_file = ROOT_DIR / self.prompt_path
		if not prompt_file.exists():
			raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

		self.system_prompt = prompt_file.read_text(encoding="utf-8")
		super().__post_init__()

	def _truncate_prompt_context(
		self,
		text: str,
		*,
		label: str,
		max_chars: int,
		request_label: str,
	) -> str:
		return truncate_context(
			text,
			label=label,
			max_chars=max_chars,
			request_label=request_label,
		)

	def _append_prompt_context_block(
		self,
		prompt: str,
		*,
		heading: str,
		text: str,
		label: str,
		max_chars: int,
		request_label: str,
	) -> str:
		if not text:
			return prompt
		return (
			prompt
			+ f"\n{heading}:\n"
			+ self._truncate_prompt_context(
				text,
				label=label,
				max_chars=max_chars,
				request_label=request_label,
			)
			+ "\n"
		)

	def _truncate_prompt_contexts(
		self,
		*,
		request_label: str,
		contexts: Mapping[str, tuple[str, int]],
	) -> dict[str, str]:
		return {
			label: self._truncate_prompt_context(
				text,
				label=label,
				max_chars=max_chars,
				request_label=request_label,
			)
			for label, (text, max_chars) in contexts.items()
		}

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
			if ext_type == "user_file_input":
				node_kind = "file"
			if ext_type == "service":
				node_kind = "service"
			if ext_type == "skill" or str(ext_data_raw.get("skill_name", "") if isinstance(ext_data_raw, Mapping) else "").strip():
				node_kind = "skill"
			if ext_type == "none" and node_kind in {"operation", "service"}:
				input_required = False
			if node_kind in {"service", "skill"}:
				input_required = False
			if ext_type in {"user_input", "user_file_input"}:
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

	@staticmethod
	def _build_app_shell_steps_meta(steps_meta: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
		return [
			{
				"id": step["id"],
				"title": step["title"],
				"dependencies": step.get("dependencies", []),
				"inputRequired": step.get("inputRequired", True),
				"nodeKind": step.get("nodeKind", "input"),
				"extData": {
					"type": step.get("extData", {}).get("type", "none"),
					"inputs_format": step.get("extData", {}).get("inputs_format", {}),
				},
			}
			for step in steps_meta
		]

	def _resolve_reference_frontend_src_dir(
		self,
		reference_frontend_src_dir: str | Path | None = None,
	) -> Path:
		candidates: list[Path] = []
		if reference_frontend_src_dir is not None:
			candidates.append(Path(reference_frontend_src_dir).expanduser().resolve())
		candidates.extend(
			[
				_BUNDLED_VUE_FRONTEND_REFERENCE_DIR.resolve(),
				_DEFAULT_VUE_FRONTEND_REFERENCE_DIR.resolve(),
			]
		)

		seen: set[Path] = set()
		unique_candidates: list[Path] = []
		for candidate in candidates:
			if candidate in seen:
				continue
			seen.add(candidate)
			unique_candidates.append(candidate)

		for candidate in unique_candidates:
			if candidate.exists() and candidate.is_dir():
				return candidate

		raise FileNotFoundError(
			"reference frontend src directory not found. "
			f"Checked: {', '.join(str(candidate) for candidate in unique_candidates)}"
		)

	def _load_reference_vue_frontend_context(
		self,
		reference_frontend_src_dir: str | Path | None = None,
	) -> dict[str, str]:
		reference_dir = self._resolve_reference_frontend_src_dir(reference_frontend_src_dir)
		files = {
			"api": reference_dir / "api" / "workflow.js",
			"store": reference_dir / "store" / "workflow.js",
			"app_shell": reference_dir / "components" / "AppShell.vue",
			"app_css": reference_dir / "styles" / "app.css",
		}
		missing = [str(path) for path in files.values() if not path.is_file()]
		if missing:
			raise FileNotFoundError(
				"reference frontend files not found: " + ", ".join(missing)
			)

		return {
			key: path.read_text(encoding="utf-8")
			for key, path in files.items()
		}

	def _load_reference_app_source(
		self,
		reference_frontend_src_dir: str | Path | None = None,
	) -> str:
		reference_dir = self._resolve_reference_frontend_src_dir(reference_frontend_src_dir)
		app_path = reference_dir / "App.vue"
		if not app_path.is_file():
			raise FileNotFoundError(f"reference frontend file not found: {app_path}")

		return app_path.read_text(encoding="utf-8")

	@staticmethod
	def _load_frontend_visible_node_names(graph_plan_path: Path) -> list[str]:
		if not graph_plan_path.is_file():
			return []

		try:
			graph_plan_data = json.loads(graph_plan_path.read_text(encoding="utf-8"))
		except json.JSONDecodeError:
			return list(graph_to_nodes(graph_plan_path).keys())

		nodes = graph_plan_data.get("nodes", []) if isinstance(graph_plan_data, Mapping) else []
		if not isinstance(nodes, list):
			return []

		visible_names: list[str] = []
		for node in nodes:
			if not isinstance(node, Mapping):
				continue
			node_meta = NodeMeta.from_dict(node)
			if not node_meta.name or not node_meta.show_frontend:
				continue
			visible_names.append(node_meta.name)

		return visible_names

	@staticmethod
	def _resolve_context_base_dir(
		output_path: Path,
		base_dir: str | Path | None = None,
	) -> Path:
		if base_dir is None:
			return output_path.parent.resolve()
		return Path(base_dir).expanduser().resolve()

	@staticmethod
	def _load_generated_frontend_context(output_path: Path) -> dict[str, str]:
		src_dir = output_path.parent.resolve()
		files = {
			"api": src_dir / "api" / "workflow.js",
			"store": src_dir / "store" / "workflow.js",
			"app_shell": src_dir / "components" / "AppShell.vue",
		}
		missing = [str(path) for path in files.values() if not path.is_file()]
		if missing:
			raise FileNotFoundError(
				"generated frontend files required for App.vue were not found: " + ", ".join(missing)
			)

		return {
			key: path.read_text(encoding="utf-8")
			for key, path in files.items()
		}

	def _build_api_user_prompt(
		self,
		*,
		run_step_endpoint: str,
		reset_session_endpoint: str,
		reference_api_source: str,
		requirement_analysis_result: Mapping[str, Any] | None,
	) -> str:
		cron_meta = normalize_requirement_analysis_result(requirement_analysis_result)
		is_cron_task = bool(cron_meta and cron_meta["is_cron_task"])
		execution_endpoint = "/cron/start" if is_cron_task else run_step_endpoint
		cron_block = ""
		if is_cron_task:
			cron_block = (
				"Cron mode requirements:\n"
				"- Export a startCron(payload, onEvent) helper that POSTs to /cron/start.\n"
				"- Keep resetSession(sessionId) exported and unchanged in spirit.\n"
				"- If the cron endpoint returns SSE, parse it exactly like runStep; if it returns JSON only, pass the parsed object to onEvent once when provided.\n\n"
			)

		truncated_contexts = self._truncate_prompt_contexts(
			request_label=self.generation_request_label,
			contexts={
				"reference_api_source": (reference_api_source, self.vue_reference_context_max_chars),
			},
		)

		return (
			"Generate one JavaScript module file named workflow.js for frontend/src/api/workflow.js.\n"
			"Return only runnable JavaScript with no markdown fences or explanation.\n"
			"Follow the reference module structure closely: fetch-based helpers, incremental SSE parsing, and plain exported functions.\n"
			"Implement a shared internal SSE reader helper if it reduces duplication.\n"
			f"Export runStep(payload, onEvent) targeting {execution_endpoint}.\n"
			f"Export resetSession(sessionId) targeting {reset_session_endpoint}.\n"
			"For SSE parsing, read response.body with getReader(), split on newline, handle lines starting with 'data: ', ignore empty payloads and [DONE], and JSON.parse each event before calling onEvent.\n"
			"Throw on non-ok HTTP responses and include the status code in the error message.\n"
			"Keep the module framework-agnostic.\n\n"
			f"{cron_block}"
			"Reference api/workflow.js example:\n"
			f"{truncated_contexts['reference_api_source']}\n"
		)

	def _build_store_user_prompt(
		self,
		*,
		steps_meta: list[dict[str, Any]],
		run_step_endpoint: str,
		reset_session_endpoint: str,
		requirement_analysis_result: Mapping[str, Any] | None,
		reference_store_source: str,
		graph_plan_context: str,
		step_output_card_context: str,
	) -> str:
		steps_json = json.dumps(steps_meta, ensure_ascii=False, indent=2)
		truncated_contexts = self._truncate_prompt_contexts(
			request_label=self.generation_request_label,
			contexts={
				"reference_store_source": (reference_store_source, self.vue_reference_context_max_chars),
				"graph_plan_context": (graph_plan_context, self.graph_plan_context_max_chars),
				"step_output_card_context": (step_output_card_context, self.step_output_card_context_max_chars),
			},
		)
		cron_meta = normalize_requirement_analysis_result(requirement_analysis_result)
		is_cron_task = bool(cron_meta and cron_meta["is_cron_task"])
		execution_helper = "startCron" if is_cron_task else "runStep"
		execution_endpoint = "/cron/start" if is_cron_task else run_step_endpoint
		cron_block = ""
		if is_cron_task:
			cron_block = (
				"Cron workflow state requirements:\n"
				"- Track cron response metadata and expose a startCronRun() action instead of per-step run buttons.\n"
				"- Keep step cards visible as read-only overview data.\n"
				"- Preserve sessionId handling and reset/new-session actions.\n\n"
			)

		return (
			"Generate one JavaScript module file named workflow.js for frontend/src/store/workflow.js.\n"
			"Return only runnable JavaScript with no markdown fences or explanation.\n"
			"Target modern Vue runtime behavior only: never use this.$set or Vue.set; update reactive state via direct assignment, object spread, or Object.assign instead.\n"
			"Use Vue's reactive() store style and export createWorkflowStore().\n"
			"Also export STEP_METADATA as a constant populated from the step metadata JSON below.\n"
			"Import resetSession and "
			f"{execution_helper} from ../api/workflow.\n"
			f"The store must orchestrate calls to {execution_endpoint}.\n"
			"Required behavior:\n"
			"- persist sessionId in localStorage and expose displaySessionId(), progressText(), and progressPercent().\n"
			"- track stepStatus, stepResults, conversationEntries, completedSteps, runningStep, eventLog, and totalSteps.\n"
			"- unlock steps from dependency completion, and auto-submit steps with inputRequired=false or nodeKind in ('operation','service','skill') once they become unlocked.\n"
			"- handle AG-UI events STEP_STARTED, STEP_FINISHED, TEXT_MESSAGE_CONTENT, CUSTOM with name='step_card', RUN_ERROR, and RUN_FINISHED.\n"
			"- append TEXT_MESSAGE_CONTENT chunks in order for chat steps instead of replacing prior content.\n"
			"- store step_card payloads under stepResults[stepId] and preserve card plus derived output.\n"
			"- provide resetCurrentSession(), createNewSession(), initialize(), submitStep(stepId, inputValue), isUnlocked(stepId), and isCompleted(stepId).\n"
			"- support file-input nodes by accepting already-serialized payload strings from the component layer rather than directly reading files in the store.\n"
			"- support structured user_input forms by sending serialized JSON strings unchanged.\n"
			"- keep code plain and robust, matching the reference module organization.\n\n"
			f"{cron_block}"
			"Graph plan JSON context:\n"
			f"{truncated_contexts['graph_plan_context']}\n\n"
			"Per-step StepRunOutput.card schema context:\n"
			f"{truncated_contexts['step_output_card_context']}\n\n"
			"Step metadata JSON:\n"
			f"{steps_json}\n\n"
			"Reference store/workflow.js example:\n"
			f"{truncated_contexts['reference_store_source']}\n"
		)

	def _build_app_shell_user_prompt(
		self,
		*,
		steps_meta: list[dict[str, Any]],
		store_workflow_source: str,
		reference_app_shell_source: str,
		node_view_template_context: str,
		step_output_card_context: str,
	) -> str:
		app_shell_steps_meta = self._build_app_shell_steps_meta(steps_meta)
		steps_json = json.dumps(app_shell_steps_meta, ensure_ascii=False, indent=2)
		truncated_contexts = self._truncate_prompt_contexts(
			request_label=self.generation_request_label,
			contexts={
				"store_workflow_source": (store_workflow_source, min(self.vue_reference_context_max_chars, 5000)),
				"reference_app_shell_source": (reference_app_shell_source, min(self.vue_reference_context_max_chars, 6000)),
				"node_view_template_context": (node_view_template_context, min(self.node_ui_context_max_chars, 5000)),
				"step_output_card_context": (step_output_card_context, min(self.step_output_card_context_max_chars, 4000)),
			},
		)

		return (
			"Generate one Vue single-file component named AppShell.vue for frontend/src/components/AppShell.vue.\n"
			"Return only runnable Vue SFC code with no markdown fences or explanation.\n"
			"Never use this.$set or Vue.set anywhere in the component; use direct property assignment, object spread, or Object.assign for reactive updates.\n"
			"Use the reference component as the baseline for layout rhythm, store interaction, and composition.\n"
			"This component is the workflow main page, operates on an injected workflowStore, and should stay close to the example's Vue Options API structure.\n"
			"Import ../styles/app.css in the component's style block and keep the main visual system there; only add minimal scoped local styles when necessary.\n"
			"Required UI behavior:\n"
			"- show a top bar with session badge, progress, New Session, and Reset Session actions.\n"
			"- render one workflow card per step from workflowStore.steps and keep cards progressive by unlocked state.\n"
			"- arrange the step cards in a strict vertical column with exactly one card per row (no multi-column card grid).\n"
			"- keep the conversation bar centered along the middle bottom of the page when the workflow uses conversational input.\n"
			"- render status badges for locked/active/running/completed/error.\n"
			"- expose one input area per selected or active step and call workflowStore.submitStep(stepId, payload) so the request flows to /api/run-step.\n"
			"- for nodeKind='file', use a multi-file picker and serialize files into JSON strings shaped like {files:[{fileName,bytes},...]} before submission.\n"
			"- for extData.inputs_format, render structured controls by type and submit JSON.stringify(collectedObject).\n"
			"- render card.rows, card.actions, and schema-aware sections using a helper named renderCardSchemaSections when schema context is available.\n"
			"- include a visible running indicator on the currently running step.\n"
			"- keep the look polished and modern while staying close to the example structure.\n\n"
			"Store workflow.js context:\n"
			f"{truncated_contexts['store_workflow_source']}\n\n"
			"Node view template context from frontend/src/views/{Node}.vue:\n"
			f"{truncated_contexts['node_view_template_context']}\n\n"
			"Per-step StepRunOutput.card schema context:\n"
			f"{truncated_contexts['step_output_card_context']}\n\n"
			"Step metadata JSON:\n"
			f"{steps_json}\n\n"
			"Reference AppShell.vue example:\n"
			f"{truncated_contexts['reference_app_shell_source']}\n"
		)

	def _build_app_css_user_prompt(
		self,
		*,
		reference_app_css_source: str,
		node_style_context: str,
		frontend_style_prompt: str,
	) -> str:
		truncated_contexts = self._truncate_prompt_contexts(
			request_label=self.generation_request_label,
			contexts={
				"reference_app_css_source": (reference_app_css_source, self.vue_reference_context_max_chars),
				"node_style_context": (node_style_context, self.node_ui_context_max_chars),
			},
		)

		return (
			"Generate one CSS file named app.css for frontend/src/styles/app.css.\n"
			"Return only runnable CSS with no markdown fences or explanation.\n"
			"Use the reference stylesheet as the baseline shared design system for the generated workflow frontend.\n"
			"Keep selectors, layout hooks, and utility rules needed by the reference AppShell structure unless the style guidance clearly requires an intentional adjustment.\n"
			"Define the AppShell step-list layout so workflow step cards are displayed vertically in one column with one card per row across the page (do not use multi-column grids for step cards).\n"
			"Use the node stylesheet context to make app.css visually fit and complement the generated frontend/src/styles/{Node}.css files without duplicating their component-scoped rules.\n"
			"Apply the user-defined frontend style guidance below across colors, spacing, typography, surfaces, and visual polish while keeping the stylesheet production-ready.\n\n"
			"Node stylesheet context from frontend/src/styles/{Node}.css:\n"
			f"{truncated_contexts['node_style_context']}\n\n"
			"User-defined frontend style guidance:\n"
			f"{frontend_style_prompt.strip()}\n\n"
			"Reference app.css example:\n"
			f"{truncated_contexts['reference_app_css_source']}\n"
		)

	def _build_app_vue_user_prompt(
		self,
		*,
		node_names: Sequence[str],
		reference_app_source: str,
		generated_api_source: str,
		generated_store_source: str,
		generated_app_shell_source: str,
	) -> str:
		node_names_json = json.dumps(list(node_names), ensure_ascii=False, indent=2)
		truncated_contexts = self._truncate_prompt_contexts(
			request_label=self.generation_request_label,
			contexts={
				"reference_app_source": (reference_app_source, self.vue_reference_context_max_chars),
				"generated_api_source": (generated_api_source, self.vue_reference_context_max_chars),
				"generated_store_source": (generated_store_source, self.vue_reference_context_max_chars),
				"generated_app_shell_source": (generated_app_shell_source, self.vue_reference_context_max_chars),
			},
		)

		return (
			"Generate one Vue single-file component named App.vue for frontend/src/App.vue.\n"
			"Return only runnable Vue SFC code with no markdown fences or explanation.\n"
			"Never use this.$set or Vue.set; keep all reactive updates compatible with modern Vue patterns.\n"
			"Use the reference App.vue as the baseline integration pattern, but adapt it to the generated sources below.\n"
			"Import createWorkflowStore from ./store/workflow and AppShell from './components/AppShell.vue'.\n"
			"Use a named import for createWorkflowStore in the generated code.\n"
			"Import one node view component per visible graph node name, using ./views/<ActualNodeName>.vue paths.\n"
			"Do not invent extra view imports, do not import hidden or backend-only nodes, and never emit placeholder imports such as ./views/{nodes}.vue or ./views/<NodeName>.vue literally.\n"
			"Build a viewMap keyed by visible graph node name so App.vue becomes the composition root that wires the generated store, shell, and node views together.\n"
			"Provide workflowStore for descendants, call workflowStore.initialize() during setup, and keep hash-based routing aligned to known steps or node names.\n"
			"Use the generated AppShell.vue source as the primary contract for props, events, and slots. If it already expects active-step-id, active-view, or navigate handlers, preserve that interface instead of inventing a new one.\n"
			"Use the generated api/workflow.js and store/workflow.js as integration context so lifecycle and state usage stay consistent.\n"
			"When no node names are available, still render AppShell and initialize the workflow store without view imports.\n\n"
			"Visible graph node names for imports:\n"
			f"{node_names_json}\n\n"
			"Generated api/workflow.js context:\n"
			f"{truncated_contexts['generated_api_source']}\n\n"
			"Generated store/workflow.js context:\n"
			f"{truncated_contexts['generated_store_source']}\n\n"
			"Generated components/AppShell.vue context:\n"
			f"{truncated_contexts['generated_app_shell_source']}\n\n"
			"Reference App.vue example:\n"
			f"{truncated_contexts['reference_app_source']}\n"
		)

	@staticmethod
	def _detect_frontend_file_kind(file_path: Path) -> str:
		normalized = file_path.as_posix()
		if normalized.endswith("/api/workflow.js"):
			return "api"
		if normalized.endswith("/store/workflow.js"):
			return "store"
		if normalized.endswith("/components/AppShell.vue"):
			return "app_shell"
		if "/views/" in normalized and normalized.endswith(".vue"):
			return "view"
		if normalized.endswith("/styles/app.css"):
			return "app_css"
		if normalized.endswith("/App.vue"):
			return "app"
		raise ValueError(f"Unsupported frontend file for amendment: {file_path}")

	@staticmethod
	def _build_feedback_contract_text(file_kind: str) -> str:
		contracts = {
			"api": (
				"Preserve the api/workflow.js contract: exported fetch helpers, SSE parsing, "
				"runStep(payload, onEvent), resetSession(sessionId), and startCron(payload, onEvent) when cron mode is required.\n"
			),
			"store": (
				"Preserve the store/workflow.js contract: export createWorkflowStore() and STEP_METADATA, "
				"keep reactive state, dependency unlocking, auto-submit behavior, and AG-UI event handling.\n"
			),
			"app_shell": (
				"Preserve the AppShell.vue contract: operate on injected workflowStore, keep the session/progress top bar, "
				"progressive step cards, input surfaces, chat rendering, and schema-aware card rendering helpers.\n"
			),
			"app": (
				"Preserve the App.vue contract: remain the composition root, import { createWorkflowStore } from './store/workflow' and AppShell from './components/AppShell.vue', "
				"provide workflowStore, initialize it during setup, keep node-view routing aligned with visible workflow nodes only, and never add placeholder or hidden-node view imports.\n"
			),
			"view": (
				"Preserve the views/<Node>.vue contract: keep it focused on a single workflow step with injected workflowStore integration, "
				"and preserve the existing node template structure as literally as possible while applying only minimal Vue-specific fixes.\n"
			),
			"app_css": (
				"Preserve the app.css contract: keep the shared visual system and selectors required by the generated AppShell structure.\n"
			),
		}
		return contracts[file_kind]

	def _write_app_css_file(
		self,
		*,
		app_css_path: Path,
		reference_context: Mapping[str, str],
		target_path: Path,
		frontend_style_prompt: str | None,
		overwrite: bool,
		temperature: float,
		max_tokens: int,
	) -> Path:
		if frontend_style_prompt and frontend_style_prompt.strip():
			node_style_context = self._load_node_style_context(target_path)
			app_css_prompt = self._build_app_css_user_prompt(
				reference_app_css_source=reference_context["app_css"],
				node_style_context=node_style_context,
				frontend_style_prompt=frontend_style_prompt,
			)
			return self.code_to_file(
				app_css_prompt,
				str(app_css_path),
				overwrite=overwrite,
				temperature=temperature,
				max_tokens=max_tokens,
			)

		return self.write_code_to_file(
			reference_context["app_css"],
			str(app_css_path),
			overwrite=overwrite,
		)

	def _build_amendment_prompt(
		self,
		*,
		file_path: Path,
		original_code: str,
		rule_violations: str,
		steps_meta: Sequence[Mapping[str, Any]] | None = None,
		context_base_dir: str | Path | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		requirement_analysis_result: Mapping[str, Any] | None = None,
		frontend_style_prompt: str | None = None,
	) -> str:
		file_kind = self._detect_frontend_file_kind(file_path)
		contract_text = self._build_feedback_contract_text(file_kind)
		user_prompt = (
			"You are updating an existing AG-UI Vue frontend source file.\n"
			f"Target file: {file_path.name}\n"
			"Fix the listed rule violations while preserving valid existing behavior and file structure.\n"
			"Prefer the smallest viable edit; do not redesign the file unless a violation requires it.\n"
			"Every defined variable must be used; remove dead assignments.\n"
			"Do not use this.$set or Vue.set in the updated file; prefer direct assignment, object spread, or Object.assign for reactive state changes.\n"
			f"{contract_text}"
			"Return only runnable code without commentary or markdown fences.\n\n"
			"Existing code:\n"
			f"{original_code}\n\n"
			"Rule violations to fix:\n"
			f"{rule_violations}\n"
		)

		try:
			reference_context = self._load_reference_vue_frontend_context(reference_frontend_src_dir)
		except FileNotFoundError:
			reference_context = {}

		if file_kind == "api":
			reference_api_source = reference_context.get("api", "")
			user_prompt = self._append_prompt_context_block(
				user_prompt,
				heading="Reference api/workflow.js context",
				text=reference_api_source,
				label="reference_api_source",
				max_chars=self.vue_reference_context_max_chars,
				request_label=self.amendment_request_label,
			)
			cron_meta = normalize_requirement_analysis_result(requirement_analysis_result)
			if cron_meta and cron_meta["is_cron_task"]:
				user_prompt += "\nCron mode is enabled for this frontend; preserve cron-specific behavior if present.\n"

		normalized_steps: list[dict[str, Any]] = []
		if steps_meta:
			normalized_steps = self._normalize_steps(steps_meta)

		if file_kind in {"store", "app_shell"}:
			if normalized_steps:
				user_prompt += (
					"\nStep metadata JSON:\n"
					f"{json.dumps(normalized_steps, ensure_ascii=False, indent=2)}\n"
				)
			step_output_card_context = self._load_step_output_card_context(
				steps_meta=normalized_steps,
				output_path=file_path,
				base_dir=context_base_dir,
			) if normalized_steps else ""
			user_prompt = self._append_prompt_context_block(
				user_prompt,
				heading="Per-step StepRunOutput.card schema context",
				text=step_output_card_context,
				label="step_output_card_context",
				max_chars=self.step_output_card_context_max_chars,
				request_label=self.amendment_request_label,
			)
			if file_kind == "store":
				_, graph_plan_context = self._load_default_frontend_context(file_path, base_dir=context_base_dir)
				user_prompt = self._append_prompt_context_block(
					user_prompt,
					heading="Graph plan JSON context",
					text=graph_plan_context,
					label="graph_plan_context",
					max_chars=self.graph_plan_context_max_chars,
					request_label=self.amendment_request_label,
				)
			reference_key = "store" if file_kind == "store" else "app_shell"
			reference_source = reference_context.get(reference_key, "")
			user_prompt = self._append_prompt_context_block(
				user_prompt,
				heading=f"Reference {reference_key} context",
				text=reference_source,
				label=f"reference_{reference_key}_source",
				max_chars=self.vue_reference_context_max_chars,
				request_label=self.amendment_request_label,
			)

		if file_kind == "app":
			try:
				reference_app_source = self._load_reference_app_source(reference_frontend_src_dir)
			except FileNotFoundError:
				reference_app_source = ""
			user_prompt = self._append_prompt_context_block(
				user_prompt,
				heading="Reference App.vue context",
				text=reference_app_source,
				label="reference_app_source",
				max_chars=self.vue_reference_context_max_chars,
				request_label=self.amendment_request_label,
			)
			try:
				generated_context = self._load_generated_frontend_context(file_path)
			except FileNotFoundError:
				generated_context = {}
			for context_key, context_label in {
				"api": "Generated api/workflow.js context",
				"store": "Generated store/workflow.js context",
				"app_shell": "Generated AppShell.vue context",
			}.items():
				context_text = generated_context.get(context_key, "")
				user_prompt = self._append_prompt_context_block(
					user_prompt,
					heading=context_label,
					text=context_text,
					label=f"generated_{context_key}_source",
					max_chars=self.vue_reference_context_max_chars,
					request_label=self.amendment_request_label,
				)
			resolved_base_dir = self._resolve_context_base_dir(file_path, context_base_dir)
			graph_plan_path = resolved_base_dir / "workflow.json"
			if graph_plan_path.is_file():
				node_names = list(graph_to_nodes(graph_plan_path).keys())
				if node_names:
					user_prompt += (
						"\nGraph node names for imports:\n"
						f"{json.dumps(node_names, ensure_ascii=False, indent=2)}\n"
					)

		if file_kind == "app_css":
			reference_app_css_source = reference_context.get("app_css", "")
			user_prompt = self._append_prompt_context_block(
				user_prompt,
				heading="Reference app.css context",
				text=reference_app_css_source,
				label="reference_app_css_source",
				max_chars=self.vue_reference_context_max_chars,
				request_label=self.amendment_request_label,
			)
			if frontend_style_prompt and frontend_style_prompt.strip():
				user_prompt += (
					"\nUser-defined frontend style guidance:\n"
					f"{frontend_style_prompt.strip()}\n"
				)

		return user_prompt

	def amend_code_with_feedback(
		self,
		file_path: str | Path,
		rule_violations: str,
		*,
		steps_meta: Sequence[Mapping[str, Any]] | None = None,
		context_base_dir: str | Path | None = None,
		requirement_analysis_result: Mapping[str, Any] | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		frontend_style_prompt: str | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		target_path = Path(file_path).expanduser()
		if not target_path.exists():
			raise FileNotFoundError(f"Frontend file not found: {target_path}")

		original_code = target_path.read_text(encoding="utf-8")
		user_prompt = self._build_amendment_prompt(
			file_path=target_path,
			original_code=original_code,
			rule_violations=rule_violations,
			steps_meta=steps_meta,
			context_base_dir=context_base_dir,
			reference_frontend_src_dir=reference_frontend_src_dir,
			requirement_analysis_result=requirement_analysis_result,
			frontend_style_prompt=frontend_style_prompt,
		)

		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def _load_default_frontend_context(
		self,
		output_path: Path,
		base_dir: str | Path | None = None,
	) -> tuple[str, str]:
		"""Load workflow.json and node_ui/*.html from a user-provided or default base dir."""

		resolved_base_dir = self._resolve_context_base_dir(output_path, base_dir)
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

	@staticmethod
	def _extract_vue_template_block(vue_source: str) -> str:
		match = re.search(r"<template\b[^>]*>[\s\S]*?</template>", vue_source, re.IGNORECASE)
		return match.group(0) if match else vue_source

	def _load_node_view_template_context(self, output_path: Path) -> str:
		src_dir = output_path.parent.parent.resolve()
		views_dir = src_dir / "views"
		if not views_dir.is_dir():
			return f"[missing] no *.vue files found under: {views_dir}"

		template_chunks: list[str] = []
		for vue_file in sorted(views_dir.glob("*.vue")):
			try:
				vue_source = vue_file.read_text(encoding="utf-8")
			except UnicodeDecodeError:
				vue_source = vue_file.read_text(encoding="utf-8", errors="replace")
			template_chunks.append(
				f"\n=== {vue_file.name} ===\n{self._extract_vue_template_block(vue_source)}\n"
			)

		if not template_chunks:
			return f"[missing] no *.vue files found under: {views_dir}"

		return "\n".join(template_chunks)

	def _load_node_style_context(self, output_path: Path) -> str:
		src_dir = output_path.parent.parent.resolve()
		styles_dir = src_dir / "styles"
		if not styles_dir.is_dir():
			return f"[missing] no node *.css files found under: {styles_dir}"

		style_chunks: list[str] = []
		for css_file in sorted(styles_dir.glob("*.css")):
			if css_file.name == "app.css":
				continue
			try:
				css_source = css_file.read_text(encoding="utf-8")
			except UnicodeDecodeError:
				css_source = css_file.read_text(encoding="utf-8", errors="replace")
			style_chunks.append(f"\n=== {css_file.name} ===\n{css_source}\n")

		if not style_chunks:
			return f"[missing] no node *.css files found under: {styles_dir}"

		return "\n".join(style_chunks)

	def _load_step_output_card_context(
		self,
		*,
		steps_meta: Sequence[Mapping[str, Any]],
		output_path: Path,
		base_dir: str | Path | None = None,
	) -> str:
		resolved_base_dir = self._resolve_context_base_dir(output_path, base_dir)

		card_schemas: list[dict[str, Any]] = []
		for step in steps_meta:
			step_id = str(step.get("id", "")).strip()
			if not step_id:
				continue

			node_file = resolved_base_dir / f"{step_id}.py"
			if not node_file.exists():
				matches = sorted(resolved_base_dir.rglob(f"{step_id}.py"))
				node_file = matches[0] if matches else None
			if node_file is None or not node_file.exists():
				continue

			schema = compile_node_file_and_get_step_output_card_schema(str(node_file))
			if not schema:
				continue

			card_schemas.append(
				{
					"stepId": step_id,
					"title": schema.get("title") or str(step.get("title", "")).strip(),
					"source": str(node_file),
					"card": schema.get("card", {}),
				}
			)

		if not card_schemas:
			return f"[missing] no StepRunOutput card schemas found under: {resolved_base_dir}"

		return json.dumps(card_schemas, ensure_ascii=False, indent=2)

	def write_api_workflow_file(
		self,
		*,
		output_path: str | Path,
		run_step_endpoint: str = "/api/run-step",
		reset_session_endpoint: str = "/api/reset-session",
		requirement_analysis_result: Mapping[str, Any] | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		reference_context = self._load_reference_vue_frontend_context(reference_frontend_src_dir)
		user_prompt = self._build_api_user_prompt(
			run_step_endpoint=run_step_endpoint,
			reset_session_endpoint=reset_session_endpoint,
			reference_api_source=reference_context["api"],
			requirement_analysis_result=requirement_analysis_result,
		)
		return self.code_to_file(
			user_prompt,
			str(Path(output_path).expanduser()),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def write_store_workflow_file(
		self,
		*,
		steps_meta: Sequence[Mapping[str, Any]],
		output_path: str | Path,
		context_base_dir: str | None = None,
		run_step_endpoint: str = "/api/run-step",
		reset_session_endpoint: str = "/api/reset-session",
		requirement_analysis_result: Mapping[str, Any] | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		normalized_steps = self._normalize_steps(steps_meta)
		target_path = Path(output_path).expanduser()
		reference_context = self._load_reference_vue_frontend_context(reference_frontend_src_dir)
		_, graph_plan_context = self._load_default_frontend_context(
			target_path,
			base_dir=context_base_dir,
		)
		step_output_card_context = self._load_step_output_card_context(
			steps_meta=normalized_steps,
			output_path=target_path,
			base_dir=context_base_dir,
		)
		user_prompt = self._build_store_user_prompt(
			steps_meta=normalized_steps,
			run_step_endpoint=run_step_endpoint,
			reset_session_endpoint=reset_session_endpoint,
			requirement_analysis_result=requirement_analysis_result,
			reference_store_source=reference_context["store"],
			graph_plan_context=graph_plan_context,
			step_output_card_context=step_output_card_context,
		)
		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def write_app_shell_vue_file(
		self,
		*,
		steps_meta: Sequence[Mapping[str, Any]],
		output_path: str | Path,
		context_base_dir: str | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		frontend_style_prompt: str | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		normalized_steps = self._normalize_steps(steps_meta)
		target_path = Path(output_path).expanduser()
		reference_context = self._load_reference_vue_frontend_context(reference_frontend_src_dir)
		step_output_card_context = self._load_step_output_card_context(
			steps_meta=normalized_steps,
			output_path=target_path,
			base_dir=context_base_dir,
		)
		store_path = target_path.parent.parent / "store" / "workflow.js"
		if store_path.is_file():
			store_workflow_source = store_path.read_text(encoding="utf-8")
		else:
			store_workflow_source = reference_context["store"]
		node_view_template_context = self._load_node_view_template_context(target_path)
		app_css_path = target_path.parent.parent / "styles" / "app.css"
		self._write_app_css_file(
			app_css_path=app_css_path,
			reference_context=reference_context,
			target_path=target_path,
			frontend_style_prompt=frontend_style_prompt,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)
		user_prompt = self._build_app_shell_user_prompt(
			steps_meta=normalized_steps,
			store_workflow_source=store_workflow_source,
			reference_app_shell_source=reference_context["app_shell"],
			node_view_template_context=node_view_template_context,
			step_output_card_context=step_output_card_context,
		)
  
		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def write_app_file(
		self,
		*,
		steps_meta: Sequence[Mapping[str, Any]],
		output_path: str | Path,
		context_base_dir: str | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		target_path = Path(output_path).expanduser()
		resolved_base_dir = self._resolve_context_base_dir(target_path, context_base_dir)
		graph_plan_path = resolved_base_dir / "workflow.json"
		reference_app_source = self._load_reference_app_source(reference_frontend_src_dir)
		node_names = self._load_frontend_visible_node_names(graph_plan_path)
		generated_context = self._load_generated_frontend_context(target_path)
		user_prompt = self._build_app_vue_user_prompt(
			node_names=node_names,
			reference_app_source=reference_app_source,
			generated_api_source=generated_context["api"],
			generated_store_source=generated_context["store"],
			generated_app_shell_source=generated_context["app_shell"],
		)
		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def write_frontend_src_files(
		self,
		*,
		steps_meta: Sequence[Mapping[str, Any]],
		store_steps_meta: Sequence[Mapping[str, Any]] | None = None,
		output_base_dir: str | Path,
		context_base_dir: str | None = None,
		run_step_endpoint: str = "/api/run-step",
		reset_session_endpoint: str = "/api/reset-session",
		requirement_analysis_result: Mapping[str, Any] | None = None,
		reference_frontend_src_dir: str | Path | None = None,
		frontend_style_prompt: str | None = None,
		overwrite: bool = True,
		temperature: float = 0.2,
		api_max_tokens: int = MAX_TOKENS,
		store_max_tokens: int = MAX_TOKENS,
		app_shell_max_tokens: int = MAX_TOKENS,
		app_max_tokens: int = MAX_TOKENS,
	) -> dict[str, Path]:
		base_dir = Path(output_base_dir).expanduser()
		api_path = base_dir / "api" / "workflow.js"
		store_path = base_dir / "store" / "workflow.js"
		app_shell_path = base_dir / "components" / "AppShell.vue"
		app_path = base_dir / "App.vue"
		app_css_path = base_dir / "styles" / "app.css"

		api_output = _run_stage(
			"api workflow file",
			api_path,
			self.write_api_workflow_file,
			output_path=api_path,
			run_step_endpoint=run_step_endpoint,
			reset_session_endpoint=reset_session_endpoint,
			requirement_analysis_result=requirement_analysis_result,
			reference_frontend_src_dir=reference_frontend_src_dir,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=api_max_tokens,
		)
		store_output = _run_stage(
			"store workflow file",
			store_path,
			self.write_store_workflow_file,
			steps_meta=store_steps_meta if store_steps_meta is not None else steps_meta,
			output_path=store_path,
			context_base_dir=context_base_dir,
			run_step_endpoint=run_step_endpoint,
			reset_session_endpoint=reset_session_endpoint,
			requirement_analysis_result=requirement_analysis_result,
			reference_frontend_src_dir=reference_frontend_src_dir,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=store_max_tokens,
		)
		app_shell_output = _run_stage(
			"app shell file",
			app_shell_path,
			self.write_app_shell_vue_file,
			steps_meta=steps_meta,
			output_path=app_shell_path,
			context_base_dir=context_base_dir,
			reference_frontend_src_dir=reference_frontend_src_dir,
			frontend_style_prompt=frontend_style_prompt,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=app_shell_max_tokens,
		)
		app_output = _run_stage(
			"app file",
			app_path,
			self.write_app_file,
			steps_meta=steps_meta,
			output_path=app_path,
			context_base_dir=context_base_dir,
			reference_frontend_src_dir=reference_frontend_src_dir,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=app_max_tokens,
		)
		print(f"finished writing frontend files to: {base_dir}")

		return {
			"api": api_output,
			"store": store_output,
			"app_shell": app_shell_output,
			"app": app_output,
			"app_css": app_css_path,
		}



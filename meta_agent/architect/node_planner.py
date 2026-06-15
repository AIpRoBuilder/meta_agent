import sys
import json
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from pydaograph import CStatus, GElement, GPipeline

_DEFAULT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_META_AGENT_SPEC = importlib.util.find_spec("meta_agent")
if _META_AGENT_SPEC and _META_AGENT_SPEC.origin:
	ROOT_DIR = Path(_META_AGENT_SPEC.origin).resolve().parent
else:
	ROOT_DIR = _DEFAULT_PACKAGE_ROOT

if str(ROOT_DIR.parent) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR.parent))

from meta_agent.llm_client.coder import Coder, MAX_TOKENS


class _NodePlanElement(GElement):
	def __init__(
		self,
		planner: "NodePlanner",
		node: dict[str, Any],
		index: int,
		target_dir: Path,
		requirement_text: str,
		overwrite: bool,
		temperature: float,
		max_tokens: int,
		outputs: dict[str, Path],
	) -> None:
		super().__init__()
		self.planner = planner
		self.node = node
		self.index = index
		self.target_dir = target_dir
		self.requirement_text = requirement_text
		self.overwrite = overwrite
		self.temperature = temperature
		self.max_tokens = max_tokens
		self.outputs = outputs

	def _build_node_prompt(self, requirement_text: str, node_context: str) -> str:
		return (
			"Generate a VERY SHORT markdown note for this SINGLE node only.\n"
			"Goal: briefly describe what this node will achieve and list the core functions to implement.\n"
			"Do NOT provide detailed implementation steps, dependency handling details, output contract details, or TODO lists.\n"
			"Input sources to use: requirement analysis + node desc + ext_data-derived node type.\n"
			"If ext_data.type='user_input' and inputs_format is provided, only mention the required validation/parsing at a high level.\n"
			"Node type must align with workflow reference contracts.\n"
			"Keep output concise and practical (MVP-first, no extra features).\n\n"
			"Mandatory output sections:\n"
			"1) # Node Brief\n"
			"2) ## What This Node Achieves (2-4 sentences)\n"
			"3) ## Core Functions (bullet list of function names with one-line purpose each)\n\n"
			"Requirement analysis markdown:\n"
			f"{requirement_text}\n\n"
			"Target node context:\n"
			f"{node_context}\n"
		)

	def run(self) -> CStatus:
		try:
			node_name = str(self.node.get("name", "")).strip() or f"Node{self.index}"
			node_context     = self.planner._node_context(self.node, self.index)
			node_file = self.target_dir / self.planner._node_filename(self.node, self.index)

			user_prompt = self._build_node_prompt(self.requirement_text, node_context)
			written = self.planner.code_to_file(
				user_prompt,
				str(node_file),
				overwrite=self.overwrite,
				temperature=self.temperature,
				max_tokens=self.max_tokens,
			)
			self.outputs[node_name] = written
			return CStatus()
		except Exception as exc:
			return CStatus(1001, f"node planning failed for index {self.index}: {exc}")


class _NodeUIElement(GElement):
	def __init__(
		self,
		planner: "NodePlanner",
		node: dict[str, Any],
		index: int,
		target_dir: Path,
		requirement_text: str,
		overwrite: bool,
		temperature: float,
		max_tokens: int,
		outputs: dict[str, Path],
		user_prompt: Optional[str] = None,
	) -> None:
		super().__init__()
		self.planner = planner
		self.node = node
		self.index = index
		self.target_dir = target_dir
		self.requirement_text = requirement_text
		self.overwrite = overwrite
		self.temperature = temperature
		self.max_tokens = max_tokens
		self.outputs = outputs
		self.user_prompt: Optional[str] = user_prompt
		# Each UI element owns its own Coder instance so LLM calls are independent.
		self.coder: Coder = planner._make_coder()

	def set_user_prompt(self, user_prompt: str) -> None:
		"""Set the user prompt to use when this element runs.

		Calling this before :meth:`run` will override the auto-generated prompt.
		"""
		self.user_prompt = user_prompt

	def run(self) -> CStatus:
		try:
			node_name = str(self.node.get("name", "")).strip() or f"Node{self.index}"
			node_context = self.planner._node_context(self.node, self.index)
			node_file = self.target_dir / self.planner._node_ui_filename(self.node, self.index)

			if self.user_prompt is None:
				self.user_prompt = self.planner._build_node_ui_prompt(self.requirement_text, node_context)
			written = self.coder.code_to_file(
				self.user_prompt,
				str(node_file),
				overwrite=self.overwrite,
				temperature=self.temperature,
				max_tokens=self.max_tokens,
			)
			self.outputs[node_name] = written
			return CStatus()
		except Exception as exc:
			return CStatus(1001, f"node ui planning failed for index {self.index}: {exc}")


@dataclass
class NodePlanner:
	"""Generate a concise markdown implementation brief for graph nodes.

	The brief is derived from:
	- requirement analysis markdown
	- node desc/dependency/ext_data from graph_plan.json
	- workflow node reference excerpts

	Output format is markdown (.md) that lists suggested tools/functions per node.

	Note: This class is NOT a subclass of Coder. It holds coder configuration and
	creates Coder instances on demand via :meth:`_make_coder`.
	"""

	prompt_path: str = "architect/prompts/node_planner_prompt.md"
	workflow_nodes_reference_path: str = "library/workflow_nodes_reference_excerpts.md"
	# Coder configuration fields (forwarded to Coder instances)
	provider: str = "openai"
	model: str = "gpt-4.1-mini"
	api_key: Optional[str] = None
	zhipu_thinking: Optional[dict] = None
	deepseek_base_url: str = "https://api.deepseek.com"
	qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
	client: Optional[object] = None
	ui_elements: dict[str, _NodeUIElement] = None  # type: ignore

	def __post_init__(self) -> None:
		prompt_file = ROOT_DIR / self.prompt_path
		if not prompt_file.exists():
			raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

		nodes_reference_file = ROOT_DIR / self.workflow_nodes_reference_path
		if not nodes_reference_file.exists():
			raise FileNotFoundError(
				f"Workflow nodes reference file not found: {nodes_reference_file}"
			)

		base_prompt = prompt_file.read_text(encoding="utf-8")
		nodes_reference = nodes_reference_file.read_text(encoding="utf-8")
		self.system_prompt = (
			f"{base_prompt}\n\n"
			"## Workflow Node Reference (Authoritative)\n"
			"When recommending tools/functions and implementation contracts,\n"
			"strictly follow the following workflow node reference.\n\n"
			f"{nodes_reference}\n"
		)
		# Build the shared coder used by _NodePlanElement / code_to_file.
		self._coder: Coder = self._make_coder()

	def _make_coder(self) -> Coder:
		"""Create and return a fresh :class:`Coder` configured with this planner's settings."""
		return Coder(
			provider=self.provider,
			model=self.model,
			api_key=self.api_key,
			system_prompt=self.system_prompt,
			zhipu_thinking=self.zhipu_thinking,
			deepseek_base_url=self.deepseek_base_url,
			qwen_base_url=self.qwen_base_url,
			client=self.client,
		)

	def code_to_file(
		self,
		user_prompt: str,
		file_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		"""Delegate to the shared internal :class:`Coder` instance."""
		return self._coder.code_to_file(
			user_prompt,
			file_path,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def _normalize_ext_type(self, ext_data: Any) -> str:
		if isinstance(ext_data, dict):
			return str(ext_data.get("type", "none")).strip().lower() or "none"
		if isinstance(ext_data, str):
			return ext_data.strip().lower() or "none"
		return "none"

	def _derive_node_profile(self, ext_data: Any) -> dict[str, Any]:
		ext_type = self._normalize_ext_type(ext_data)
		service_name = ""
		skill_name = ""
		if isinstance(ext_data, dict):
			service_name = str(ext_data.get("service_name", "")).strip()
			skill_name = str(ext_data.get("skill_name", "")).strip()

		if ext_type == "skill" or skill_name:
			return {
				"extType": ext_type,
				"nodeKind": "skill",
				"baseClass": "WorkflowSkillNode",
				"primaryFunctions": ["process_operation"],
				"skillName": skill_name,
				"note": (
					f"Skill node wrapping skill '{skill_name}': "
					"set SKILL_DIR / SKILL_MD_PATH class attributes pointing to the skill directory, "
					"then implement process_operation(user_input, dependency_results, session_state) to invoke the skill logic using "
					"self.skill_description, self.skill_using, self.skill_examples from the parsed skill.md."
				)
				if skill_name
				else (
					"Skill node: set SKILL_DIR / SKILL_MD_PATH and implement process_operation(user_input, dependency_results, session_state)."
				),
			}

		if ext_type == "service" or service_name:
			return {
				"extType": ext_type,
				"nodeKind": "service",
				"baseClass": "WorkflowServiceNode",
				"primaryFunctions": ["build_instance_spec"],
				"note": "Service bootstrap node: prepares service run/probe spec for sandbox or local execution.",
			}

		if ext_type == "chat_input":
			return {
				"extType": ext_type,
				"nodeKind": "chat",
				"baseClass": "WorkflowChatNode",
				"primaryFunctions": ["process_chat", "build_user_prompt"],
				"note": "Conversational node: combines user chat input with dependency outputs; validates inputs_format when present.",
			}
		if ext_type == "user_file_input":
			return {
				"extType": ext_type,
				"nodeKind": "file",
				"baseClass": "WorkflowFileNode",
				"primaryFunctions": ["build_step_output(optional)", "save_files_remote(optional)"],
				"note": "File-upload node: persists uploaded files and can optionally customize StepRunOutput via build_step_output.",
			}
		if ext_type == "user_input":
			return {
				"extType": ext_type,
				"nodeKind": "input",
				"baseClass": "WorkflowStepNode",
				"primaryFunctions": ["process_input"],
				"note": "Text-input step node: validates user input against inputs_format (if present) and computes output.",
			}

		return {
			"extType": ext_type,
			"nodeKind": "operation",
			"baseClass": "WorkflowOperationNode",
			"primaryFunctions": ["process_operation"],
			"note": "Compute/process node: dependency-driven without direct user input.",
		}

	def _build_nodes_context(self, graph_plan: dict[str, Any]) -> str:
		nodes = graph_plan.get("nodes", []) if isinstance(graph_plan, dict) else []
		if not isinstance(nodes, list) or not nodes:
			return "(No nodes found in graph plan)"

		lines: list[str] = []
		for idx, node in enumerate(nodes, start=1):
			if not isinstance(node, dict):
				continue

			name = str(node.get("name", "")).strip() or f"Node{idx}"
			desc = str(node.get("desc", "")).strip()
			depends = node.get("depends", [])
			if not isinstance(depends, list):
				depends = []
			ext_data = node.get("ext_data", {})
			inputs_format = node.get("inputs_format", {})
			if not isinstance(inputs_format, dict):
				inputs_format = {}
			profile = self._derive_node_profile(ext_data)

			ext_desc = ""
			service_name_val = ""
			skill_name_val = ""
			if isinstance(ext_data, dict):
				ext_desc = str(ext_data.get("desc", "")).strip()
				service_name_val = str(ext_data.get("service_name", "")).strip()
				skill_name_val = str(ext_data.get("skill_name", "")).strip()

			node_lines = [
				f"### Node {idx}: {name}",
				f"- desc: {desc}",
				f"- depends: {', '.join(depends) if depends else 'none'}",
				f"- ext_data.type: {profile['extType']}",
				f"- ext_data.desc: {ext_desc or 'n/a'}",
			]
			if profile["extType"] == "user_input":
				node_lines.append(
					f"- inputs_format: {json.dumps(inputs_format, ensure_ascii=False) if inputs_format else 'n/a'}"
				)
			if service_name_val:
				node_lines.append(f"- ext_data.service_name: {service_name_val}")
			if skill_name_val:
				node_lines.append(f"- ext_data.skill_name: {skill_name_val}")
			node_lines.extend(
				[
					f"- derived node kind: {profile['nodeKind']}",
					f"- recommended base class: {profile['baseClass']}",
					f"- primary functions: {', '.join(profile['primaryFunctions'])}",
					f"- note: {profile['note']}",
					"",
				]
			)
			lines.extend(node_lines)

		return "\n".join(lines).strip()

	def _extract_nodes(self, graph_plan: dict[str, Any]) -> list[dict[str, Any]]:
		nodes = graph_plan.get("nodes", []) if isinstance(graph_plan, dict) else []
		if not isinstance(nodes, list):
			return []
		return [node for node in nodes if isinstance(node, dict)]

	def _node_context(self, node: dict[str, Any], index: int) -> str:
		name = str(node.get("name", "")).strip() or f"Node{index}"
		desc = str(node.get("desc", "")).strip()
		depends = node.get("depends", [])
		if not isinstance(depends, list):
			depends = []
		services = node.get("services", [])
		if not isinstance(services, list):
			services = []
		ext_data = node.get("ext_data", {})
		inputs_format = node.get("inputs_format", {})
		if not isinstance(inputs_format, dict):
			inputs_format = {}
		profile = self._derive_node_profile(ext_data)

		ext_desc = ""
		service_name_val = ""
		skill_name_val = ""
		if isinstance(ext_data, dict):
			ext_desc = str(ext_data.get("desc", "")).strip()
			service_name_val = str(ext_data.get("service_name", "")).strip()
			skill_name_val = str(ext_data.get("skill_name", "")).strip()

		ctx_lines = [
			f"### Node {index}: {name}",
			f"- desc: {desc}",
			f"- depends: {', '.join(depends) if depends else 'none'}",
			f"- ext_data.type: {profile['extType']}",
			f"- ext_data.desc: {ext_desc or 'n/a'}",
		]
		if profile["extType"] == "user_input":
			ctx_lines.append(
				f"- inputs_format: {json.dumps(inputs_format, ensure_ascii=False) if inputs_format else 'n/a'}"
			)
		if service_name_val:
			ctx_lines.append(f"- ext_data.service_name: {service_name_val}")
		if skill_name_val:
			ctx_lines.append(f"- ext_data.skill_name: {skill_name_val}")
		if services:
			ctx_lines.append(f"- services: {json.dumps(services, ensure_ascii=False)}")
		else:
			ctx_lines.append("- services: none")
		ctx_lines.extend(
			[
				f"- derived node kind: {profile['nodeKind']}",
				f"- recommended base class: {profile['baseClass']}",
				f"- primary functions: {', '.join(profile['primaryFunctions'])}",
				f"- note: {profile['note']}",
			]
		)
		return "\n".join(ctx_lines)

	def _node_filename(self, node: dict[str, Any], index: int) -> str:
		name = str(node.get("name", "")).strip() or f"Node{index}"
		return f"{name}.md"

	def _node_ui_filename(self, node: dict[str, Any], index: int) -> str:
		name = str(node.get("name", "")).strip() or f"Node{index}"
		return f"{name}.html"

	def _build_node_ui_prompt(self, requirement_text: str, node_context: str) -> str:
		return (
			"Generate a SINGLE, self-contained HTML file for this node's user interaction UI.\n"
			"Goal: provide a minimal, practical interface for end-user interaction at this workflow step.\n"
			"Use requirement analysis and node metadata context to decide UI fields, hints, and submit interaction.\n"
			"The output must be valid HTML only (no markdown fences, no explanations).\n"
			"MVP-first: keep UI simple, clear, and focused on required inputs/outputs.\n"
			"Include: semantic structure, labels, input controls, basic inline styles, and a submit action area.\n"
			"If ext_data.type='user_input' and inputs_format exists, map form fields to that schema.\n"
			"If the node is not directly user-input-driven, present read-only dependency context and action trigger.\n\n"
			"Requirement analysis markdown:\n"
			f"{requirement_text}\n\n"
			"Target node context:\n"
			f"{node_context}\n"
		)

	def plan_each_from_files(
		self,
		requirement_md_path: str,
		graph_plan_json_path: str,
		output_dir: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.05,
		max_tokens: int = MAX_TOKENS,
	) -> list[Path]:
		"""Generate one brief markdown file per node, named `<node_name>.md`."""

		requirement_path = Path(requirement_md_path)
		if not requirement_path.exists():
			raise FileNotFoundError(f"Requirement file not found: {requirement_path}")

		graph_path = Path(graph_plan_json_path)
		if not graph_path.exists():
			raise FileNotFoundError(f"Graph plan file not found: {graph_path}")

		requirement_text = requirement_path.read_text(encoding="utf-8")
		graph_plan_text = graph_path.read_text(encoding="utf-8")

		return self.plan_each(
			requirement_text=requirement_text,
			graph_plan_text=graph_plan_text,
			output_dir=output_dir,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def plan_each(
		self,
		requirement_text: str,
		graph_plan_text: str,
		output_dir: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> list[Path]:
		"""Generate one brief node summary markdown for each node into `output_dir`.

		Each file is intentionally high-level and includes only:
		- what the node will achieve
		- core function names with short purposes
		"""

		try:
			graph_plan: dict[str, Any] = json.loads(graph_plan_text)
		except json.JSONDecodeError as exc:
			raise ValueError(f"Invalid graph plan JSON: {exc}") from exc

		nodes = self._extract_nodes(graph_plan)
		if not nodes:
			return []

		target_dir = Path(output_dir)
		target_dir.mkdir(parents=True, exist_ok=True)

		pipeline = GPipeline()
		node_entries: list[tuple[int, dict[str, Any], str]] = []
		elements: dict[str, _NodePlanElement] = {}
		node_outputs: dict[str, Path] = {}

		for index, node in enumerate(nodes, start=1):
			node_name = str(node.get("name", "")).strip() or f"Node{index}"
			node_entries.append((index, node, node_name))
			elements[node_name] = _NodePlanElement(
				planner=self,
				node=node,
				index=index,
				target_dir=target_dir,
				requirement_text=requirement_text,
				overwrite=overwrite,
				temperature=temperature,
				max_tokens=max_tokens,
				outputs=node_outputs,
			)

		for index, node, node_name in node_entries:
			depends = node.get("depends", [])
			dep_names = depends if isinstance(depends, list) else []
			dep_elements = {elements[dep_name] for dep_name in dep_names if dep_name in elements}
			status = pipeline.registerGElement(elements[node_name], dep_elements, node_name, 1)
			if status.isErr():
				raise RuntimeError(f"registerGElement failed for {node_name}: {status.getInfo()}")

		process_status = pipeline.process()
		if process_status.isErr():
			raise RuntimeError(f"plan_each pipeline.process failed: {process_status.getInfo()}")

		output_paths: list[Path] = []
		for index, _node, node_name in node_entries:
			if node_name in node_outputs:
				output_paths.append(node_outputs[node_name])
			else:
				expected = target_dir / self._node_filename(_node, index)
				if expected.exists():
					output_paths.append(expected)

		return output_paths

	def _build_amend_node_ui_prompt(
		self,
		user_prompt: str,
		old_html: str,
		requirement_text: str,
		node_context: str,
	) -> str:
		return (
			"You are rewriting an existing node UI HTML file based on user feedback.\n"
			"Produce a SINGLE, self-contained valid HTML file. No markdown fences, no explanations.\n"
			"Apply the user's amendment instructions while keeping parts not mentioned intact.\n"
			"Use the requirement analysis and node metadata as background context.\n\n"
			"=== Requirement Analysis ===\n"
			f"{requirement_text}\n\n"
			"=== Node Context ===\n"
			f"{node_context}\n\n"
			"=== Existing HTML (to amend) ===\n"
			f"{old_html}\n\n"
			"=== Amendment Instructions (apply these changes) ===\n"
			f"{user_prompt}\n"
		)

	def amend_node_ui(
		self,
		node_name: str,
		user_prompt: str,
		old_html: str,
		requirement_text: str,
		graph_plan_text: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		"""Rewrite a single node UI HTML file using user feedback.

		This method reuses the previously-created :class:`_NodeUIElement`
		stored in ``self.ui_elements`` (typically populated by
		:meth:`plan_each_ui`) and executes its :meth:`run` method.

		Args:
			node_name: Name of the node whose UI is being amended (must match a node in graph_plan).
			user_prompt: Amendment instructions describing what to change.
			old_html: Current HTML content of the node UI file.
			requirement_text: Full requirement analysis markdown.
			graph_plan_text: JSON string of the graph plan (to extract node metadata).
			output_path: Destination file path for the rewritten HTML.
			overwrite: Whether to overwrite an existing file (default True).
			temperature: LLM sampling temperature.
			max_tokens: LLM max output tokens.

		Returns:
			Path to the written HTML file.
		"""
		try:
			graph_plan: dict[str, Any] = json.loads(graph_plan_text)
		except json.JSONDecodeError as exc:
			raise ValueError(f"Invalid graph plan JSON: {exc}") from exc

		nodes = self._extract_nodes(graph_plan)
		matched_node: dict[str, Any] | None = None
		matched_index = 1
		for idx, node in enumerate(nodes, start=1):
			name = str(node.get("name", "")).strip() or f"Node{idx}"
			if name == node_name:
				matched_node = node
				matched_index = idx
				break

		if matched_node is None:
			raise ValueError(
				f"Node '{node_name}' not found in graph plan. "
				f"Available nodes: {[str(n.get('name','')).strip() for n in nodes]}"
			)

		if not isinstance(self.ui_elements, dict) or node_name not in self.ui_elements:
			raise ValueError(
				f"UI element for node '{node_name}' not found in planner cache. "
				"Run plan_each_ui(...) first to initialize self.ui_elements."
			)

		node_context = self._node_context(matched_node, matched_index)
		prompt = self._build_amend_node_ui_prompt(user_prompt, old_html, requirement_text, node_context)

		ui_element = self.ui_elements[node_name]
		output_target = Path(output_path)
		ui_element.target_dir = output_target.parent
		ui_element.overwrite = overwrite
		ui_element.temperature = temperature
		ui_element.max_tokens = max_tokens
		ui_element.requirement_text = requirement_text
		ui_element.set_user_prompt(prompt)

		status = ui_element.run()
		if status.isErr():
			raise RuntimeError(f"amend_node_ui failed for '{node_name}': {status.getInfo()}")

		written = ui_element.outputs.get(node_name)
		if written is None:
			written = ui_element.target_dir / self._node_ui_filename(matched_node, matched_index)

		if not written.exists():
			raise RuntimeError(
				f"amend_node_ui did not produce expected output file for '{node_name}': {written}"
			)

		if written.resolve() == output_target.resolve():
			return written

		if output_target.exists() and not overwrite:
			raise FileExistsError(f"Output file exists and overwrite=False: {output_target}")

		output_target.parent.mkdir(parents=True, exist_ok=True)
		output_target.write_text(written.read_text(encoding="utf-8"), encoding="utf-8")
		return output_target

	def amend_node_ui_from_files(
		self,
		node_name: str,
		user_prompt: str,
		existing_html_path: str,
		requirement_md_path: str,
		graph_plan_json_path: str,
		output_path: str | None = None,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		"""File-based wrapper for :meth:`amend_node_ui`.

		Args:
			node_name: Name of the node whose UI is being amended.
			user_prompt: Amendment instructions describing what to change.
			existing_html_path: Path to the current HTML file for this node UI.
			requirement_md_path: Path to the requirement analysis markdown file.
			graph_plan_json_path: Path to the graph plan JSON file.
			output_path: Destination path for the rewritten HTML.
			                Defaults to overwriting ``existing_html_path`` when None.
			overwrite: Whether to overwrite an existing output file.
			temperature: LLM sampling temperature.
			max_tokens: LLM max output tokens.
		"""
		html_path = Path(existing_html_path)
		if not html_path.exists():
			raise FileNotFoundError(f"Existing HTML file not found: {html_path}")

		req_path = Path(requirement_md_path)
		if not req_path.exists():
			raise FileNotFoundError(f"Requirement file not found: {req_path}")

		graph_path = Path(graph_plan_json_path)
		if not graph_path.exists():
			raise FileNotFoundError(f"Graph plan file not found: {graph_path}")

		old_html = html_path.read_text(encoding="utf-8")
		requirement_text = req_path.read_text(encoding="utf-8")
		graph_plan_text = graph_path.read_text(encoding="utf-8")

		dest = output_path if output_path is not None else str(html_path)

		return self.amend_node_ui(
			node_name=node_name,
			user_prompt=user_prompt,
			old_html=old_html,
			requirement_text=requirement_text,
			graph_plan_text=graph_plan_text,
			output_path=dest,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def plan_each_ui_from_files(
		self,
		requirement_md_path: str,
		graph_plan_json_path: str,
		output_dir: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> list[Path]:
		"""Generate one HTML UI file per node into `<output_dir>/node_ui`."""

		requirement_path = Path(requirement_md_path)
		if not requirement_path.exists():
			raise FileNotFoundError(f"Requirement file not found: {requirement_path}")

		graph_path = Path(graph_plan_json_path)
		if not graph_path.exists():
			raise FileNotFoundError(f"Graph plan file not found: {graph_path}")

		requirement_text = requirement_path.read_text(encoding="utf-8")
		graph_plan_text = graph_path.read_text(encoding="utf-8")

		return self.plan_each_ui(
			requirement_text=requirement_text,
			graph_plan_text=graph_plan_text,
			output_dir=output_dir,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def plan_each_ui(
		self,
		requirement_text: str,
		graph_plan_text: str,
		output_dir: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.05,
		max_tokens: int = MAX_TOKENS,
	) -> list[Path]:
		"""Generate one HTML UI file per node into `node_ui` under `output_dir`."""

		try:
			graph_plan: dict[str, Any] = json.loads(graph_plan_text)
		except json.JSONDecodeError as exc:
			raise ValueError(f"Invalid graph plan JSON: {exc}") from exc

		nodes = self._extract_nodes(graph_plan)
		if not nodes:
			return []

		target_dir = Path(output_dir)
		target_dir.mkdir(parents=True, exist_ok=True)

		pipeline = GPipeline()
		node_entries: list[tuple[int, dict[str, Any], str]] = []
		elements: dict[str, _NodeUIElement] = {}
		node_outputs: dict[str, Path] = {}

		for index, node in enumerate(nodes, start=1):
			node_name = str(node.get("name", "")).strip() or f"Node{index}"
			node_entries.append((index, node, node_name))
			elements[node_name] = _NodeUIElement(
				planner=self,
				node=node,
				index=index,
				target_dir=target_dir,
				requirement_text=requirement_text,
				overwrite=overwrite,
				temperature=temperature,
				max_tokens=max_tokens,
				outputs=node_outputs,
			)

		for index, node, node_name in node_entries:
			depends = node.get("depends", [])
			dep_names = depends if isinstance(depends, list) else []
			dep_elements = {elements[dep_name] for dep_name in dep_names if dep_name in elements}
			status = pipeline.registerGElement(elements[node_name], dep_elements, node_name, 1)
			if status.isErr():
				raise RuntimeError(f"registerGElement failed for {node_name}: {status.getInfo()}")

		process_status = pipeline.process()
		if process_status.isErr():
			raise RuntimeError(f"plan_each_ui pipeline.process failed: {process_status.getInfo()}")

		self.ui_elements = elements  # type: ignore
		output_paths: list[Path] = []
		for index, node, node_name in node_entries:
			if node_name in node_outputs:
				output_paths.append(node_outputs[node_name])
			else:
				expected = target_dir / self._node_ui_filename(node, index)
				if expected.exists():
					output_paths.append(expected)

		return output_paths
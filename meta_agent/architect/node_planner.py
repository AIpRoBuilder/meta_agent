import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder


@dataclass
class NodePlanner(Coder):
	"""Generate a concise markdown implementation brief for graph nodes.

	The brief is derived from:
	- requirement analysis markdown
	- node desc/dependency/ext_data from graph_plan.json
	- workflow node reference excerpts

	Output format is markdown (.md) that lists suggested tools/functions per node.
	"""

	prompt_path: str = "architect/prompts/node_planner_prompt.md"
	workflow_nodes_reference_path: str = "library/workflow_nodes_reference_excerpts.md"

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
		super().__post_init__()

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
					"then implement process_operation() to invoke the skill logic using "
					"self.skill_description, self.skill_using, self.skill_examples from the parsed skill.md."
				)
				if skill_name
				else (
					"Skill node: set SKILL_DIR / SKILL_MD_PATH and implement process_operation()."
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
				"note": "Conversational node: combines user chat input with dependency outputs.",
			}
		if ext_type == "user_file_input":
			return {
				"extType": ext_type,
				"nodeKind": "file",
				"baseClass": "WorkflowFileNode",
				"primaryFunctions": ["process_files", "save_files_remote(optional)"],
				"note": "File-upload node: handles persisted files and emits structured derived outputs.",
			}
		if ext_type == "image":
			return {
				"extType": ext_type,
				"nodeKind": "image",
				"baseClass": "WorkflowImageNode",
				"primaryFunctions": ["process_images_prompts", "process_image_prompts"],
				"note": "Vision node: consumes image refs from dependencies; no direct upload handler.",
			}
		if ext_type == "user_input":
			return {
				"extType": ext_type,
				"nodeKind": "input",
				"baseClass": "WorkflowStepNode",
				"primaryFunctions": ["process_input"],
				"note": "Text-input step node: validates user input and computes output.",
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
		ext_data = node.get("ext_data", {})
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
		if service_name_val:
			ctx_lines.append(f"- ext_data.service_name: {service_name_val}")
		if skill_name_val:
			ctx_lines.append(f"- ext_data.skill_name: {skill_name_val}")
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

	def plan_each_from_files(
		self,
		requirement_md_path: str,
		graph_plan_json_path: str,
		output_dir: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.05,
		max_tokens: int = 12000,
	) -> list[Path]:
		"""Generate one markdown file per node, named `<node_name>.md`."""

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
		temperature: float = 0.05,
		max_tokens: int = 12000,
	) -> list[Path]:
		"""Generate one concise markdown brief for each node into `output_dir`."""

		try:
			graph_plan: dict[str, Any] = json.loads(graph_plan_text)
		except json.JSONDecodeError as exc:
			raise ValueError(f"Invalid graph plan JSON: {exc}") from exc

		nodes = self._extract_nodes(graph_plan)
		if not nodes:
			return []

		target_dir = Path(output_dir)
		target_dir.mkdir(parents=True, exist_ok=True)

		output_paths: list[Path] = []
		for index, node in enumerate(nodes, start=1):
			node_context = self._node_context(node, index)
			node_file = target_dir / self._node_filename(node, index)

			user_prompt = (
				"Generate a BRIEF markdown implementation guide for this SINGLE node only.\n"
				"Goal: recommend concrete tools/functions and a short implementation strategy.\n"
				"Input sources to use: requirement analysis + node desc + ext_data-derived node type.\n"
				"Node type must align with workflow reference contracts.\n"
				"Keep output concise and practical (MVP-first, no extra features).\n\n"
				"Mandatory output sections:\n"
				"1) # Node Implementation Brief\n"
				"2) ## Node Summary\n"
				"3) ## Tools and Functions\n"
				"4) ## Input/Dependency Handling\n"
				"5) ## Output Contract\n"
				"6) ## Minimal TODOs (3-6 bullets)\n\n"
				"Requirement analysis markdown:\n"
				f"{requirement_text}\n\n"
				"Target node context:\n"
				f"{node_context}\n"
			)

			written = self.code_to_file(
				user_prompt,
				str(node_file),
				overwrite=overwrite,
				temperature=temperature,
				max_tokens=max_tokens,
			)
			output_paths.append(written)

		return output_paths
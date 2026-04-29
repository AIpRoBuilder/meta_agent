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
class GraphPlanner(Coder):
	"""Generate a JSON graph plan from a requirements analysis markdown.

	Nodes in the plan should be objects with keys: `name`, `type`, `desc`,
	`depends`, `ext_data`, and optional `services`.

	`ext_data` should be a JSON object for every node with shape:
	{
		"type": "user_input" | "user_file_input" | "image" | "chat_input" | "url" | "file" | "db" | "skill" | "service" | "none" | ...,
		"desc": "short description",
		"service_name": "optional service directory name (required when type=service)",
		"skill_name": "optional skill directory name (required when type=skill)"
	}

	If a node uses one or more upstream services, it should include:
	"services": [
		{"service_name": "...", "use_desc": "..."}
	]

	Use `{"type": "user_input", ...}` for nodes that require user input.
	Use `{"type": "chat_input", ...}` for nodes that should be implemented as WorkflowChatNode.
	Use `{"type": "user_file_input", ...}` for nodes that should be implemented as WorkflowFileNode.
	Use `{"type": "image", ...}` for nodes that should be implemented as WorkflowImageNode.
	Use `{"type": "service", "service_name": "<service>", ...}` for nodes that should be implemented as WorkflowServiceNode.
	Use `{"type": "skill", "skill_name": "<skill>", ...}` for nodes that should be implemented as WorkflowSkillNode.
	Note: WorkflowImageNode is dependency-driven and does not directly upload files.
	If user image upload is needed, plan a WorkflowFileNode (`ext_data.type="user_file_input"`)
	upstream, and make the image node depend on that file node.
	"""

	prompt_path: str = "architect/prompts/graph_planner_prompt.md"
	workflow_nodes_reference_path: str = "library/workflow_nodes_reference_excerpts.md"
	default_services_dirname: str = "agent_services"
	default_skills_dirname: str = "skills"
	NONE_EXT_DESC: str = "no need for ext data"
	SERVICE_EXT_DESC: str = "service bootstrap node"
	SKILL_EXT_DESC: str = "skill node"

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
			"When selecting workflow node structure, node kind and required capabilities,\n"
			"strictly follow the following node types/functions reference.\n\n"
			f"{nodes_reference}\n"
		)
		super().__post_init__()

	def _default_services_root(self) -> Path:
		root_dir = ROOT_DIR.parent
		direct = root_dir / self.default_services_dirname
		if direct.is_dir():
			return direct
		parent = root_dir.parent / self.default_services_dirname
		if parent.is_dir():
			return parent
		return direct

	def _list_available_services(self) -> list[str]:
		services_root = self._default_services_root()
		if not services_root.is_dir():
			return []
		return sorted(child.name for child in services_root.iterdir() if child.is_dir())

	def _read_service_markdown(self, services_root: Path, service_name: str) -> str:
		if not service_name:
			return ""
		service_doc = services_root / service_name / "service.md"
		if not service_doc.is_file():
			return ""
		return service_doc.read_text(encoding="utf-8").strip()

	def _extract_service_description(self, service_markdown: str) -> str:
		if not service_markdown.strip():
			return ""

		lines = service_markdown.splitlines()
		description_lines: list[str] = []
		collecting = False
		in_code_block = False

		for raw_line in lines:
			line = raw_line.strip()
			if line.startswith("```"):
				in_code_block = not in_code_block
				continue
			if in_code_block:
				continue

			if line.startswith("#"):
				heading_text = line.lstrip("#").strip().lower()
				if heading_text in {"description", "desc", "简介", "说明"}:
					collecting = True
					description_lines.clear()
					continue
				if collecting:
					break

			if collecting:
				if line:
					description_lines.append(line)
				continue

		if description_lines:
			return " ".join(description_lines).strip()

		for raw_line in lines:
			line = raw_line.strip()
			if not line or line.startswith("#") or line.startswith("```"):
				continue
			return line

		return ""

	def _service_descriptions(self, services_root: Path, available_services: list[str]) -> dict[str, str]:
		descriptions: dict[str, str] = {}
		for service_name in available_services:
			service_markdown = self._read_service_markdown(services_root, service_name)
			description = self._extract_service_description(service_markdown)
			if description:
				descriptions[service_name] = description
		return descriptions

	def _normalize_service_key(self, value: str) -> str:
		clean = value.strip().lower()
		for sep in ("_", "-", " "):
			clean = clean.replace(sep, "")
		return clean

	def _resolve_service_name(self, node: dict[str, Any], available_services: list[str]) -> str:
		if not available_services:
			return ""

		ext_data = node.get("ext_data", {})
		service_name = ""
		if isinstance(ext_data, dict):
			service_name = str(ext_data.get("service_name", "")).strip()

		by_key = {self._normalize_service_key(name): name for name in available_services}

		if service_name:
			matched = by_key.get(self._normalize_service_key(service_name))
			if matched:
				return matched

		search_texts: list[str] = []
		for key in ("name", "type", "desc"):
			val = node.get(key, "")
			if isinstance(val, str) and val.strip():
				search_texts.append(val)
		if isinstance(ext_data, dict):
			ext_desc = ext_data.get("desc", "")
			if isinstance(ext_desc, str) and ext_desc.strip():
				search_texts.append(ext_desc)

		for text in search_texts:
			norm_text = self._normalize_service_key(text)
			for key, canonical in by_key.items():
				if key and key in norm_text:
					return canonical

		if len(available_services) == 1:
			return available_services[0]

		return ""

	# ------------------------------------------------------------------
	# Skill helpers (mirrors service helpers)
	# ------------------------------------------------------------------

	def _default_skills_root(self) -> Path:
		root_dir = ROOT_DIR.parent
		direct = root_dir / self.default_skills_dirname
		if direct.is_dir():
			return direct
		# also look one level up
		parent = root_dir.parent / self.default_skills_dirname
		if parent.is_dir():
			return parent
		# fall back to sibling of the meta_agent package root
		pkg_sibling = ROOT_DIR.parent / self.default_skills_dirname
		if pkg_sibling.is_dir():
			return pkg_sibling
		return direct

	def _list_available_skills(self) -> list[str]:
		skills_root = self._default_skills_root()
		if not skills_root.is_dir():
			return []
		return sorted(
			child.name
			for child in skills_root.iterdir()
			if child.is_dir() and (child / "skill.md").is_file()
		)

	def _read_skill_markdown(self, skills_root: Path, skill_name: str) -> str:
		if not skill_name:
			return ""
		skill_doc = skills_root / skill_name / "skill.md"
		if not skill_doc.is_file():
			return ""
		return skill_doc.read_text(encoding="utf-8").strip()

	def _extract_skill_description(self, skill_markdown: str) -> str:
		"""Return the text under the ## Description section of a skill.md."""
		if not skill_markdown.strip():
			return ""
		from meta_agent.tools.file_tools import parse_skill_md
		sections = parse_skill_md(skill_markdown)
		desc = sections.get("Description", "").strip()
		if desc:
			return " ".join(desc.splitlines()).strip()
		# fall back to first non-empty, non-heading line
		for line in skill_markdown.splitlines():
			stripped = line.strip()
			if stripped and not stripped.startswith("#") and not stripped.startswith("`"):
				return stripped
		return ""

	def _skill_descriptions(self, skills_root: Path, available_skills: list[str]) -> dict[str, str]:
		descriptions: dict[str, str] = {}
		for skill_name in available_skills:
			skill_markdown = self._read_skill_markdown(skills_root, skill_name)
			description = self._extract_skill_description(skill_markdown)
			if description:
				descriptions[skill_name] = description
		return descriptions

	def _normalize_skill_key(self, value: str) -> str:
		clean = value.strip().lower()
		for sep in ("_", "-", " "):
			clean = clean.replace(sep, "")
		return clean

	def _resolve_skill_name(self, node: dict[str, Any], available_skills: list[str]) -> str:
		if not available_skills:
			return ""

		ext_data = node.get("ext_data", {})
		skill_name = ""
		if isinstance(ext_data, dict):
			skill_name = str(ext_data.get("skill_name", "")).strip()

		by_key = {self._normalize_skill_key(name): name for name in available_skills}

		if skill_name:
			matched = by_key.get(self._normalize_skill_key(skill_name))
			if matched:
				return matched

		search_texts: list[str] = []
		for key in ("name", "type", "desc"):
			val = node.get(key, "")
			if isinstance(val, str) and val.strip():
				search_texts.append(val)
		if isinstance(ext_data, dict):
			ext_desc = ext_data.get("desc", "")
			if isinstance(ext_desc, str) and ext_desc.strip():
				search_texts.append(ext_desc)

		for text in search_texts:
			norm_text = self._normalize_skill_key(text)
			for key, canonical in by_key.items():
				if key and key in norm_text:
					return canonical

		if len(available_skills) == 1:
			return available_skills[0]

		return ""

	def _skill_bootstrap_desc(self, skill_name: str, skill_descriptions: dict[str, str]) -> str:
		description = skill_descriptions.get(skill_name, "").strip()
		if not description:
			return self.SKILL_EXT_DESC
		return f"skill node: {description}"

	def _build_skill_context_prompt(self) -> str:
		skills_root = self._default_skills_root()
		available_skills = self._list_available_skills()
		skill_descriptions = self._skill_descriptions(skills_root, available_skills)
		skills_text = ", ".join(available_skills) if available_skills else "none"
		skill_lines = [
			"Skill planning context:\n"
			f"- default_skills_root: {skills_root}\n"
			f"- available_skills_name: {skills_text}\n"
			"- If choosing WorkflowSkillNode semantics, set ext_data.type='skill' and ext_data.skill_name to one exact available_skills_name entry.\n"
		]
		if skill_descriptions:
			skill_lines.append("- skill_descriptions_from_skill_md:\n")
			for skill_name in available_skills:
				description = skill_descriptions.get(skill_name, "")
				if not description:
					continue
				skill_lines.append(f"  - {skill_name}: {description}\n")
			skill_lines.append(
				"- For skill-type nodes, choose skill_name by matching requirement semantics to skill_descriptions_from_skill_md, and reflect that purpose in node desc/ext_data.desc.\n"
			)
		return "".join(skill_lines)

	# ------------------------------------------------------------------
	def _build_service_context_prompt(self) -> str:
		services_root = self._default_services_root()
		available_services = self._list_available_services()
		service_descriptions = self._service_descriptions(services_root, available_services)
		services_text = ", ".join(available_services) if available_services else "none"
		service_lines = [
			"Service planning context:\n"
			f"- default_services_root: {services_root}\n"
			f"- available_services_name: {services_text}\n"
			"- If choosing WorkflowServiceNode semantics, set ext_data.type='service' and ext_data.service_name to one exact available_services_name entry.\n"
		]
		if service_descriptions:
			service_lines.append("- service_descriptions_from_service_md:\n")
			for service_name in available_services:
				description = service_descriptions.get(service_name, "")
				if not description:
					continue
				service_lines.append(f"  - {service_name}: {description}\n")
			service_lines.append(
				"- For service-type nodes, choose service_name by matching requirement semantics to service_descriptions_from_service_md, and reflect that purpose in node desc/ext_data.desc.\n"
			)
		return "".join(service_lines)

	def _service_bootstrap_desc(self, service_name: str, service_descriptions: dict[str, str]) -> str:
		description = service_descriptions.get(service_name, "").strip()
		if not description:
			return self.SERVICE_EXT_DESC
		return f"service bootstrap node: {description}"

	def _is_service_node(self, node: dict[str, Any]) -> bool:
		ext_data = node.get("ext_data", {})
		if not isinstance(ext_data, dict):
			return False
		ext_type = str(ext_data.get("type", "")).strip().lower()
		service_name = str(ext_data.get("service_name", "")).strip()
		return ext_type == "service" or bool(service_name)

	def _collect_upstream_service_names(
		self,
		node: dict[str, Any],
		node_by_name: dict[str, dict[str, Any]],
		available_services: list[str],
	) -> list[str]:
		depends = node.get("depends", [])
		if isinstance(depends, (str, bytes)):
			depends = [depends]
		if not isinstance(depends, list):
			return []

		stack: list[str] = [str(dep).strip() for dep in depends if str(dep).strip()]
		visited: set[str] = set()
		service_names: set[str] = set()

		while stack:
			current = stack.pop()
			if current in visited:
				continue
			visited.add(current)

			upstream = node_by_name.get(current)
			if not isinstance(upstream, dict):
				continue

			if self._is_service_node(upstream):
				resolved = self._resolve_service_name(upstream, available_services)
				if resolved:
					service_names.add(resolved)
				else:
					ext_data = upstream.get("ext_data", {})
					if isinstance(ext_data, dict):
						raw_name = str(ext_data.get("service_name", "")).strip()
						if raw_name:
							service_names.add(raw_name)

			upstream_depends = upstream.get("depends", [])
			if isinstance(upstream_depends, (str, bytes)):
				upstream_depends = [upstream_depends]
			if not isinstance(upstream_depends, list):
				continue
			for dep in upstream_depends:
				dep_name = str(dep).strip()
				if dep_name and dep_name not in visited:
					stack.append(dep_name)

		return sorted(service_names)

	def _default_service_use_desc(
		self,
		node: dict[str, Any],
		service_name: str,
	) -> str:
		node_desc = str(node.get("desc", "")).strip()
		ext_data = node.get("ext_data", {})
		ext_desc = ""
		if isinstance(ext_data, dict):
			ext_desc = str(ext_data.get("desc", "")).strip()

		target_desc = node_desc or ext_desc
		if target_desc:
			return f"use service '{service_name}' to support: {target_desc}"
		return f"use service '{service_name}' in this node"

	def _normalize_services_field(
		self,
		payload: dict[str, Any],
		available_services: list[str],
	) -> None:
		nodes = payload.get("nodes", [])
		if not isinstance(nodes, list):
			return

		node_by_name: dict[str, dict[str, Any]] = {}
		for node in nodes:
			if not isinstance(node, dict):
				continue
			name = str(node.get("name", "")).strip()
			if name:
				node_by_name[name] = node

		for node in nodes:
			if not isinstance(node, dict):
				continue

			if self._is_service_node(node):
				node.pop("services", None)
				continue

			upstream_service_names = self._collect_upstream_service_names(
				node,
				node_by_name,
				available_services,
			)

			existing_services = node.get("services")
			normalized: dict[str, str] = {}
			if isinstance(existing_services, list):
				for item in existing_services:
					if not isinstance(item, dict):
						continue
					service_name = str(item.get("service_name", "")).strip()
					use_desc = str(item.get("use_desc", "")).strip()
					if not service_name:
						continue
					resolved = service_name
					if available_services:
						matched = self._resolve_service_name(
							{"name": "", "type": "", "desc": "", "ext_data": {"service_name": service_name}},
							available_services,
						)
						if matched:
							resolved = matched
					normalized[resolved] = use_desc

			for service_name in upstream_service_names:
				normalized.setdefault(service_name, "")

			if not normalized:
				node.pop("services", None)
				continue

			node["services"] = [
				{
					"service_name": service_name,
					"use_desc": use_desc or self._default_service_use_desc(node, service_name),
				}
				for service_name, use_desc in sorted(normalized.items())
			]

	def _normalize_ext_data_in_file(self, graph_json_path: Path) -> None:
		# Normalize ext_data shape and enforce type=none description rules.

		payload = json.loads(graph_json_path.read_text(encoding="utf-8"))
		nodes = payload.get("nodes", [])
		if not isinstance(nodes, list):
			return

		available_services = self._list_available_services()
		services_root = self._default_services_root()
		service_descriptions = self._service_descriptions(services_root, available_services)

		available_skills = self._list_available_skills()
		skills_root = self._default_skills_root()
		skill_descriptions = self._skill_descriptions(skills_root, available_skills)

		for node in nodes:
			if not isinstance(node, dict):
				continue

			loop_value = node.get("loop", 1)
			try:
				loop_int = int(loop_value)
			except (TypeError, ValueError):
				loop_int = 1
			node["loop"] = max(1, loop_int)

			ext_data = node.get("ext_data")
			if not isinstance(ext_data, dict):
				node["ext_data"] = {"type": "none", "desc": self.NONE_EXT_DESC}
				continue

			ext_type = str(ext_data.get("type", "")).strip().lower()
			if not ext_type:
				ext_type = "none"
			ext_data["type"] = ext_type

			# ---- skill node normalisation ----
			skill_name = str(ext_data.get("skill_name", "")).strip()
			if ext_type == "skill" or skill_name:
				ext_data["type"] = "skill"
				resolved_skill = self._resolve_skill_name(node, available_skills)
				ext_data["skill_name"] = resolved_skill
				desc = str(ext_data.get("desc", "")).strip()
				ext_data["desc"] = desc or self._skill_bootstrap_desc(
					resolved_skill,
					skill_descriptions,
				)
				continue

			# ---- service node normalisation ----
			service_name = str(ext_data.get("service_name", "")).strip()
			if ext_type == "service" or service_name:
				ext_data["type"] = "service"
				resolved_service = self._resolve_service_name(node, available_services)
				ext_data["service_name"] = resolved_service
				desc = str(ext_data.get("desc", "")).strip()
				ext_data["desc"] = desc or self._service_bootstrap_desc(
					resolved_service,
					service_descriptions,
				)
				continue

			if ext_type == "none":
				ext_data["desc"] = self.NONE_EXT_DESC
			else:
				desc = str(ext_data.get("desc", "")).strip()
				ext_data["desc"] = desc
			if "service_name" in ext_data and ext_data["service_name"] is None:
				ext_data["service_name"] = ""
			if "skill_name" in ext_data and ext_data["skill_name"] is None:
				ext_data["skill_name"] = ""

		self._normalize_services_field(payload, available_services)

		graph_json_path.write_text(
			json.dumps(payload, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)

	def _safe_mermaid_id(self, node_name: str, used_ids: set[str]) -> str:
		base_chars: list[str] = []
		for ch in str(node_name):
			if ch.isalnum() or ch == "_":
				base_chars.append(ch)
			else:
				base_chars.append("_")
		base = "".join(base_chars).strip("_")
		if not base:
			base = "node"
		if not (base[0].isalpha() or base[0] == "_"):
			base = f"n_{base}"

		candidate = base
		suffix = 2
		while candidate in used_ids:
			candidate = f"{base}_{suffix}"
			suffix += 1
		used_ids.add(candidate)
		return candidate

	def _to_mermaid_text(self, graph_json_path: Path) -> str:
		payload = json.loads(graph_json_path.read_text(encoding="utf-8"))
		nodes = payload.get("nodes", [])
		if not isinstance(nodes, list):
			nodes = []

		used_ids: set[str] = set()
		name_to_id: dict[str, str] = {}
		for node in nodes:
			if not isinstance(node, dict):
				continue
			name = str(node.get("name", "")).strip()
			if not name or name in name_to_id:
				continue
			name_to_id[name] = self._safe_mermaid_id(name, used_ids)

		lines: list[str] = ["flowchart TD"]
		for node in nodes:
			if not isinstance(node, dict):
				continue
			name = str(node.get("name", "")).strip()
			if not name or name not in name_to_id:
				continue
			node_id = name_to_id[name]
			label = name.replace('"', "\\\"")
			lines.append(f'    {node_id}["{label}"]')

		edges_seen: set[tuple[str, str]] = set()
		for node in nodes:
			if not isinstance(node, dict):
				continue
			name = str(node.get("name", "")).strip()
			if not name or name not in name_to_id:
				continue
			target_id = name_to_id[name]
			depends = node.get("depends", [])
			if isinstance(depends, (str, bytes)):
				depends = [depends]
			if not isinstance(depends, list):
				continue
			for dep in depends:
				dep_name = str(dep).strip()
				if not dep_name:
					continue
				dep_id = name_to_id.get(dep_name)
				if dep_id is None:
					dep_id = self._safe_mermaid_id(dep_name, used_ids)
					name_to_id[dep_name] = dep_id
					label = dep_name.replace('"', "\\\"")
					lines.append(f'    {dep_id}["{label}"]')
				edge = (dep_id, target_id)
				if edge in edges_seen:
					continue
				edges_seen.add(edge)
				lines.append(f"    {dep_id} --> {target_id}")

		return "\n".join(lines).strip() + "\n"

	def _write_mermaid_from_graph_json(self, graph_json_path: Path) -> Path:
		mmd_path = graph_json_path.with_suffix(".mmd")
		mmd_text = self._to_mermaid_text(graph_json_path)
		mmd_path.write_text(mmd_text, encoding="utf-8")
		return mmd_path

	def plan_from_file(
		self,
		requirement_md_path: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = 20000,
	) -> Path:
		"""Read requirement_analysis.md and write a JSON graph plan."""

		requirement_path = Path(requirement_md_path)
		if not requirement_path.exists():
			raise FileNotFoundError(f"Requirement file not found: {requirement_path}")

		requirement_text = requirement_path.read_text(encoding="utf-8")
		return self.plan(
			requirement_text,
			output_path,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def plan(
		self,
		requirement_text: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.05,
		max_tokens: int = 20000,
	) -> Path:
		"""Call the LLM and persist the graph plan as JSON."""

		target_path = Path(output_path)
		if target_path.suffix.lower() != ".json":
			target_path = target_path.with_suffix(".json")

		user_prompt = (
			"Generate graph_plan.json from the requirement text below.\n"
			"Node-type/function selection rules:\n"
			"- Use WorkflowStepNode-compatible semantics for nodes with ext_data.type='user_input'\n"
			"- Use WorkflowOperationNode-compatible semantics for pure compute/process nodes with ext_data.type='none'\n"
			"- Use WorkflowChatNode-compatible semantics for conversational assistant nodes with ext_data.type='chat_input'\n"
			"- Use WorkflowFileNode-compatible semantics for generic multi-file upload/storage nodes with ext_data.type='user_file_input'\n"
			"- Use WorkflowImageNode-compatible semantics for dependency-driven vision/image analysis nodes with ext_data.type='image'\n"
			"- Use WorkflowServiceNode-compatible semantics for service bootstrap/startup nodes with ext_data.type='service'\n"
			"- Use WorkflowSkillNode-compatible semantics for nodes that wrap a pre-built skill library with ext_data.type='skill'\n"
			"- WorkflowImageNode has no direct upload handler: if user-uploaded images are needed, create an upstream user_file_input node and set the image node depends on it\n"
			"- Do not invent node categories outside Step/Operation/Chat/File/Image/Service/Skill capabilities defined in the workflow reference\n"
			"Schema requirements for each node:\n"
			"- Required fields: name, type, desc, enable, depends, ext_data\n"
			"- For any node that depends directly or transitively on a service node (ext_data.type='service'), include node.services as a list of objects: [{'service_name':'<service>','use_desc':'<how this node uses the service>'}] could be empty if no services are used\n"
			"- service nodes themselves should not include services\n"
			"- Use node-level loop to represent repeated execution; default loop=1\n"
			"- If a node must execute multiple times to update node state, set loop to an integer > 1 (example: UserInput loop=2)\n"
			"- ext_data must be a JSON object with keys: type, desc (and service_name when type='service', skill_name when type='skill')\n"
			"- Mark text input nodes with ext_data.type = 'user_input'\n"
			"- Mark conversational/chat assistant nodes with ext_data.type = 'chat_input'\n"
			"- Mark generic file-upload nodes that require user files with ext_data.type = 'user_file_input'\n"
			"- Mark dependency-driven vision/image analysis nodes with ext_data.type = 'image'\n"
			"- Mark service bootstrap/startup nodes with ext_data.type = 'service'\n"
			"- Mark skill-library wrapper nodes with ext_data.type = 'skill'\n"
			"- For user image upload, use a separate user_file_input node and depend on it from the image node\n"
			"- Workflow mapping: user_input -> WorkflowStepNode, chat_input -> WorkflowChatNode, user_file_input -> WorkflowFileNode, image -> WorkflowImageNode, service -> WorkflowServiceNode, skill -> WorkflowSkillNode\n"
			"- If ext_data.type='service', ext_data.service_name must be set to a valid service directory name\n"
			"- If ext_data.type='skill', ext_data.skill_name must be set to a valid skill directory name\n"
			"- Examples: {'type':'user_input','desc':'user input income'}, {'type':'chat_input','desc':'chat with assistant using previous step outputs'}, {'type':'user_file_input','desc':'upload files for storage and downstream processing'}, {'type':'image','desc':'analyze images from dependency file node outputs'}, {'type':'service','service_name':'media_crawler','desc':'bootstrap and verify media crawler service'}, {'type':'skill','skill_name':'baidu_search','desc':'search baidu for query results'}, {'type':'url','desc':'image generator api'}\n"
			"- For nodes without external dependency, include ext_data as {'type':'none','desc':'no need for ext data'}\n"
			"- If ext_data.type is 'none', desc must be exactly 'no need for ext data'\n"
			"- Example for iterative state update node: {'name':'UserInput','type':'UserInput','desc':'接收用户输入的目标用户画像与教学大纲文本','loop':2,'ext_data':{'type':'user_input','desc':'输入目标用户画像和教学大纲文本'},'enable':true}\n"
			f"{self._build_service_context_prompt()}"
			f"{self._build_skill_context_prompt()}"
			"Return only valid JSON.\n\n"
			"Requirement text:\n"
			f"{requirement_text}"
		)

		result_path = self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)
		graph_path = Path(result_path)
		self._normalize_ext_data_in_file(graph_path)
		return result_path

	def amend_file_with_feedback(
		self,
		graph_json_path: str,
		amendment: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.05,
		max_tokens: int = 20000,
	) -> Path:
		"""Amend an existing graph JSON plan using feedback."""

		target_path = Path(graph_json_path)
		if target_path.suffix.lower() != ".json":
			target_path = target_path.with_suffix(".json")

		if not target_path.exists():
			raise FileNotFoundError(f"Graph JSON file not found: {target_path}")

		current_plan = target_path.read_text(encoding="utf-8")

		user_prompt = (
			"Update the existing graph plan JSON using the amendment provided.\n"
			"Node-type/function selection rules:\n"
			"- Use WorkflowStepNode-compatible semantics for nodes with ext_data.type='user_input'\n"
			"- Use WorkflowOperationNode-compatible semantics for pure compute/process nodes with ext_data.type='none'\n"
			"- Use WorkflowChatNode-compatible semantics for conversational assistant nodes with ext_data.type='chat_input'\n"
			"- Use WorkflowFileNode-compatible semantics for generic multi-file upload/storage nodes with ext_data.type='user_file_input'\n"
			"- Use WorkflowImageNode-compatible semantics for dependency-driven vision/image analysis nodes with ext_data.type='image'\n"
			"- Use WorkflowServiceNode-compatible semantics for service bootstrap/startup nodes with ext_data.type='service'.\n"
			"- Use WorkflowSkillNode-compatible semantics for nodes that wrap a pre-built skill library with ext_data.type='skill'.\n"
			"- WorkflowImageNode has no direct upload handler: if user-uploaded images are needed, create an upstream user_file_input node and set the image node depends on it\n"
			"- Do not invent node categories outside Step/Operation/Chat/File/Image/Service/Skill capabilities defined in the workflow reference\n"
			"Preserve the graph schema (top-level nodes list with name, type, desc, depends, ext_data).\n"
			"For any node that depends directly or transitively on a service node (ext_data.type='service'), include node.services as a list of objects: [{'service_name':'<service>','use_desc':'<how this node uses the service>'}] could be empty if no services are used.\n"
			"Service nodes themselves should not include services.\n"
			"Use node-level loop to represent repeated execution; default loop=1.\n"
			"If a node must execute multiple times to update node state, set loop to an integer > 1 (example: UserInput loop=2).\n"
			"Every node must include ext_data as a JSON object with keys: type, desc (plus service_name when type='service', skill_name when type='skill').\n"
			"Mark text input nodes with ext_data.type='user_input'.\n"
			"Mark conversational/chat assistant nodes with ext_data.type='chat_input'.\n"
			"Mark generic file-upload nodes that require user files with ext_data.type='user_file_input'.\n"
			"Mark dependency-driven vision/image analysis nodes with ext_data.type='image'.\n"
			"Mark service bootstrap/startup nodes with ext_data.type='service'.\n"
			"Mark skill-library wrapper nodes with ext_data.type='skill'.\n"
			"If ext_data.type='service', ext_data.service_name must be set to a valid service directory name.\n"
			"If ext_data.type='skill', ext_data.skill_name must be set to a valid skill directory name.\n"
			"For user image upload, use a separate user_file_input node and depend on it from the image node.\n"
			"Workflow mapping: user_input -> WorkflowStepNode, chat_input -> WorkflowChatNode, user_file_input -> WorkflowFileNode, image -> WorkflowImageNode, service -> WorkflowServiceNode, skill -> WorkflowSkillNode.\n"
			"If ext_data.type is 'none', desc must be exactly 'no need for ext data'.\n"
			"Example for iterative state update node: {'name':'UserInput','type':'UserInput','desc':'接收用户输入的目标用户画像与教学大纲文本','loop':2,'ext_data':{'type':'user_input','desc':'输入目标用户画像和教学大纲文本'},'enable':true}.\n"
			"Examples: {'type':'user_input','desc':'user input income'}, {'type':'chat_input','desc':'chat with assistant using previous step outputs'}, {'type':'user_file_input','desc':'upload files for storage and downstream processing'}, {'type':'image','desc':'analyze images from dependency file node outputs'}, {'type':'service','service_name':'media_crawler','desc':'bootstrap and verify media crawler service'}, {'type':'skill','skill_name':'baidu_search','desc':'search baidu for query results'}, {'type':'url','desc':'image generator api'}.\n"
			f"{self._build_service_context_prompt()}"
			f"{self._build_skill_context_prompt()}"
			"Return only valid JSON without code fences or commentary.\n\n"
			"Existing graph plan:\n"
			f"{current_plan}\n\n"
			"Amendment / feedback to apply:\n"
			f"{amendment}\n"
		)

		result_path = self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)
		graph_path = Path(result_path)
		self._normalize_ext_data_in_file(graph_path)
		return result_path

"""Generate per-node Vue view and CSS files from graph metadata via an LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from meta_agent._paths import bootstrap_package_root


ROOT_DIR = bootstrap_package_root(__file__)

from meta_agent.llm_client.coder import Coder, MAX_TOKENS
from meta_agent.architect.graph import NodeMeta
from meta_agent.tools.text_tools import truncate_context


@dataclass
class FrontendViewCoder(Coder):
	"""Coder that emits one Vue view and one CSS file per enabled graph node."""

	prompt_path: str = "worker/prompts/pydaograph_frontend_view_prompt.md"
	node_html_context_max_chars: int = 16000
	node_python_context_max_chars: int = 16000
	graph_plan_context_max_chars: int = 12000

	def __post_init__(self) -> None:
		prompt_file = ROOT_DIR / self.prompt_path
		if not prompt_file.exists():
			raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

		self.system_prompt = prompt_file.read_text(encoding="utf-8")
		super().__post_init__()

	@staticmethod
	def _load_graph_plan(graph_plan: str | Mapping[str, Any]) -> dict[str, Any]:
		if isinstance(graph_plan, Mapping):
			return dict(graph_plan)

		graph_plan_path = Path(graph_plan).expanduser()
		if graph_plan_path.exists():
			return json.loads(graph_plan_path.read_text(encoding="utf-8"))

		return json.loads(graph_plan)

	@staticmethod
	def _extract_enabled_nodes(graph_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
		nodes = graph_plan.get("nodes", []) if isinstance(graph_plan, Mapping) else []
		if not isinstance(nodes, list):
			return []

		enabled_nodes: list[dict[str, Any]] = []
		for node in nodes:
			if not isinstance(node, Mapping):
				continue
			if node.get("enable", True) is False:
				continue
			if node.get("show_frontend", True) is False:
				continue

			node_name = str(node.get("name", "")).strip()
			if not node_name:
				continue
			enabled_nodes.append(dict(node))
		return enabled_nodes

	@staticmethod
	def _resolve_context_file(base_dir: Path, node_name: str, suffix: str) -> Path | None:
		direct_path = base_dir / f"{node_name}{suffix}"
		if direct_path.exists():
			return direct_path

		matches = sorted(
			candidate
			for candidate in base_dir.rglob(f"*{suffix}")
			if candidate.is_file() and candidate.stem == node_name
		)
		return matches[0] if matches else None

	def _read_context_file(self, base_dir: Path, node_name: str, suffix: str) -> str:
		path = self._resolve_context_file(base_dir, node_name, suffix)
		if path is None:
			return f"[missing] {node_name}{suffix} not found under: {base_dir}"

		return path.read_text(encoding="utf-8")

	@staticmethod
	def _strip_script_blocks(html_text: str) -> str:
		return re.sub(r"<script\b[^>]*>.*?</script>", "", html_text, flags=re.IGNORECASE | re.DOTALL)

	@staticmethod
	def _strip_style_blocks(html_text: str) -> str:
		return re.sub(r"<style\b[^>]*>.*?</style>", "", html_text, flags=re.IGNORECASE | re.DOTALL)

	def _build_vue_user_prompt(
		self,
		*,
		node_name: str,
		node_meta: NodeMeta,
		graph_plan_context: str,
		node_html_context: str,
		node_python_context: str,
		style_filename: str,
	) -> str:
		node_meta_json = json.dumps(node_meta.to_dict(), ensure_ascii=False, indent=2)
		graph_plan_context = truncate_context(
			graph_plan_context,
			label="graph_plan_context",
			max_chars=self.graph_plan_context_max_chars,
		)
		node_html_context = self._strip_style_blocks(node_html_context)
		node_html_context = truncate_context(
			node_html_context,
			label="node_html_context",
			max_chars=self.node_html_context_max_chars,
		)
		node_python_context = truncate_context(
			node_python_context,
			label="node_python_context",
			max_chars=self.node_python_context_max_chars,
		)

		return (
			f"Generate one Vue single-file component named {node_name}.vue.\n"
			"Return only runnable Vue component code with no markdown fences or explanation.\n"
			"Never use this.$set or Vue.set in node views; use direct assignment or object replacement patterns instead.\n"
			"Follow the reference structure inferred from the sample frontend: template + script + external style tag.\n"
			"Use the node name as the default stepId prop value and keep the component focused on a single workflow step.\n"
			"The component should integrate with an injected workflowStore, expose a busy state, and call workflowStore.submitStep(stepId) from a runCurrentStep method.\n"
			"If current node metadata indicates ext_data.type='user_file_input', build the view so it collects files and submits backend user_input as a JSON string with exact shape {\"files\":[{\"fileName\":\"new_file\",\"bytes\":\"sdsdsk\"}]}; use real uploaded file names and file bytes encoded to a string value instead of the example literals.\n"
			"Never import workflowStore or createWorkflowStore from ../stores/workflowStore or ../store/workflow inside node views; rely on injected workflowStore only.\n"
			"Use <style src=\"../styles/"
			f"{style_filename}\"></style> at the end of the file.\n"
			"Prefer Vue options API to match the reference project.\n"
			"Treat the provided HTML context as the primary source for the <template> block and preserve it as literally as possible.\n"
			"Ignore any <style>...</style> blocks from the source context and derive the template only from the remaining markup.\n"
			"Keep the same tag hierarchy, section ordering, class names, attributes, and visible text unless a change is required to produce valid Vue syntax or wire required workflow behavior.\n"
			"Do not redesign, summarize, or replace the HTML context with a different layout; only make the smallest Vue-specific edits needed for bindings, events, conditionals, loops, and accessibility.\n"
			"If the HTML context already contains suitable form controls or actions, keep them and adapt them instead of inventing new markup.\n"
			"When workflow behavior requires extra controls or status UI, append or minimally wrap the existing HTML instead of rewriting the original structure.\n\n"
			"Graph plan JSON context:\n"
			f"{graph_plan_context}\n\n"
			f"Current node metadata for {node_name}:\n"
			f"{node_meta_json}\n\n"
			f"HTML context from {node_name}.html:\n"
			f"{node_html_context}\n\n"
			f"Python context from {node_name}.py:\n"
			f"{node_python_context}\n"
		)

	def _build_css_user_prompt(
		self,
		*,
		node_name: str,
		node_meta: NodeMeta,
		graph_plan_context: str,
		node_html_context: str,
	) -> str:
		node_meta_json = json.dumps(node_meta.to_dict(), ensure_ascii=False, indent=2)
		graph_plan_context = truncate_context(
			graph_plan_context,
			label="graph_plan_context",
			max_chars=self.graph_plan_context_max_chars,
		)
		node_html_context = self._strip_script_blocks(node_html_context)
		node_html_context = truncate_context(
			node_html_context,
			label="node_html_context",
			max_chars=self.node_html_context_max_chars,
		)

		return (
			f"Generate one CSS stylesheet named {node_name}.css.\n"
			"Return only runnable CSS with no markdown fences or explanation.\n"
			"Use the HTML context as the primary source for selectors, section structure, and visual hierarchy.\n"
			"Preserve the visual style, tone, spacing cues, and component character implied by the HTML context as much as possible.\n"
			"Preserve the HTML context as literally as possible when deriving selectors and section-level styling targets.\n"
			"Ignore any <script>...</script> blocks from the source context and derive styles only from the remaining markup.\n"
			"Keep the same class names, ids, attributes, section ordering, and tag hierarchy assumptions unless a small change is required to produce valid, maintainable CSS.\n"
			"Do not restyle the page into a different aesthetic; keep the original look-and-feel direction unless a minimal adjustment is required for responsive or maintainable CSS.\n"
			"Do not redesign, summarize, or replace the HTML-derived structure with a different selector strategy; make the smallest CSS-specific additions needed to style the provided markup.\n"
			"Scope selectors to the node page so styles stay local to this view.\n"
			"Implement a dedicated step card surface in this node stylesheet that is sized to approximately one-third of the page (target about one-third viewport width and one-third viewport height, e.g. around 33vw x 33vh) while keeping it responsive on smaller screens.\n"
			"Follow the reference frontend style direction: concise, component-scoped rules that extend shared page-shell classes.\n\n"
			"Graph plan JSON context:\n"
			f"{graph_plan_context}\n\n"
			f"Current node metadata for {node_name}:\n"
			f"{node_meta_json}\n\n"
			f"HTML context from {node_name}.html:\n"
			f"{node_html_context}\n"
		)

	def write_node_vue_file(
		self,
		*,
		node_name: str,
		node_meta: NodeMeta,
		graph_plan_context: str,
		node_html_context: str,
		node_python_context: str,
		output_path: str | Path,
		style_filename: str,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		user_prompt = self._build_vue_user_prompt(
			node_name=node_name,
			node_meta=node_meta,
			graph_plan_context=graph_plan_context,
			node_html_context=node_html_context,
			node_python_context=node_python_context,
			style_filename=style_filename,
		)
		return self.code_to_file(
			user_prompt,
			str(Path(output_path).expanduser()),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def write_node_css_file(
		self,
		*,
		node_name: str,
		node_meta: NodeMeta,
		graph_plan_context: str,
		node_html_context: str,
		output_path: str | Path,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> Path:
		user_prompt = self._build_css_user_prompt(
			node_name=node_name,
			node_meta=node_meta,
			graph_plan_context=graph_plan_context,
			node_html_context=node_html_context,
		)
		return self.code_to_file(
			user_prompt,
			str(Path(output_path).expanduser()),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def write_graph_node_files(
		self,
		*,
		graph_plan: str | Mapping[str, Any],
		context_base_dir: str,
		output_base_dir: str,
		overwrite: bool = True,
		temperature: float = 0.2,
		vue_max_tokens: int = MAX_TOKENS,
		css_max_tokens: int = MAX_TOKENS,
	) -> dict[str, dict[str, Path]]:
		graph_plan_data = self._load_graph_plan(graph_plan)
		nodes = self._extract_enabled_nodes(graph_plan_data)
		if not nodes:
			return {}

		context_dir = Path(context_base_dir).expanduser().resolve()
		output_dir = Path(output_base_dir).expanduser().resolve()
		views_dir = output_dir / "views"
		styles_dir = output_dir / "styles"
		views_dir.mkdir(parents=True, exist_ok=True)
		styles_dir.mkdir(parents=True, exist_ok=True)

		graph_plan_context = json.dumps(graph_plan_data, ensure_ascii=False, indent=2)
		written_files: dict[str, dict[str, Path]] = {}

		for node in nodes:
			node_meta = NodeMeta.from_dict(node)
			node_name = node_meta.name.strip()
			if not node_name:
				continue

			node_html_context = self._read_context_file(context_dir, node_name, ".html")
			node_python_context = self._read_context_file(context_dir, node_name, ".py")
			style_filename = f"{node_name}.css"
			view_path = views_dir / f"{node_name}.vue"
			style_path = styles_dir / style_filename

			self.write_node_vue_file(
				node_name=node_name,
				node_meta=node_meta,
				graph_plan_context=graph_plan_context,
				node_html_context=node_html_context,
				node_python_context=node_python_context,
				output_path=view_path,
				style_filename=style_filename,
				overwrite=overwrite,
				temperature=temperature,
				max_tokens=vue_max_tokens,
			)
			self.write_node_css_file(
				node_name=node_name,
				node_meta=node_meta,
				graph_plan_context=graph_plan_context,
				node_html_context=node_html_context,
				output_path=style_path,
				overwrite=overwrite,
				temperature=temperature,
				max_tokens=css_max_tokens,
			)
			written_files[node_name] = {
				"view": view_path,
				"style": style_path,
			}

		return written_files

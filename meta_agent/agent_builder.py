from typing import Optional, List, Dict, Any, Mapping
import os
import shutil
import subprocess
import json
from datetime import datetime
from pathlib import Path

from pydaograph import CStatus, GElement, GPipeline

from meta_agent.architect import GraphPlanner, NodePlanner, Graph
from meta_agent.auditor import GraphJsonAuditor, NodeAuditor, MainEntryPointAuditor, OutputAuditor, FrontendAuditor
from meta_agent.llm_client.coder import MAX_TOKENS
from meta_agent.worker.main_writer import PromptMainFileCoder
from meta_agent.worker.node_writer import (
    PromptNodeFileCoderBase,
    WorkflowOperationNodeCoder,
    WorkflowServiceNodeCoder,
    WorkflowSkillNodeCoder,
    WorkflowFileNodeCoder,
    WorkflowStepNodeCoder,
    is_none_ext_data,
    is_service_ext_data,
    is_skill_ext_data,
    is_file_ext_data,
)
from meta_agent.worker.frontend_view_writer import FrontendViewCoder
from meta_agent.worker.frontend_writer import PromptFrontendCoder
from meta_agent.demand_analyzer import RequirementDisector
from meta_agent.tools.agent_builder_tools import (
    build_frontend_node_paths,
    build_frontend_src_file_map,
    create_minimal_vue_frontend_scaffold,
    get_language_extension,
    get_reference_frontend_src_dir,
    select_python_command,
)
from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema

class _NodeGenerateElement(GElement):
    def __init__(self, builder: "AgentBuilder", node_name: str,total: int, node_index: int, language: str, temperature: float) -> None:
        super().__init__()
        self.builder = builder
        self.node_name = node_name
        self.node_index = node_index
        self.node_meta = self.builder.planned_graph.get_node_meta(self.node_name)
        self.coder = self.builder._make_node_coder(self.node_meta)
        self.total = total
        self.temperature = temperature
        self.language = language

    def run(self) -> CStatus:
        try:
            out_dir = os.path.join(self.builder.root_dir, self.node_name)
            print(f"[{self.node_index}/{self.total}] Generating node '{self.node_name}' -> {out_dir}.py")

            # create a node-specific coder for this metadata type
            file_path = self.coder.write_node_from_requirement(
                self.node_name,
                self.node_meta,
                self.builder.requirement_md_path,
                out_dir,
                graph_plan_path=self.builder.graph_plan_path,
                language=self.language,
                temperature=self.temperature,
            )

            # audit/amend loop remains the same
            while True:
                ok, violations = self.builder.node_auditor.audit_node_file(
                    file_path,
                    self.node_meta,
                    graph_plan_path=self.builder.graph_plan_path,
                )
                if ok:
                    print(f"[{self.node_index}/{self.total}] Node audit passed: {self.node_name}")
                    break
                amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
                print(f"[{self.node_index}/{self.total}] Node audit failed: {self.node_name}. {amendment} Applying amendment...")
                self.coder.amend_code_with_feedback(
                    out_dir,
                    amendment,
                    graph_plan_path=self.builder.graph_plan_path or "",
                    requirement_md_path=self.builder.requirement_md_path or "",
                    current_node_name=self.node_name,
                    language=self.language,
                    temperature=self.temperature,
                )

            self.builder.node_coder_map[self.node_name] = self.coder
            self.builder.node_location_map[self.node_name] = file_path

            return CStatus()
        except Exception as exc:
            print(f"[{self.node_index}/{self.total}] Node generation failed for {self.node_name}: {exc}")
            return CStatus(1001, f"node generation failed for {self.node_name}: {exc}")


class _FrontendViewGenerateElement(GElement):
    def __init__(
        self,
        builder: "AgentBuilder",
        node_name: str,
        total: int,
        node_index: int,
        output_base_dir: str,
        context_base_dir: str,
        graph_plan_context: str,
        temperature: float,
        overwrite_existing: bool = True,
        generated_outputs: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        super().__init__()
        self.builder = builder
        self.node_name = node_name
        self.total = total
        self.node_index = node_index
        self.output_base_dir = Path(output_base_dir)
        self.context_base_dir = Path(context_base_dir)
        self.graph_plan_context = graph_plan_context
        self.temperature = temperature
        self.overwrite_existing = overwrite_existing
        self.generated_outputs = generated_outputs if generated_outputs is not None else {}
        self.node_meta = self.builder.planned_graph.get_node_meta(self.node_name)
        self.coder = self.builder._make_frontend_view_writer(self.node_meta)

    def run(self) -> CStatus:
        try:
            if self.node_meta is None:
                raise ValueError(f"node metadata not found for {self.node_name}")

            style_filename = f"{self.node_name}.css"
            view_path = self.output_base_dir / "views" / f"{self.node_name}.vue"
            style_path = self.output_base_dir / "styles" / style_filename
            print(f"[{self.node_index}/{self.total}] Generating frontend view '{self.node_name}' -> {view_path}")

            node_html_context = self.coder._read_context_file(
                self.context_base_dir,
                self.node_name,
                ".html",
            )
            node_python_context = self.coder._read_context_file(
                self.context_base_dir,
                self.node_name,
                ".py",
            )

            node_generated: Dict[str, str] = {}
            if self.overwrite_existing or not view_path.exists():
                self.coder.write_node_vue_file(
                    node_name=self.node_name,
                    node_meta=self.node_meta,
                    graph_plan_context=self.graph_plan_context,
                    node_html_context=node_html_context,
                    node_python_context=node_python_context,
                    output_path=view_path,
                    style_filename=style_filename,
                    overwrite=True,
                    temperature=self.temperature,
                )
                node_generated["view"] = str(view_path)
            if self.overwrite_existing or not style_path.exists():
                self.coder.write_node_css_file(
                    node_name=self.node_name,
                    node_meta=self.node_meta,
                    graph_plan_context=self.graph_plan_context,
                    node_html_context=node_html_context,
                    output_path=style_path,
                    overwrite=True,
                    temperature=self.temperature,
                )
                node_generated["style"] = str(style_path)
            self.builder.frontend_view_output_map[self.node_name] = {
                "view": str(view_path),
                "style": str(style_path),
            }
            if node_generated:
                self.generated_outputs[self.node_name] = node_generated
            return CStatus()
        except Exception as exc:
            return CStatus(1002, f"frontend view generation failed for {self.node_name}: {exc}")
                
class AgentBuilder:
    """Build AG-UI workflow artifacts with generation, auditing, and progress display."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        provider: str = "deepseek",
        root_dir: str = "./example",
        frontend_style_prompt: Optional[str] = None,
        services_root_path: Optional[str] = None,
        skills_root_path: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.root_dir = root_dir
        self.frontend_style_prompt = frontend_style_prompt.strip() if frontend_style_prompt else None
        self.services_root_path = services_root_path.strip() if isinstance(services_root_path, str) else ""
        self.skills_root_path = skills_root_path.strip() if isinstance(skills_root_path, str) else ""
        os.makedirs(self.root_dir, exist_ok=True)

        self._progress_total = 0
        self._progress_current = 0
        self._progress_width = 28
        self.requirement_md_path: Optional[str] = None
        self.requirement_analysis_result: Optional[Dict[str, Any]] = None
        self.graph_plan_path: Optional[str] = None

        self._reset_llm_components()
        # initialize auditors for later validation steps
        self.graph_auditor = GraphJsonAuditor()
        self.node_auditor = NodeAuditor()
        self.main_entry_auditor = MainEntryPointAuditor()
        self.frontend_auditor = FrontendAuditor(base_dir=self.root_dir)
        # output auditor will inspect test logs and help trigger amendments
        self.output_auditor = OutputAuditor()
        self.dynamic_graph_cache: Dict[str, Any] = {
            "graph_nodes": [],
            "graph_plan_path": "",
            "node_plans": {},
            "node_ui": {},
            "backend_nodes": {},
            "frontend_nodes": {},
            "frontend_shared": {},
            "node_input_output_formats": {},
            "server_runtime": {},
        }
        self.backend_server_process: Optional[Any] = None
        self.frontend_server_process: Optional[Any] = None

    def _reset_llm_components(self) -> None:
        self.analyzer = RequirementDisector(api_key=self.api_key, model=self.model, provider=self.provider)
        self.planner = GraphPlanner(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            services_root_path=self.services_root_path,
            skills_root_path=self.skills_root_path,
        )
        self.node_planner = NodePlanner(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            skills_root_path=self.skills_root_path,
        )
        self.main_writer = PromptMainFileCoder(api_key=self.api_key, model=self.model, provider=self.provider)
        self.frontend_writer = PromptFrontendCoder(api_key=self.api_key, model=self.model, provider=self.provider)
        self.frontend_view_writer = FrontendViewCoder(api_key=self.api_key, model=self.model, provider=self.provider)

    def reset_llm_config(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        if api_key is not None:
            self.api_key = api_key
        if model is not None:
            self.model = model
        if provider is not None:
            self.provider = provider
        self._reset_llm_components()

    def _make_node_coder(self, node_meta: Any) -> PromptNodeFileCoderBase:
        ext_data = node_meta.ext_data if node_meta and hasattr(node_meta, 'ext_data') else None
        if is_service_ext_data(ext_data):
            return WorkflowServiceNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
                services_root_path=self.services_root_path,
            )
        if is_skill_ext_data(ext_data):
            return WorkflowSkillNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
                skills_root_path=self.skills_root_path,
            )
        if is_none_ext_data(ext_data):
            return WorkflowOperationNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
            )
        if is_file_ext_data(ext_data):
            return WorkflowFileNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
            )
        return WorkflowStepNodeCoder(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            root_dir_path=self.root_dir,
        )

    def _make_frontend_view_writer(self, node_meta: Any) -> FrontendViewCoder:
        return FrontendViewCoder(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
        )

    def _set_services_root_path(self, services_root: Optional[str]) -> None:
        if services_root is None:
            return
        self.services_root_path = str(services_root).strip()
        self.planner.services_root_path = self.services_root_path

    def _resolve_root_path(self, path_value: str | Path) -> Path:
        resolved_path = Path(path_value).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = Path(self.root_dir).expanduser() / resolved_path
        return resolved_path.resolve()

    def _load_planned_graph(self, graph_plan_path: Optional[str] = None) -> Graph:
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")

        graph_path = Path(self.graph_plan_path).expanduser().resolve()
        planned_graph = getattr(self, "planned_graph", None)
        planned_graph_path: Optional[Path] = None
        if planned_graph is not None and hasattr(planned_graph, "graph_json_path"):
            try:
                planned_graph_path = Path(planned_graph.graph_json_path).resolve()
            except Exception:
                planned_graph_path = None
        if planned_graph is None or planned_graph_path != graph_path:
            self.planned_graph = Graph(str(graph_path))
        return self.planned_graph

    def _read_requirement_text(self, requirement_md_path: Optional[str] = None) -> str:
        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")
        requirement_path = Path(self.requirement_md_path).expanduser().resolve()
        return requirement_path.read_text(encoding="utf-8")

    def _read_graph_plan_payload(self) -> Dict[str, Any]:
        self._load_planned_graph()
        graph_path = Path(self.graph_plan_path).expanduser().resolve()
        return json.loads(graph_path.read_text(encoding="utf-8"))

    def _build_filtered_graph_plan_payload(self, node_names: List[str]) -> Dict[str, Any]:
        graph_payload = self._read_graph_plan_payload()
        requested_names = {name for name in node_names if isinstance(name, str) and name.strip()}
        nodes = graph_payload.get("nodes", []) if isinstance(graph_payload, dict) else []
        if not isinstance(nodes, list):
            raise ValueError("graph_plan JSON must contain a top-level 'nodes' list.")
        graph_payload["nodes"] = [
            node for node in nodes
            if isinstance(node, Mapping) and str(node.get("name", "")).strip() in requested_names
        ]
        return graph_payload

    def _sync_workflow_graph_json(self, context_base_dir: Optional[str] = None) -> str:
        self._load_planned_graph()
        target_dir = self._resolve_root_path(context_base_dir or self.root_dir)
        source_path = Path(self.graph_plan_path).expanduser().resolve()
        workflow_path = target_dir / "workflow.json"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        source_text = source_path.read_text(encoding="utf-8")
        if not workflow_path.exists() or workflow_path.read_text(encoding="utf-8") != source_text:
            workflow_path.write_text(source_text, encoding="utf-8")
        self.workflow_json_path = str(workflow_path)
        return self.workflow_json_path

    def _expected_backend_node_path(self, node_name: str, language: str = "python") -> Path:
        return self._resolve_root_path(Path(f"{node_name}{get_language_extension(language)}"))

    def _collect_current_frontend_node_outputs(self, frontend_src_dir: Path, node_names: List[str]) -> Dict[str, Dict[str, str]]:
        output_map: Dict[str, Dict[str, str]] = {}
        for node_name in node_names:
            expected_paths = build_frontend_node_paths(frontend_src_dir, node_name)
            view_path = expected_paths["view"]
            style_path = expected_paths["style"]
            if view_path.is_file() and style_path.is_file():
                output_map[node_name] = {
                    "view": str(view_path),
                    "style": str(style_path),
                }
        return output_map

    def _generate_selected_nodes(
        self,
        node_names: List[str],
        *,
        language: str = "python",
        temperature: float = 0.35,
        reset_mappings: bool = False,
    ) -> List[str]:
        planned_graph = self._load_planned_graph()
        if reset_mappings or not hasattr(self, "node_coder_map"):
            self.node_coder_map = {}
        if reset_mappings or not hasattr(self, "node_location_map"):
            self.node_location_map = {}

        requested_names = {name for name in node_names if isinstance(name, str) and name.strip()}
        ordered_names = [
            name for name in planned_graph.get_topological_sorted_nodes()
            if name in requested_names
        ]
        missing_names = requested_names.difference(ordered_names)
        if missing_names:
            raise ValueError(f"node(s) not found in graph plan: {sorted(missing_names)}")
        if not ordered_names:
            return []

        total = len(ordered_names)
        pipeline = GPipeline()
        elements: Dict[str, _NodeGenerateElement] = {}
        for index, name in enumerate(ordered_names, start=1):
            elements[name] = _NodeGenerateElement(self, name, total, index, language=language, temperature=temperature)

        for name in ordered_names:
            node_meta = planned_graph.get_node_meta(name)
            depends = set()
            if node_meta and node_meta.depends:
                depends = {elements[dep] for dep in node_meta.depends if dep in elements}
            status = pipeline.registerGElement(elements[name], depends, name, 1)
            if status.isErr():
                raise RuntimeError(f"registerGElement failed for {name}: {status.getInfo()}")

        process_status = pipeline.process()
        if process_status.isErr():
            raise RuntimeError(f"generate_nodes pipeline.process failed: {process_status.getInfo()}")

        return [self.node_location_map[name] for name in ordered_names if name in self.node_location_map]

    def _generate_selected_frontend_views(
        self,
        node_names: List[str],
        *,
        output_base_dir: str = "frontend/src",
        context_base_dir: Optional[str] = None,
        temperature: float = 0.3,
        overwrite_existing: bool = False,
    ) -> Dict[str, Dict[str, str]]:
        planned_graph = self._load_planned_graph()
        requested_names = {name for name in node_names if isinstance(name, str) and name.strip()}
        ordered_names = [
            name for name in planned_graph.get_topological_sorted_nodes()
            if name in requested_names
            and planned_graph.get_node_meta(name) is not None
            and planned_graph.get_node_meta(name).show_frontend
        ]
        if not ordered_names:
            return {}

        resolved_output_dir = self._resolve_root_path(output_base_dir)
        resolved_context_dir = self._resolve_root_path(context_base_dir or self.root_dir)
        (resolved_output_dir / "views").mkdir(parents=True, exist_ok=True)
        (resolved_output_dir / "styles").mkdir(parents=True, exist_ok=True)

        graph_plan_context = Path(self.graph_plan_path).expanduser().resolve().read_text(encoding="utf-8")
        if not hasattr(self, "frontend_view_writer_map"):
            self.frontend_view_writer_map = {}
        if not hasattr(self, "frontend_view_output_map"):
            self.frontend_view_output_map = {}
        self.frontend_views_output_path = str(resolved_output_dir)

        generated_outputs: Dict[str, Dict[str, str]] = {}
        pipeline = GPipeline()
        elements: Dict[str, _FrontendViewGenerateElement] = {}
        total = len(ordered_names)
        for index, node_name in enumerate(ordered_names, start=1):
            element = _FrontendViewGenerateElement(
                self,
                node_name,
                total,
                index,
                output_base_dir=str(resolved_output_dir),
                context_base_dir=str(resolved_context_dir),
                graph_plan_context=graph_plan_context,
                temperature=temperature,
                overwrite_existing=overwrite_existing,
                generated_outputs=generated_outputs,
            )
            elements[node_name] = element
            self.frontend_view_writer_map[node_name] = element.coder

        for node_name in ordered_names:
            node_meta = planned_graph.get_node_meta(node_name)
            depends = set()
            if node_meta and node_meta.depends:
                depends = {elements[dep] for dep in node_meta.depends if dep in elements}
            status = pipeline.registerGElement(elements[node_name], depends, node_name, 1)
            if status.isErr():
                raise RuntimeError(f"registerGElement failed for frontend view {node_name}: {status.getInfo()}")

        process_status = pipeline.process()
        if process_status.isErr():
            raise RuntimeError(f"generate_frontend_views pipeline.process failed: {process_status.getInfo()}")

        return generated_outputs

    def _audit_frontend_src(
        self,
        *,
        frontend_path: str,
        steps_meta: List[Dict[str, Any]],
        context_base_dir: Optional[str],
        reference_frontend_src_dir: str,
        frontend_style_prompt: Optional[str],
        temperature: float,
        max_audit_rounds: int,
    ) -> None:
        last_amendment = ""
        for audit_round in range(1, max_audit_rounds + 1):
            ok, violations = self.frontend_auditor.audit_frontend_file(frontend_path)
            if ok:
                print("frontend audit passed for mode=vue_src.")
                return
            last_amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            if audit_round >= max_audit_rounds:
                raise RuntimeError(
                    "frontend audit did not pass after "
                    f"{max_audit_rounds} attempt(s). Last feedback:\n{last_amendment}"
                )
            grouped_feedback: Dict[Path, List[str]] = {}
            unresolved_feedback: List[str] = []
            for violation in violations:
                target_file = self._resolve_frontend_violation_target(frontend_path, violation)
                message = f"Line {violation.lineno}: {violation.rule} - {violation.detail}"
                if target_file is None or not target_file.is_file():
                    unresolved_feedback.append(message)
                    continue
                grouped_feedback.setdefault(target_file, []).append(message)

            if not grouped_feedback:
                raise RuntimeError(
                    "frontend src audit failed and no amendable target files could be resolved. "
                    f"Last feedback:\n{last_amendment}"
                )

            if unresolved_feedback:
                unresolved_feedback_text = "\n".join(unresolved_feedback)
                raise RuntimeError(
                    "frontend src audit failed and some violations could not be routed to an existing frontend file. "
                    f"Unresolved feedback:\n{unresolved_feedback_text}"
                )

            for target_file, file_feedback in grouped_feedback.items():
                print(f"frontend audit failed. Applying amendment to {target_file} ...")
                self.frontend_writer.amend_code_with_feedback(
                    file_path=str(target_file),
                    rule_violations="\n".join(file_feedback),
                    steps_meta=steps_meta,
                    context_base_dir=context_base_dir,
                    requirement_analysis_result=self.requirement_analysis_result,
                    reference_frontend_src_dir=reference_frontend_src_dir,
                    frontend_style_prompt=frontend_style_prompt,
                    overwrite=True,
                    temperature=temperature,
                )

    def _validate_generated_artifacts(
        self,
        *,
        frontend_project_dir: str | Path,
        graph_plan_path: Optional[str] = None,
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        backend_language: str = "python",
        main_entrypoint_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        planned_graph = self._load_planned_graph(graph_plan_path)
        doc_dir = self._resolve_root_path(getattr(self, "node_docs_dir", node_docs_dirname))
        ui_dir = self._resolve_root_path(getattr(self, "node_html_dir", node_ui_dirname))
        resolved_frontend_dir = self._resolve_root_path(frontend_project_dir)
        frontend_src_dir = resolved_frontend_dir / "src"
        main_path = Path(main_entrypoint_path or getattr(self, "main_output_path", self._resolve_root_path("main.py"))).expanduser()
        if not main_path.is_absolute():
            main_path = self._resolve_root_path(main_path)

        node_names = planned_graph.get_topological_sorted_nodes()
        plan_outputs: Dict[str, str] = {}
        node_ui_outputs: Dict[str, str] = {}
        backend_outputs: Dict[str, str] = {}
        frontend_outputs: Dict[str, Dict[str, str]] = {}
        missing: List[str] = []

        for node_name in node_names:
            node_meta = planned_graph.get_node_meta(node_name)
            doc_path = doc_dir / f"{node_name}.md"
            backend_path = self._expected_backend_node_path(node_name, backend_language)
            if doc_path.is_file():
                plan_outputs[node_name] = str(doc_path)
            else:
                missing.append(str(doc_path))
            if backend_path.is_file():
                backend_outputs[node_name] = str(backend_path)
            else:
                missing.append(str(backend_path))

            if node_meta and node_meta.show_frontend:
                html_path = ui_dir / f"{node_name}.html"
                expected_frontend_paths = build_frontend_node_paths(frontend_src_dir, node_name)
                view_path = expected_frontend_paths["view"]
                style_path = expected_frontend_paths["style"]
                if html_path.is_file():
                    node_ui_outputs[node_name] = str(html_path)
                else:
                    missing.append(str(html_path))
                if view_path.is_file() and style_path.is_file():
                    frontend_outputs[node_name] = {
                        "view": str(view_path),
                        "style": str(style_path),
                    }
                else:
                    if not view_path.is_file():
                        missing.append(str(view_path))
                    if not style_path.is_file():
                        missing.append(str(style_path))

        package_json_path = resolved_frontend_dir / "package.json"
        if not package_json_path.is_file():
            missing.append(str(package_json_path))
        if not main_path.is_file():
            missing.append(str(main_path))

        if missing:
            raise FileNotFoundError(
                "Missing artifacts required for graph refresh/server restart:\n" + "\n".join(sorted(set(missing)))
            )

        return {
            "node_plan": plan_outputs,
            "node_ui": node_ui_outputs,
            "backend_nodes": backend_outputs,
            "frontend_nodes": frontend_outputs,
            "frontend_project_dir": str(resolved_frontend_dir),
            "frontend_src_dir": str(frontend_src_dir),
            "main_entrypoint": str(main_path),
        }

    def _stop_managed_server_process(self, process: Optional[Any]) -> None:
        if process is None:
            return
        try:
            if callable(getattr(process, "poll", None)) and process.poll() is not None:
                return
        except Exception:
            return

        try:
            process.terminate()
            if callable(getattr(process, "wait", None)):
                process.wait(timeout=5)
            return
        except Exception:
            pass

        try:
            process.kill()
            if callable(getattr(process, "wait", None)):
                process.wait(timeout=5)
        except Exception:
            return

    def _start_progress(self, total_steps: int) -> None:
        self._progress_total = max(1, total_steps)
        self._progress_current = 0
        print(f"Pipeline started. Total steps: {self._progress_total}")
        self._print_progress_bar("Initializing")

    def _advance_progress(self, message: str) -> None:
        self._progress_current = min(self._progress_total, self._progress_current + 1)
        self._print_progress_bar(message)

    def _print_progress_bar(self, message: str) -> None:
        ratio = self._progress_current / self._progress_total if self._progress_total else 0
        filled = int(self._progress_width * ratio)
        bar = "#" * filled + "-" * (self._progress_width - filled)
        pct = int(ratio * 100)
        print(f"[{bar}] {self._progress_current}/{self._progress_total} ({pct:3d}%) | {message}")

    def analyze_requirement(self, requirement_text: Optional[str] = None, requirement_file: Optional[str] = None, out_file: str = "requirement_analysis.md") -> str:
        """Produce a requirement analysis markdown file.

        Either `requirement_text` or `requirement_file` should be provided. If `requirement_file`
        is provided it is used as-is (and returned); otherwise `requirement_text` is processed
        by the `RequirementDisector` and written to `out_file` under `root_dir`.
        """
        if requirement_file:
            self.requirement_md_path = requirement_file
            self.requirement_analysis_result = None
            return requirement_file

        out_path = os.path.join(self.root_dir, out_file)
        print(f"Analyzing requirement -> {out_path}")
        result = self.analyzer.analyze(requirement_text or "", out_path)
        self.requirement_md_path = str(result.output_path)
        self.requirement_analysis_result = {
            "output_path": str(result.output_path),
            "is_cron_task": result.is_cron_task,
            "task_type": result.task_type,
            "crontab_expression": result.crontab_expression,
        }
        return self.requirement_md_path

    def plan_graph(
        self,
        requirement_md_path: Optional[str] = None,
        graph_plan_filename: str = "workflow.json",
        temperature: float = 0.35,
        services_root: Optional[str] = None,
    ) -> str:
        self._set_services_root_path(services_root)
        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")

        self.graph_plan_path = os.path.join(self.root_dir, graph_plan_filename)
        print(f"Planning graph -> {self.graph_plan_path}")
        self.planner.plan_from_file(self.requirement_md_path, self.graph_plan_path)

        while True:
            self.planned_graph = Graph(self.graph_plan_path)
            ok, violations = self.graph_auditor.audit_graph_json(self.planned_graph)
            if ok:
                print("Graph plan audit passed.")
                break
            amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            print(f"Graph audit failed. Applying amendment {amendment}...")
            self.planner.amend_file_with_feedback(self.graph_plan_path, amendment, temperature=temperature)
        self.planner._write_mermaid_from_graph_json(Path(self.graph_plan_path))
        return self.graph_plan_path

    def amend_graph(
        self,
        amendment: str,
        graph_plan_path: Optional[str] = None,
        temperature: float = 0.35,
        services_root: Optional[str] = None,
    ) -> str:
        self._set_services_root_path(services_root)
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")
        if not isinstance(amendment, str) or not amendment.strip():
            raise ValueError("amendment must be a non-empty string.")

        while True:
            self.planner.amend_file_with_feedback(
                self.graph_plan_path,
                amendment,
                temperature=temperature,
            )
            self.planned_graph = Graph(self.graph_plan_path)
            ok, violations = self.graph_auditor.audit_graph_json(self.planned_graph)
            if ok:
                print("Graph amendment audit passed.")
                break
            amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            print("Graph amendment audit failed. Applying amendment...")

        self.planner._write_mermaid_from_graph_json(Path(self.graph_plan_path))
        return self.graph_plan_path

    def amend_workflow_json(
        self,
        user_prompt: str,
        workflow_json_path: Optional[str] = None,
        temperature: float = 0.35,
        services_root: Optional[str] = None,
    ) -> str:
        """Amend workflow.json based on a natural-language user prompt.

        This is a convenience wrapper around :meth:`amend_graph` that accepts
        a ``user_prompt`` and targets ``workflow.json`` by default.
        """
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("user_prompt must be a non-empty string.")

        selected_workflow_path = workflow_json_path
        if selected_workflow_path is None:
            selected_workflow_path = self.graph_plan_path
        if selected_workflow_path is None:
            default_workflow_path = self._resolve_root_path("workflow.json")
            if default_workflow_path.is_file():
                selected_workflow_path = str(default_workflow_path)

        if selected_workflow_path is None:
            raise ValueError(
                "workflow_json_path is not set. Call plan_graph(...) first, "
                "set graph_plan_path, or pass workflow_json_path explicitly."
            )

        return self.amend_graph(
            amendment=user_prompt,
            graph_plan_path=selected_workflow_path,
            temperature=temperature,
            services_root=services_root,
        )

    def generate_nodes(
        self,
        graph_plan_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        language: str = "python",
        temperature: float = 0.35,
        services_root: Optional[str] = None,
    ) -> List[str]:
        """Generate code for every node in the planned graph.

        A separate :class:`PromptNodeFileCoder` instance is created for each
        node.  After the file has been written and audited we record the coder
        object and the final file location in two dictionaries on ``self`` so
        that later stages (testing, amendments, etc.) can look them up.

        Returns a list of all generated file paths as before.
        """
        self._set_services_root_path(services_root)
        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")
        planned_graph = self._load_planned_graph(graph_plan_path)
        return self._generate_selected_nodes(
            planned_graph.get_topological_sorted_nodes(),
            language=language,
            temperature=temperature,
            reset_mappings=True,
        )

    def generate_node_markdowns(
        self,
        requirement_md_path: str,
        graph_plan_path: str,
        output_dirname: str = "node_docs",
        temperature: float = 0.2,
    ) -> List[str]:
        """Generate one markdown planning doc per node using NodePlanner."""

        output_dir = os.path.join(self.root_dir, output_dirname)
        print(f"Generating per-node markdown plans -> {output_dir}")
        node_doc_paths = self.node_planner.plan_each_from_files(
            requirement_md_path=requirement_md_path,
            graph_plan_json_path=graph_plan_path,
            output_dir=output_dir,
            overwrite=True,
            temperature=temperature,
        )
        self.node_docs_dir = output_dir
        self.node_doc_paths = [str(path) for path in node_doc_paths]
        return self.node_doc_paths

    def generate_node_html(
        self,
        requirement_md_path: str,
        graph_plan_path: str,
        output_dirname: str = "node_ui",
        temperature: float = 0.3,
    ) -> List[str]:
        """Generate one HTML interaction file per node using NodePlanner."""

        output_dir = os.path.join(self.root_dir, output_dirname)
        print(f"Generating per-node HTML UIs -> {output_dir}")
        node_html_paths = self.node_planner.plan_each_ui_from_files(
            requirement_md_path=requirement_md_path,
            graph_plan_json_path=graph_plan_path,
            output_dir=output_dir,
            overwrite=True,
            temperature=temperature,
        )
        self.node_html_dir = output_dir
        self.node_html_paths = [str(path) for path in node_html_paths]
        return self.node_html_paths

    def update_nodes_plan(
        self,
        graph_plan_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
    ) -> Dict[str, Any]:
        requirement_text = self._read_requirement_text(requirement_md_path)
        planned_graph = self._load_planned_graph(graph_plan_path)
        node_names = planned_graph.get_topological_sorted_nodes()
        visible_node_names = [
            node_name for node_name in node_names
            if planned_graph.get_node_meta(node_name) and planned_graph.get_node_meta(node_name).show_frontend
        ]

        node_docs_dir = self._resolve_root_path(node_docs_dirname)
        node_ui_dir = self._resolve_root_path(node_ui_dirname)
        node_docs_dir.mkdir(parents=True, exist_ok=True)
        node_ui_dir.mkdir(parents=True, exist_ok=True)

        existing_plan_map: Dict[str, str] = {}
        missing_plan_names: List[str] = []
        for node_name in node_names:
            plan_path = node_docs_dir / f"{node_name}.md"
            if plan_path.is_file():
                existing_plan_map[node_name] = str(plan_path)
            else:
                missing_plan_names.append(node_name)

        generated_plan_map: Dict[str, str] = {}
        if missing_plan_names:
            filtered_graph_plan = self._build_filtered_graph_plan_payload(missing_plan_names)
            generated_plan_paths = self.node_planner.plan_each(
                requirement_text=requirement_text,
                graph_plan_text=json.dumps(filtered_graph_plan, ensure_ascii=False, indent=2),
                output_dir=str(node_docs_dir),
                overwrite=True,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            generated_plan_map = {Path(path).stem: str(path) for path in generated_plan_paths}

        existing_ui_map: Dict[str, str] = {}
        missing_ui_names: List[str] = []
        for node_name in visible_node_names:
            ui_path = node_ui_dir / f"{node_name}.html"
            if ui_path.is_file():
                existing_ui_map[node_name] = str(ui_path)
            else:
                missing_ui_names.append(node_name)

        generated_ui_map: Dict[str, str] = {}
        if missing_ui_names:
            filtered_ui_graph_plan = self._build_filtered_graph_plan_payload(missing_ui_names)
            generated_ui_paths = self.node_planner.plan_each_ui(
                requirement_text=requirement_text,
                graph_plan_text=json.dumps(filtered_ui_graph_plan, ensure_ascii=False, indent=2),
                output_dir=str(node_ui_dir),
                overwrite=True,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            generated_ui_map = {Path(path).stem: str(path) for path in generated_ui_paths}

        all_plan_map = {
            node_name: str(node_docs_dir / f"{node_name}.md")
            for node_name in node_names
            if (node_docs_dir / f"{node_name}.md").is_file()
        }
        all_ui_map = {
            node_name: str(node_ui_dir / f"{node_name}.html")
            for node_name in visible_node_names
            if (node_ui_dir / f"{node_name}.html").is_file()
        }

        self.node_docs_dir = str(node_docs_dir)
        self.node_doc_paths = [all_plan_map[node_name] for node_name in node_names if node_name in all_plan_map]
        self.node_html_dir = str(node_ui_dir)
        self.node_html_paths = [all_ui_map[node_name] for node_name in visible_node_names if node_name in all_ui_map]

        self.dynamic_graph_cache["graph_nodes"] = node_names
        self.dynamic_graph_cache["graph_plan_path"] = str(Path(self.graph_plan_path).expanduser().resolve())
        self.dynamic_graph_cache["node_plans"] = all_plan_map
        self.dynamic_graph_cache["node_ui"] = all_ui_map

        return {
            "graph_plan_path": self.dynamic_graph_cache["graph_plan_path"],
            "node_plan": {
                "existing": existing_plan_map,
                "generated": generated_plan_map,
                "all": all_plan_map,
            },
            "node_ui": {
                "existing": existing_ui_map,
                "generated": generated_ui_map,
                "all": all_ui_map,
            },
        }

    def update_backend_nodes(
        self,
        graph_plan_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        language: str = "python",
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        plan_result = self.update_nodes_plan(
            graph_plan_path=graph_plan_path,
            requirement_md_path=requirement_md_path,
            node_docs_dirname=node_docs_dirname,
            node_ui_dirname=node_ui_dirname,
            temperature=temperature,
        )
        planned_graph = self._load_planned_graph()
        node_names = planned_graph.get_topological_sorted_nodes()
        visible_node_names = [
            node_name for node_name in node_names
            if planned_graph.get_node_meta(node_name) and planned_graph.get_node_meta(node_name).show_frontend
        ]

        missing_plan_names = [node_name for node_name in node_names if node_name not in plan_result["node_plan"]["all"]]
        missing_ui_names = [node_name for node_name in visible_node_names if node_name not in plan_result["node_ui"]["all"]]
        if missing_plan_names or missing_ui_names:
            missing_sections: List[str] = []
            if missing_plan_names:
                missing_sections.append(f"missing node plan files for: {missing_plan_names}")
            if missing_ui_names:
                missing_sections.append(f"missing node ui files for: {missing_ui_names}")
            raise FileNotFoundError(
                "update_backend_nodes requires node plan/ui artifacts before code generation. "
                + "; ".join(missing_sections)
            )

        existing_backend_map: Dict[str, str] = {}
        missing_backend_names: List[str] = []
        for node_name in node_names:
            backend_path = self._expected_backend_node_path(node_name, language)
            if backend_path.is_file():
                existing_backend_map[node_name] = str(backend_path)
            else:
                missing_backend_names.append(node_name)

        generated_backend_paths = self._generate_selected_nodes(
            missing_backend_names,
            language=language,
            temperature=temperature,
            reset_mappings=False,
        )
        generated_backend_map = {Path(path).stem: str(path) for path in generated_backend_paths}
        all_backend_map = {
            node_name: str(self._expected_backend_node_path(node_name, language))
            for node_name in node_names
            if self._expected_backend_node_path(node_name, language).is_file()
        }
        if not hasattr(self, "node_location_map"):
            self.node_location_map = {}
        for node_name, node_path in all_backend_map.items():
            self.node_location_map.setdefault(node_name, node_path)

        self.dynamic_graph_cache["backend_nodes"] = all_backend_map

        return {
            "node_plan": plan_result["node_plan"],
            "node_ui": plan_result["node_ui"],
            "backend_nodes": {
                "existing": existing_backend_map,
                "generated": generated_backend_map,
                "all": all_backend_map,
            },
        }

    def get_node_input_output_formats(
        self,
        graph_plan_path: Optional[str] = None,
        backend_language: str = "python",
    ) -> Dict[str, Dict[str, Any]]:
        """Return each node's normalized user input format and backend card schema.

        The returned mapping is keyed by node name. For each node we expose:
        - ``user_input_format``: normalized graph ``inputs_format`` for user_input/skill nodes
        - ``backend_output_card_format``: AST-derived preview of ``StepRunOutput.card`` from the node backend file
        - ``backend_node_path``: resolved backend node file path when present
        """
        planned_graph = self._load_planned_graph(graph_plan_path)
        node_formats: Dict[str, Dict[str, Any]] = {}

        for node_name in planned_graph.get_topological_sorted_nodes():
            node_meta = planned_graph.get_node_meta(node_name)
            inputs_format = node_meta.inputs_format if node_meta and getattr(node_meta, "inputs_format", None) else {}
            if not isinstance(inputs_format, Mapping):
                inputs_format = {}

            normalized_inputs_format: Dict[str, str] = {}
            for key, value in inputs_format.items():
                field_name = str(key).strip()
                field_type = str(value).strip().lower()
                if field_name and field_type:
                    normalized_inputs_format[field_name] = field_type

            ext_data = node_meta.ext_data if node_meta and getattr(node_meta, "ext_data", None) else {}
            if isinstance(ext_data, Mapping):
                ext_type = str(ext_data.get("type", "none")).strip().lower()
            else:
                ext_type = str(ext_data).strip().lower() or "none"
            if ext_type not in {"user_input", "skill"}:
                normalized_inputs_format = {}

            backend_path_value = None
            if hasattr(self, "node_location_map") and isinstance(self.node_location_map, dict):
                backend_path_value = self.node_location_map.get(node_name)
            if backend_path_value:
                backend_path = self._resolve_root_path(backend_path_value)
            else:
                backend_path = self._expected_backend_node_path(node_name, backend_language)

            backend_card_schema = None
            backend_path_str: Optional[str] = None
            if backend_path.is_file():
                backend_card_schema = compile_node_file_and_get_step_output_card_schema(str(backend_path))
                backend_path_str = str(backend_path)

            node_formats[node_name] = {
                "user_input_format": normalized_inputs_format,
                "backend_output_card_format": backend_card_schema.get("card") if backend_card_schema else None,
                "backend_node_path": backend_path_str,
            }

        self.dynamic_graph_cache["node_input_output_formats"] = node_formats
        return node_formats

    def update_nodes(
        self,
        graph_plan_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        frontend_output_dir: str = "frontend",
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        language: str = "python",
        temperature: float = 0.3,
        frontend_style_prompt: Optional[str] = None,
        context_base_dir: Optional[str] = None,
        max_frontend_audit_rounds: int = 4,
        backend_port: int = 8000,
        main_output_filename: str = "main.py",
    ) -> Dict[str, Any]:
        backend_result = self.update_backend_nodes(
            graph_plan_path=graph_plan_path,
            requirement_md_path=requirement_md_path,
            node_docs_dirname=node_docs_dirname,
            node_ui_dirname=node_ui_dirname,
            language=language,
            temperature=temperature,
        )
        planned_graph = self._load_planned_graph()
        node_names = planned_graph.get_topological_sorted_nodes()
        visible_node_names = [
            node_name for node_name in node_names
            if planned_graph.get_node_meta(node_name) and planned_graph.get_node_meta(node_name).show_frontend
        ]

        frontend_project_dir = self._ensure_vue_frontend_project(frontend_output_dir, backend_port=backend_port)
        self.frontend_project_dir = frontend_project_dir
        frontend_src_dir = self._resolve_root_path(Path(frontend_project_dir) / "src")

        existing_frontend_map = self._collect_current_frontend_node_outputs(frontend_src_dir, visible_node_names)
        missing_frontend_names = [node_name for node_name in visible_node_names if node_name not in existing_frontend_map]
        generated_frontend_map = self._generate_selected_frontend_views(
            missing_frontend_names,
            output_base_dir=str(frontend_src_dir),
            context_base_dir=context_base_dir,
            temperature=temperature,
            overwrite_existing=False,
        )
        all_frontend_map = self._collect_current_frontend_node_outputs(frontend_src_dir, visible_node_names)

        resolved_context_dir = str(self._resolve_root_path(context_base_dir or self.root_dir))
        workflow_json_path = self._sync_workflow_graph_json(context_base_dir=resolved_context_dir)
        steps_meta = self._build_steps_meta()
        store_steps_meta = self._build_steps_meta(include_hidden_nodes=True)
        effective_style_prompt = frontend_style_prompt
        if effective_style_prompt is None:
            effective_style_prompt = self.frontend_style_prompt
        if isinstance(effective_style_prompt, str):
            effective_style_prompt = effective_style_prompt.strip() or None
        reference_frontend_src_dir = get_reference_frontend_src_dir()

        shared_frontend_outputs = self.frontend_writer.write_frontend_src_files(
            steps_meta=steps_meta,
            store_steps_meta=store_steps_meta,
            output_base_dir=str(frontend_src_dir),
            context_base_dir=resolved_context_dir,
            run_step_endpoint="/api/run-step",
            reset_session_endpoint="/api/reset-session",
            requirement_analysis_result=self.requirement_analysis_result,
            reference_frontend_src_dir=reference_frontend_src_dir,
            frontend_style_prompt=effective_style_prompt,
            overwrite=True,
            temperature=temperature,
        )
        self._audit_frontend_src(
            frontend_path=str(frontend_src_dir),
            steps_meta=steps_meta,
            context_base_dir=resolved_context_dir,
            reference_frontend_src_dir=reference_frontend_src_dir,
            frontend_style_prompt=effective_style_prompt,
            temperature=temperature,
            max_audit_rounds=max_frontend_audit_rounds,
        )

        main_output_target = getattr(self, "main_output_path", os.path.join(self.root_dir, main_output_filename))
        main_output_path = self.generate_main_entrypoint(
            self.graph_plan_path,
            output_filename=str(main_output_target),
            temperature=temperature,
            fastapi_port=backend_port,
        )

        self.frontend_output_path = str(frontend_src_dir)
        self.dynamic_graph_cache["frontend_nodes"] = all_frontend_map
        self.dynamic_graph_cache["frontend_shared"] = {
            key: str(path) for key, path in shared_frontend_outputs.items()
        }

        return {
            "node_plan": backend_result["node_plan"],
            "node_ui": backend_result["node_ui"],
            "backend_nodes": backend_result["backend_nodes"],
            "frontend_nodes": {
                "existing": existing_frontend_map,
                "generated": generated_frontend_map,
                "all": all_frontend_map,
            },
            "frontend_shared": {
                key: str(path) for key, path in shared_frontend_outputs.items()
            },
            "workflow_json_path": workflow_json_path,
            "main_entrypoint": main_output_path,
        }

    def rerun_server(
        self,
        graph_plan_path: Optional[str] = None,
        frontend_project_dir: Optional[str] = None,
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        backend_language: str = "python",
        main_entrypoint_path: Optional[str] = None,
        backend_port: int = 8000,
        frontend_host: str = "127.0.0.1",
        frontend_port: int = 8080,
    ) -> Dict[str, Any]:
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")

        resolved_frontend_project_dir = frontend_project_dir or getattr(self, "frontend_project_dir", "frontend")
        artifact_state = self._validate_generated_artifacts(
            frontend_project_dir=resolved_frontend_project_dir,
            graph_plan_path=self.graph_plan_path,
            node_docs_dirname=node_docs_dirname,
            node_ui_dirname=node_ui_dirname,
            backend_language=backend_language,
            main_entrypoint_path=main_entrypoint_path,
        )

        resolved_frontend_dir = Path(artifact_state["frontend_project_dir"]).expanduser().resolve()
        main_path = Path(artifact_state["main_entrypoint"]).expanduser().resolve()
        self._write_vue_proxy_config(resolved_frontend_dir, backend_port=backend_port)

        self._stop_managed_server_process(self.backend_server_process)
        self._stop_managed_server_process(self.frontend_server_process)

        python_cmd = select_python_command()
        npm_cmd = shutil.which("npm") or "npm"
        backend_command = [python_cmd, str(main_path)]
        frontend_command = [npm_cmd, "run", "serve", "--", "--host", frontend_host, "--port", str(frontend_port)]

        self.backend_server_process = subprocess.Popen(
            backend_command,
            cwd=str(main_path.parent),
            env=os.environ.copy(),
        )
        self.frontend_server_process = subprocess.Popen(
            frontend_command,
            cwd=str(resolved_frontend_dir),
            env=os.environ.copy(),
        )

        server_runtime = {
            "backend": {
                "pid": getattr(self.backend_server_process, "pid", None),
                "command": backend_command,
                "cwd": str(main_path.parent),
            },
            "frontend": {
                "pid": getattr(self.frontend_server_process, "pid", None),
                "command": frontend_command,
                "cwd": str(resolved_frontend_dir),
            },
            "artifacts": artifact_state,
        }
        self.dynamic_graph_cache["server_runtime"] = server_runtime
        return server_runtime

    def amend_node_ui(
        self,
        node_name: str,
        amendment: str,
        existing_html_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        graph_plan_path: Optional[str] = None,
        output_path: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
        overwrite: bool = True,
    ) -> str:
        """Amend a single node UI HTML file using file-based planner wrapper."""
        if not isinstance(node_name, str) or not node_name.strip():
            raise ValueError("node_name must be a non-empty string.")
        if not isinstance(amendment, str) or not amendment.strip():
            raise ValueError("amendment must be a non-empty string.")

        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path

        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")

        target_html_path = existing_html_path
        if target_html_path is None:
            target_html_path = os.path.join(self.root_dir, "node_ui", f"{node_name}.html")

        print(f"Amending node UI '{node_name}' -> {target_html_path}")
        amended_path = self.node_planner.amend_node_ui_from_files(
            node_name=node_name,
            user_prompt=amendment,
            existing_html_path=target_html_path,
            requirement_md_path=self.requirement_md_path,
            graph_plan_json_path=self.graph_plan_path,
            output_path=output_path,
            overwrite=overwrite,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        final_path = str(amended_path)
        self.last_amended_node_ui_path = final_path
        return final_path

    def amend_node_markdown(
        self,
        node_name: str,
        amendment: str,
        existing_markdown_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        graph_plan_path: Optional[str] = None,
        output_path: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
        overwrite: bool = True,
    ) -> str:
        """Amend a single graph node and regenerate its markdown planning doc."""
        if not isinstance(node_name, str) or not node_name.strip():
            raise ValueError("node_name must be a non-empty string.")
        if not isinstance(amendment, str) or not amendment.strip():
            raise ValueError("amendment must be a non-empty string.")

        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path

        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")

        target_markdown_path = output_path or existing_markdown_path
        if target_markdown_path is None:
            target_markdown_path = os.path.join(self.root_dir, "node_docs", f"{node_name}.md")
        target_html_dir = getattr(self, "node_html_dir", os.path.join(self.root_dir, "node_ui"))
        target_html_path = os.path.join(target_html_dir, f"{node_name}.html")

        print(f"Amending node markdown '{node_name}' -> {target_markdown_path}")
        amended_graph_path, amended_doc_path = self.node_planner.amend_graph_node_from_files(
            node_name=node_name,
            user_prompt=amendment,
            requirement_md_path=self.requirement_md_path,
            graph_plan_json_path=self.graph_plan_path,
            node_output_path=target_markdown_path,
            node_ui_output_path=target_html_path,
            overwrite=overwrite,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        self.graph_plan_path = str(amended_graph_path)
        self.planned_graph = Graph(self.graph_plan_path)
        self.planner._write_mermaid_from_graph_json(Path(self.graph_plan_path))

        final_path = str(amended_doc_path)
        self.node_docs_dir = str(Path(final_path).parent)
        existing_paths = list(getattr(self, "node_doc_paths", []) or [])
        expected_name = f"{node_name}.md"
        updated_paths = [path for path in existing_paths if Path(path).name != expected_name]
        updated_paths.append(final_path)
        self.node_doc_paths = updated_paths
        self.last_amended_node_doc_path = final_path

        node_meta = self.planned_graph.get_node_meta(node_name)
        existing_html_paths = list(getattr(self, "node_html_paths", []) or [])
        expected_html_name = f"{node_name}.html"
        self.node_html_paths = [
            path for path in existing_html_paths if Path(path).name != expected_html_name
        ]
        if node_meta and node_meta.show_frontend:
            self.node_html_dir = str(Path(target_html_path).parent)
            self.node_html_paths.append(target_html_path)
            self.last_amended_node_ui_path = target_html_path
        return final_path

    def _build_steps_meta(self, include_hidden_nodes: bool = False) -> List[Dict[str, Any]]:
        """Build step metadata for frontend generation from planned graph."""
        steps_meta: List[Dict[str, Any]] = []
        for node_name in self.planned_graph.get_topological_sorted_nodes():
            node_meta = self.planned_graph.get_node_meta(node_name)
            if node_meta and not node_meta.show_frontend and not include_hidden_nodes:
                continue
            title = (node_meta.desc or node_name) if node_meta else node_name
            prompt = (node_meta.desc or f"Provide input for {node_name}") if node_meta else f"Provide input for {node_name}"
            dependencies = node_meta.depends if node_meta and node_meta.depends else []
            services = node_meta.services if node_meta and node_meta.services else []
            ext_data = node_meta.ext_data if node_meta and node_meta.ext_data else {"type": "none", "desc": "no need for ext data"}
            inputs_format = node_meta.inputs_format if node_meta and getattr(node_meta, "inputs_format", None) else {}
            if not isinstance(inputs_format, Mapping):
                inputs_format = {}
            normalized_inputs_format: Dict[str, str] = {}
            for key, value in inputs_format.items():
                field_name = str(key).strip()
                field_type = str(value).strip().lower()
                if field_name and field_type:
                    normalized_inputs_format[field_name] = field_type
            if isinstance(ext_data, dict):
                ext_type = str(ext_data.get("type", "none")).strip().lower()
                ext_desc = str(ext_data.get("desc", "")).strip()
                service_name = str(ext_data.get("service_name", "")).strip()
            else:
                ext_type = str(ext_data).strip().lower() or "none"
                ext_desc = ""
                service_name = ""

            input_required = ext_type in {"user_input", "user_file_input"}
            if ext_type == "user_file_input":
                node_kind = "file"
            elif ext_type == "service" or service_name:
                node_kind = "service"
            elif ext_type == "skill" or str(ext_data.get("skill_name", "") if isinstance(ext_data, Mapping) else "").strip():
                node_kind = "skill"
            elif input_required:
                node_kind = "input"
            else:
                node_kind = "operation"
            steps_meta.append(
                {
                    "id": node_name,
                    "title": title,
                    "prompt": prompt,
                    "dependencies": dependencies,
                    "services": services,
                    "inputRequired": input_required,
                    "nodeKind": node_kind,
                    "extData": {
                        "type": ext_type,
                        "desc": ext_desc,
                        "inputs_format": normalized_inputs_format if ext_type in ("user_input", "skill") else {},
                    },
                }
            )
        return steps_meta

    @classmethod
    def _resolve_frontend_violation_target(cls, frontend_src_dir: str | Path, violation: Any) -> Optional[Path]:
        file_map = build_frontend_src_file_map(frontend_src_dir)
        rule_to_target = {
            "execution_endpoint_missing": "api",
            "reset_session_endpoint_missing": "api",
            "step_card_handler_missing": "store",
            "session_id_usage_missing": "store",
            "step_output_schema_renderer_missing": "app_shell",
            "app_shell_import_missing": "app",
            "app_view_import_missing": "app",
        }

        frontend_src_path = Path(frontend_src_dir).expanduser().resolve()
        for raw_path in [
            getattr(violation, "class_name", ""),
            str(getattr(violation, "detail", "")).split(":", 1)[0].strip(),
        ]:
            if not raw_path:
                continue
            candidate = Path(raw_path).expanduser()
            if candidate.is_file():
                return candidate.resolve()
            if not candidate.is_absolute():
                relative_candidate = (frontend_src_path / candidate).resolve()
                if relative_candidate.is_file():
                    return relative_candidate

        target_key = rule_to_target.get(getattr(violation, "rule", ""))
        if target_key is None:
            return None
        return file_map[target_key]

    def generate_frontend(
        self,
        output_filename: str = "frontend",
        frontend_mode: str = "vue_src",
        temperature: float = 0.3,
        frontend_style_prompt: Optional[str] = None,
        context_base_dir: Optional[str] = None,
        max_audit_rounds: int = 4,
        backend_port: int = 8000,
    ) -> str:
        """Generate and audit frontend output in vue_src mode."""
        frontend_path = os.path.join(self.root_dir, output_filename+"/src")
        frontend_project_dir = os.path.join(self.root_dir, output_filename)
        self._ensure_vue_frontend_project(frontend_project_dir, backend_port=backend_port)
        print(f"Generating frontend -> {frontend_path}")
        steps_meta = self._build_steps_meta()
        store_steps_meta = self._build_steps_meta(include_hidden_nodes=True)

        if max_audit_rounds < 1:
            raise ValueError("max_audit_rounds must be at least 1.")

        effective_style_prompt = frontend_style_prompt
        if effective_style_prompt is None:
            effective_style_prompt = self.frontend_style_prompt
        if isinstance(effective_style_prompt, str):
            effective_style_prompt = effective_style_prompt.strip() or None
        print("starting frontend generation with style prompt:", repr(effective_style_prompt))

        if frontend_mode != "vue_src":
            raise ValueError("frontend_mode must be 'vue_src'.")
        reference_frontend_src_dir = get_reference_frontend_src_dir()
        self.frontend_project_dir = frontend_project_dir
        self.generate_frontend_views(
            output_base_dir=frontend_path,
            context_base_dir=context_base_dir,
            temperature=temperature,
        )

        self.frontend_writer.write_frontend_src_files(
            steps_meta=steps_meta,
            store_steps_meta=store_steps_meta,
            output_base_dir=frontend_path,
            context_base_dir=context_base_dir,
            run_step_endpoint="/api/run-step",
            reset_session_endpoint="/api/reset-session",
            requirement_analysis_result=self.requirement_analysis_result,
            reference_frontend_src_dir=reference_frontend_src_dir,
            frontend_style_prompt=effective_style_prompt,
            overwrite=True,
            temperature=temperature,
        )
        self._audit_frontend_src(
            frontend_path=frontend_path,
            steps_meta=steps_meta,
            context_base_dir=context_base_dir,
            reference_frontend_src_dir=reference_frontend_src_dir,
            frontend_style_prompt=effective_style_prompt,
            temperature=temperature,
            max_audit_rounds=max_audit_rounds,
        )

        self.frontend_output_path = frontend_path
        return frontend_path

    def _prepare_frontend_project_and_main_entrypoint(
        self,
        *,
        frontend_project_dir: str | Path | None = None,
        backend_port: int = 8000,
        ensure_frontend_project: bool = False,
        write_proxy_config: bool = False,
        graph_plan_path: Optional[str] = None,
        output_filename: str = "main.py",
        fastapi_host: str = "0.0.0.0",
        temperature: float = 0.0,
        fastapi_port: int = 8000,
        generate_main_entrypoint: bool = False,
    ) -> tuple[str | None, str | None]:
        resolved_frontend_dir: Path | None = None
        if frontend_project_dir is not None:
            resolved_frontend_dir = Path(frontend_project_dir).expanduser()
            if not resolved_frontend_dir.is_absolute():
                resolved_frontend_dir = Path(self.root_dir).expanduser() / resolved_frontend_dir
            resolved_frontend_dir = resolved_frontend_dir.resolve()

        if ensure_frontend_project:
            if resolved_frontend_dir is None:
                raise ValueError("frontend_project_dir is required when ensure_frontend_project=True.")

            if resolved_frontend_dir.exists():
                pass
            else:
                vue_executable = shutil.which("vue")
                if not vue_executable:
                    create_minimal_vue_frontend_scaffold(resolved_frontend_dir)
                    print(
                        "warning: Vue CLI is not installed or not available on PATH; "
                        f"using minimal frontend scaffold at {resolved_frontend_dir}"
                    )
                else:
                    print(f"Creating Vue frontend project -> {resolved_frontend_dir}")
                    try:
                        subprocess.run(
                            [vue_executable, "create", resolved_frontend_dir.name, "--default"],
                            cwd=str(resolved_frontend_dir.parent),
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                    except subprocess.CalledProcessError as exc:
                        stderr = exc.stderr.strip() if exc.stderr else ""
                        stdout = exc.stdout.strip() if exc.stdout else ""
                        detail = stderr or stdout or str(exc)
                        create_minimal_vue_frontend_scaffold(resolved_frontend_dir)
                        print(
                            "warning: vue create failed; "
                            f"using minimal frontend scaffold at {resolved_frontend_dir}. "
                            f"Original error: {detail}"
                        )
                    except OSError as exc:
                        create_minimal_vue_frontend_scaffold(resolved_frontend_dir)
                        print(
                            "warning: vue command execution failed; "
                            f"using minimal frontend scaffold at {resolved_frontend_dir}. "
                            f"Original error: {exc}"
                        )

        if write_proxy_config:
            if resolved_frontend_dir is None:
                raise ValueError("frontend_project_dir is required when write_proxy_config=True.")
            if not isinstance(backend_port, int) or not (1 <= backend_port <= 65535):
                raise ValueError("backend_port must be an integer in range 1..65535.")

            vue_config_path = resolved_frontend_dir / "vue.config.js"
            vue_config_path.write_text(
                "const { defineConfig } = require('@vue/cli-service')\n"
                "module.exports = defineConfig({\n"
                "  devServer: {\n"
                "    proxy: {\n"
                "      '/api': {\n"
                f"        target: 'http://127.0.0.1:{backend_port}',\n"
                "        changeOrigin: true,\n"
                "      },\n"
                "    },\n"
                "  },\n"
                "})\n",
                encoding="utf-8",
            )

        generated_main_output_path: str | None = None
        if generate_main_entrypoint:
            self.main_output_path = os.path.join(self.root_dir, output_filename)
            print(f"Generating main entrypoint -> {self.main_output_path}")
            self.main_writer.write_main_entrypoint(
                project_root_path=self.root_dir,
                graph_plan_json_path=graph_plan_path or "",
                output_path=self.main_output_path,
                requirement_analysis_result=self.requirement_analysis_result,
                fastapi_host=fastapi_host,
                fastapi_port=fastapi_port,
                temperature=temperature,
            )

            while True:
                ok, violations = self.main_entry_auditor.audit_main_entrypoint_file(
                    str(self.main_output_path),
                    str(self.root_dir),
                )
                if ok:
                    print("Main entrypoint audit passed.")
                    break
                amendment = "\n".join(
                    [f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations]
                )
                print(amendment)
                print("Main entrypoint audit failed. Applying amendment...")
                self.main_writer.amend_code_with_feedback(
                    self.main_output_path,
                    amendment,
                    language="python",
                    temperature=0.2,
                )

            generated_main_output_path = self.main_output_path

        return (
            str(resolved_frontend_dir) if resolved_frontend_dir is not None else None,
            generated_main_output_path,
        )

    def _ensure_vue_frontend_project(self, frontend_project_dir: str, backend_port: int = 8000) -> str:
        """Create the Vue frontend project with Vue CLI when it is missing."""
        resolved_frontend_dir, _ = self._prepare_frontend_project_and_main_entrypoint(
            frontend_project_dir=frontend_project_dir,
            backend_port=backend_port,
            ensure_frontend_project=True,
            write_proxy_config=True,
        )
        if resolved_frontend_dir is None:
            raise RuntimeError("frontend project preparation did not return a directory path.")
        return resolved_frontend_dir

    def _write_vue_proxy_config(self, frontend_dir: Path, backend_port: int = 8000) -> None:
        self._prepare_frontend_project_and_main_entrypoint(
            frontend_project_dir=frontend_dir,
            backend_port=backend_port,
            write_proxy_config=True,
        )

    def generate_frontend_views(
        self,
        graph_plan_path: Optional[str] = None,
        output_base_dir: str = "frontend/src",
        context_base_dir: Optional[str] = None,
        temperature: float = 0.3,
    ) -> Dict[str, Dict[str, str]]:
        """Generate one Vue view and stylesheet per graph node in dependency order."""
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")

        graph_path = Path(self.graph_plan_path).expanduser().resolve()
        planned_graph = getattr(self, "planned_graph", None)
        if planned_graph is None or Path(planned_graph.graph_json_path).resolve() != graph_path:
            self.planned_graph = Graph(str(graph_path))

        resolved_output_dir = Path(output_base_dir).expanduser()
        if not resolved_output_dir.is_absolute():
            resolved_output_dir = Path(self.root_dir).expanduser() / resolved_output_dir
        resolved_output_dir = resolved_output_dir.resolve()

        if context_base_dir is None:
            resolved_context_dir = Path(self.root_dir).expanduser().resolve()
        else:
            resolved_context_dir = Path(context_base_dir).expanduser().resolve()

        graph_plan_context = graph_path.read_text(encoding="utf-8")
        self.frontend_view_writer_map = {}
        self.frontend_view_output_map = {}
        self.frontend_views_output_path = str(resolved_output_dir)

        nodes = [
            node_name
            for node_name in self.planned_graph.get_topological_sorted_nodes()
            if not self.planned_graph.get_node_meta(node_name)
            or self.planned_graph.get_node_meta(node_name).show_frontend
        ]
        total = len(nodes)
        pipeline = GPipeline()

        elements: Dict[str, _FrontendViewGenerateElement] = {}
        for index, name in enumerate(nodes, start=1):
            elements[name] = _FrontendViewGenerateElement(
                self,
                name,
                total,
                index,
                output_base_dir=str(resolved_output_dir),
                context_base_dir=str(resolved_context_dir),
                graph_plan_context=graph_plan_context,
                temperature=temperature,
            )
            self.frontend_view_writer_map[name] = elements[name].coder

        for name in nodes:
            node_meta = self.planned_graph.get_node_meta(name)
            depends = set()
            if node_meta and node_meta.depends:
                depends = {elements[dep] for dep in node_meta.depends if dep in elements}
            status = pipeline.registerGElement(elements[name], depends, name, 1)
            if status.isErr():
                raise RuntimeError(f"registerGElement failed for frontend view {name}: {status.getInfo()}")

        process_status = pipeline.process()
        if process_status.isErr():
            raise RuntimeError(f"generate_frontend_views pipeline.process failed: {process_status.getInfo()}")

        return self.frontend_view_output_map

    def generate_main_entrypoint(
        self,
        graph_plan_path: str,
        output_filename: str = "main.py",
        fastapi_host: str = "0.0.0.0",
        temperature: float = 0.0,
        fastapi_port: int = 8000,
    ) -> str:
        _, generated_main_output_path = self._prepare_frontend_project_and_main_entrypoint(
            graph_plan_path=graph_plan_path,
            output_filename=output_filename,
            fastapi_host=fastapi_host,
            temperature=temperature,
            fastapi_port=fastapi_port,
            generate_main_entrypoint=True,
        )
        if generated_main_output_path is None:
            raise RuntimeError("main entrypoint generation did not return an output path.")
        self.main_output_path = generated_main_output_path
        return self.main_output_path

    def test_main_entrypoint(
        self,
        main_entrypoint_path: str,
        log_filename: str = "test_log.txt",
        graph_plan_path: Optional[str] = None,
    ) -> bool:
        """Test the generated main_entrypoint.py and write logs to a file.

        This method will exercise the main entrypoint as a subprocess and
        record both stdout and stderr output to a log file.  After the run the
        log is audited and amendments are applied to any code files mentioned
        in the traceback.

        Args:
            main_entrypoint_path: Path to the main_entrypoint.py file to test.
            log_filename: Name of the log file to write output to (under root_dir).
            graph_plan_path: Optional path to the graph plan JSON.  When
            provided the graph is used to decide whether a filename mentioned in
            the log corresponds to a node; this helps select the appropriate
            coder when applying amendments.

        Returns:
            Path to the log file.
        """
        # make sure we use absolute paths to avoid cwd duplication
        abs_path = os.path.abspath(main_entrypoint_path)
        self.log_path = os.path.join(self.root_dir, log_filename)

        with open(self.log_path, "w") as log_file:
            log_file.write(f"=== Main Entrypoint Test Log ===\n")
            log_file.write(f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"Testing file: {abs_path}\n")
            log_file.write(f"{'='*50}\n\n")

            try:
                # Run the main_entrypoint.py as a subprocess
                python_cmd = "python3.10"
                log_file.write(f"Executing: {python_cmd} {abs_path}\n\n")
                result = subprocess.run(
                    [python_cmd, abs_path],
                    cwd=os.path.dirname(abs_path),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                log_file.write(f"Return code: {result.returncode}\n\n")

                if result.stdout:
                    log_file.write(f"--- STDOUT ---\n{result.stdout}\n\n")
                if result.stderr:
                    log_file.write(f"--- STDERR ---\n{result.stderr}\n\n")

                if result.returncode == 0:
                    log_file.write("✓ Test completed successfully.\n")
                else:
                    log_file.write(f"✗ Test failed with return code {result.returncode}.\n")

            except subprocess.TimeoutExpired:
                log_file.write("✗ Test timed out after 60 seconds.\n")
            except Exception as e:
                log_file.write(f"✗ Test raised an exception: {type(e).__name__}: {e}\n")

            log_file.write(f"\n{'='*50}\n")
            log_file.write(f"Test ended: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        print(f"Test log written to: {self.log_path}")

        # after writing the log, run the output auditor and apply amendments if needed
        finished = self.amend_by_log(self.log_path)
        return finished

    def amend_by_log(
        self,
        log_path: str
    ) -> bool:
        """Run output auditor on a log and apply code amendments.

        Uses pre-built mappings (node_map and node_location_map) to retrieve the
        appropriate coder and file location for each node that needs amendment.

        Args:
            log_path: Path to the test log produced by :meth:`test_main_entrypoint`.
            graph_plan_path: Optional path to the graph plan JSON (unused; kept for
            signature compatibility).
        """
        ok, violations = self.output_auditor.audit_log_file(log_path)
        if not ok:
            for v in violations:
                fname = v.rule
                detail = v.detail
                coder = None
                target_path = fname

                # try to find node coder from stored mappings
                if hasattr(self, 'node_coder_map') and hasattr(self, 'node_location_map'):
                    for node_name, node_file_location in self.node_location_map.items():
                        if fname == node_file_location or node_name in fname:
                            coder = self.node_coder_map[node_name]
                            target_path = node_file_location
                            break

                # fallback based on filename patterns
                if coder is None:
                    if fname.endswith("main.py") or "main" in os.path.basename(fname):
                        coder = self.main_writer
                        if hasattr(self, 'main_output_path'):
                            target_path = self.main_output_path
                    else:
                        coder = PromptNodeFileCoderBase(api_key=self.api_key, model=self.model, provider=self.provider)
                        if hasattr(self, 'node_location_map'):
                            for node_file_location in self.node_location_map.values():
                                if os.path.basename(node_file_location) == os.path.basename(fname):
                                    target_path = node_file_location
                                    break

                try:
                    print(f"Applying amendment to {fname}: {detail}")
                    current_node_name = Path(target_path).stem
                    coder.amend_code_with_feedback(
                        target_path,
                        detail,
                        graph_plan_path=self.graph_plan_path or "",
                        requirement_md_path=self.requirement_md_path or "",
                        current_node_name=current_node_name,
                        language="python",
                        temperature=0.3,
                    )
                except Exception as e:
                    print(f"Failed to amend {fname}: {e}")
        return ok

    def run_full_pipeline(
        self,
        requirement_text: Optional[str] = None,
        requirement_file: Optional[str] = None,
        test_after_generation: bool = True,
        generate_node_docs: bool = True,
        generate_node_html: bool = True,
        frontend_mode: str = "vue_src",
        frontend_style_prompt: Optional[str] = None,
        context_base_dir: Optional[str] = None,
        backend_port: int = 8000,
    ) -> None:
        """Run full build pipeline and generate AG-UI deliverables.

        Args:
            requirement_text: Raw requirement text to analyze.
            requirement_file: Path to an existing requirement file (takes precedence).
            test_after_generation: Whether to test generated main.py after generation.
            generate_node_docs: Whether to generate per-node markdown planning docs.
            generate_node_html: Whether to generate per-node HTML interaction files for node writing context.
            frontend_mode: Frontend output mode. Only 'vue_src' is supported.
            frontend_style_prompt: Optional style guidance for generated frontend output.
            context_base_dir: Optional base directory for loading workflow.json and node_ui/*.html used as frontend generation context.
            backend_port: Backend API port used by the generated Vue devServer proxy.
        """
        total_steps = 5
        if generate_node_docs:
            total_steps += 1
        if generate_node_html:
            total_steps += 1
        if test_after_generation:
            total_steps += 1
        self._start_progress(total_steps=total_steps)

        if frontend_style_prompt is not None:
            self.frontend_style_prompt = frontend_style_prompt.strip() or None

        req_path = self.analyze_requirement(requirement_text=requirement_text, requirement_file=requirement_file)
        self._advance_progress("Requirement analyzed")

        self.graph_plan_path = self.plan_graph(req_path, graph_plan_filename="workflow.json")
        self._advance_progress("Graph plan generated and audited")

        if generate_node_docs:
            self.generate_node_markdowns(
                requirement_md_path=req_path,
                graph_plan_path=self.graph_plan_path,
                output_dirname="node_docs",
                temperature=0.0,
            )
            self._advance_progress("Per-node markdown plans generated")

        if generate_node_html:
            self.generate_node_html(
                requirement_md_path=req_path,
                graph_plan_path=self.graph_plan_path,
                output_dirname="node_ui",
                temperature=0.0,
            )
            self._advance_progress("Per-node HTML interaction files generated")

        print("Starting node generation and audit...")
        self.generate_nodes(language="python", temperature=0.0)
        print("All nodes generated and audited successfully.")
        self._advance_progress("Node files generated and audited")

        print("Generating frontend...")
        self.generate_frontend(
            output_filename=os.path.join("frontend", "src"),
            frontend_mode=frontend_mode,
            temperature=0.0,
            frontend_style_prompt=self.frontend_style_prompt,
            context_base_dir=context_base_dir,
            backend_port=backend_port,
        )
        self._advance_progress(f"frontend generated and audited ({frontend_mode})")

        print("Generating main entrypoint...")
        main_entrypoint_path = self.generate_main_entrypoint(
            self.graph_plan_path,
            output_filename="main.py",
            temperature=0.0,
        )
        self._advance_progress("main.py generated and audited")

        if test_after_generation:
            print("Testing main.py...")
            while True:
                finished = self.test_main_entrypoint(
                    main_entrypoint_path,
                    log_filename="test_log.txt",
                    graph_plan_path=self.graph_plan_path,
                )
                if finished:
                    print("run sim tests all passed!")
                    break
                else:
                    print("Amendments applied based on test log. Retesting...")
            self._advance_progress("main.py test and amendment loop completed")

        print("Build outputs:")
        print(f"- graph_plan_path.json: {self.graph_plan_path}")
        if generate_node_docs:
            print(f"- node_docs/: {getattr(self, 'node_docs_dir', '')}")
        if generate_node_html:
            print(f"- node_ui/: {getattr(self, 'node_html_dir', '')}")
        print(f"- frontend: {self.frontend_output_path}")
        print(f"- main.py: {self.main_output_path}")


from typing import Optional, List, Dict, Any, Mapping
import os
import subprocess
import json
from datetime import datetime
from pathlib import Path

from pydaograph import CStatus, GElement, GPipeline

from meta_agent.architect import GraphPlanner, NodePlanner, Graph
from meta_agent.auditor import GraphJsonAuditor, NodeAuditor, MainEntryPointAuditor, OutputAuditor
from meta_agent.llm_client.coder import MAX_TOKENS, compose_session_marking_prompt
from meta_agent.worker.main_writer import PromptMainFileCoder
from meta_agent.worker.node_writer import (
    PromptNodeFileCoderBase,
    SpatialTemporalContractNodeCoder,
    WorkflowOperationNodeCoder,
    WorkflowSkillNodeCoder,
    WorkflowFileNodeCoder,
    WorkflowStepNodeCoder,
    is_none_ext_data,
    is_skill_ext_data,
    is_file_ext_data,
    is_spatial_temporal_contract_ext_data,
)
from meta_agent.demand_analyzer import RequirementDisector
from meta_agent.logging_utils import configure_runtime_logging, get_logger
from meta_agent.tools.agent_builder_tools import (
    get_language_extension,
    select_python_command,
)
from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema


DEFAULT_MAX_AUDIT_ROUNDS = 7

class _NodeGenerateElement(GElement):
    def __init__(self, builder: "AgentBuilder", node_name: str,total: int, node_index: int, language: str, temperature: float) -> None:
        super().__init__()
        self.builder = builder
        self.node_name = node_name
        self.node_index = node_index
        self.node_meta = self.builder.planned_graph.get_node_meta(self.node_name)
        self.coder = self.builder._make_node_coder(self.node_meta)
        self.builder._sync_node_coder_root_dir(self.coder)
        self.total = total
        self.temperature = temperature
        self.language = language

    def run(self) -> CStatus:
        try:
            target_path = self.builder._expected_backend_node_path(self.node_name, self.language)
            self.builder._logger.info(
                "[%s/%s] Generating node '%s' -> %s",
                self.node_index,
                self.total,
                self.node_name,
                target_path,
            )

            # create a node-specific coder for this metadata type
            file_path = self.coder.write_node_from_requirement(
                self.node_name,
                self.node_meta,
                self.builder.requirement_md_path,
                str(target_path),
                graph_plan_path=self.builder.graph_plan_path,
                language=self.language,
                temperature=self.temperature,
            )

            max_audit_rounds = self.builder._resolve_max_audit_rounds()
            for audit_round in range(1, max_audit_rounds + 1):
                ok, violations = self.builder.node_auditor.audit_node_file(
                    file_path,
                    self.node_meta,
                    graph_plan_path=self.builder.graph_plan_path,
                )
                if ok:
                    self.builder._logger.info(
                        "[%s/%s] Node audit passed: %s",
                        self.node_index,
                        self.total,
                        self.node_name,
                    )
                    break
                amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
                if audit_round >= max_audit_rounds:
                    raise RuntimeError(
                        f"node audit did not pass for {self.node_name} after "
                        f"{max_audit_rounds} attempt(s). Last feedback:\n{amendment}"
                    )
                self.builder._logger.warning(
                    "[%s/%s] Node audit failed: %s. %s Applying amendment...",
                    self.node_index,
                    self.total,
                    self.node_name,
                    amendment,
                )
                self.coder.amend_code_with_feedback(
                    file_path,
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
            self.builder._logger.error(
                "[%s/%s] Node generation failed for %s: %s",
                self.node_index,
                self.total,
                self.node_name,
                exc,
                exc_info=True,
            )
            return CStatus(1001, f"node generation failed for {self.node_name}: {exc}")


class AgentBuilder:
    """Build AG-UI workflow artifacts with generation, auditing, and progress display."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        provider: str = "deepseek",
        root_dir: str = "./example",
        frontend_style_prompt: Optional[str] = None,
        skills_root_path: Optional[str] = None,
        log_level: str | int | None = None,
        log_filename: str = "meta_agent_debug.log",
        max_audit_rounds: int = DEFAULT_MAX_AUDIT_ROUNDS,
        session_marking_prompt: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.root_dir = root_dir
        self.frontend_style_prompt = frontend_style_prompt.strip() if frontend_style_prompt else None
        self.skills_root_path = skills_root_path.strip() if isinstance(skills_root_path, str) else ""
        self.max_audit_rounds = self._validate_max_audit_rounds(max_audit_rounds)
        self.session_marking_prompt = compose_session_marking_prompt(session_marking_prompt)
        os.makedirs(self.root_dir, exist_ok=True)
        self.log_level = log_level or os.getenv("META_AGENT_LOG_LEVEL", "INFO")
        self.runtime_log_path = str(
            configure_runtime_logging(
                self.root_dir,
                log_filename=log_filename,
                console_level=self.log_level,
            )
        )
        self._logger = get_logger(__name__)
        self._logger.info(f"Runtime log file: {self.runtime_log_path}")
        self._logger.debug(
            "Initialized AgentBuilder with model=%s provider=%s root_dir=%s skills_root_path=%s max_audit_rounds=%s",
            self.model,
            self.provider,
            Path(self.root_dir).expanduser().resolve(),
            self.skills_root_path,
            self.max_audit_rounds,
        )

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

    @staticmethod
    def _validate_max_audit_rounds(max_audit_rounds: int) -> int:
        if max_audit_rounds < 1:
            raise ValueError("max_audit_rounds must be at least 1.")
        return max_audit_rounds

    def _resolve_max_audit_rounds(self, max_audit_rounds: Optional[int] = None) -> int:
        if max_audit_rounds is None:
            return self.max_audit_rounds
        return self._validate_max_audit_rounds(max_audit_rounds)

    def _reset_llm_components(self) -> None:
        self._logger.debug(
            "Resetting LLM-backed components for model=%s provider=%s",
            self.model,
            self.provider,
        )
        self.analyzer = RequirementDisector(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            session_marking_prompt=self.session_marking_prompt,
        )
        self.planner = GraphPlanner(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            skills_root_path=self.skills_root_path,
            session_marking_prompt=self.session_marking_prompt,
        )
        self.node_planner = NodePlanner(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            skills_root_path=self.skills_root_path,
            session_marking_prompt=self.session_marking_prompt,
        )
        self.main_writer = PromptMainFileCoder(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            session_marking_prompt=self.session_marking_prompt,
        )

    @staticmethod
    def _frontend_removed_error() -> RuntimeError:
        return RuntimeError("Frontend generation has been removed from meta_agent.")

    @staticmethod
    def _node_ui_removed_error() -> RuntimeError:
        return RuntimeError("Node UI planning has been removed from meta_agent.")

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
        self._logger.info("Resetting LLM configuration.")
        self._reset_llm_components()

    def _make_node_coder(self, node_meta: Any) -> PromptNodeFileCoderBase:
        ext_data = node_meta.ext_data if node_meta and hasattr(node_meta, 'ext_data') else None
        if is_skill_ext_data(ext_data):
            return WorkflowSkillNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
                skills_root_path=self.skills_root_path,
                session_marking_prompt=self.session_marking_prompt,
            )
        if is_spatial_temporal_contract_ext_data(ext_data):
            return SpatialTemporalContractNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
                session_marking_prompt=self.session_marking_prompt,
            )
        if is_none_ext_data(ext_data):
            return WorkflowOperationNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
                session_marking_prompt=self.session_marking_prompt,
            )
        if is_file_ext_data(ext_data):
            return WorkflowFileNodeCoder(
                api_key=self.api_key,
                model=self.model,
                provider=self.provider,
                root_dir_path=self.root_dir,
                session_marking_prompt=self.session_marking_prompt,
            )
        return WorkflowStepNodeCoder(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            root_dir_path=self.root_dir,
            session_marking_prompt=self.session_marking_prompt,
        )

    def _resolve_root_path(self, path_value: str | Path) -> Path:
        resolved_path = Path(path_value).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = Path(self.root_dir).expanduser() / resolved_path
        return resolved_path.resolve()

    def _resolve_backend_node_base_dir(self) -> Path:
        if self.graph_plan_path:
            return Path(self.graph_plan_path).expanduser().resolve().parent
        return Path(self.root_dir).expanduser().resolve()

    def _sync_node_coder_root_dir(self, coder: PromptNodeFileCoderBase) -> None:
        if hasattr(coder, "root_dir_path"):
            coder.root_dir_path = str(self._resolve_backend_node_base_dir())

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
        return (self._resolve_backend_node_base_dir() / f"{node_name}{get_language_extension(language)}").resolve()

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
        del node_names, output_base_dir, context_base_dir, temperature, overwrite_existing
        raise self._frontend_removed_error()

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
        del frontend_path, steps_meta, context_base_dir, reference_frontend_src_dir, frontend_style_prompt, temperature, max_audit_rounds
        raise self._frontend_removed_error()

    def _validate_generated_artifacts(
        self,
        *,
        frontend_project_dir: str | Path | None = None,
        graph_plan_path: Optional[str] = None,
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        backend_language: str = "python",
        main_entrypoint_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        del frontend_project_dir, node_ui_dirname
        planned_graph = self._load_planned_graph(graph_plan_path)
        doc_dir = self._resolve_root_path(getattr(self, "node_docs_dir", node_docs_dirname))
        main_path = Path(main_entrypoint_path or getattr(self, "main_output_path", self._resolve_root_path("main.py"))).expanduser()
        if not main_path.is_absolute():
            main_path = self._resolve_root_path(main_path)

        node_names = planned_graph.get_topological_sorted_nodes()
        plan_outputs: Dict[str, str] = {}
        backend_outputs: Dict[str, str] = {}
        missing: List[str] = []

        for node_name in node_names:
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
        if not main_path.is_file():
            missing.append(str(main_path))

        if missing:
            raise FileNotFoundError(
                "Missing artifacts required for graph refresh/server restart:\n" + "\n".join(sorted(set(missing)))
            )

        return {
            "node_plan": plan_outputs,
            "backend_nodes": backend_outputs,
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
        self._logger.info(f"Pipeline started. Total steps: {self._progress_total}")
        self._print_progress_bar("Initializing")

    def _advance_progress(self, message: str) -> None:
        self._progress_current = min(self._progress_total, self._progress_current + 1)
        self._print_progress_bar(message)

    def _print_progress_bar(self, message: str) -> None:
        ratio = self._progress_current / self._progress_total if self._progress_total else 0
        filled = int(self._progress_width * ratio)
        bar = "#" * filled + "-" * (self._progress_width - filled)
        pct = int(ratio * 100)
        self._logger.info(f"[{bar}] {self._progress_current}/{self._progress_total} ({pct:3d}%) | {message}")

    def analyze_requirement(self, requirement_text: Optional[str] = None, requirement_file: Optional[str] = None, out_file: str = "requirement_analysis.md") -> str:
        """Produce a requirement analysis markdown file.

        Either `requirement_text` or `requirement_file` should be provided. If `requirement_file`
        is provided it is used as-is (and returned); otherwise `requirement_text` is processed
        by the `RequirementDisector` and written to `out_file` under `root_dir`.
        """
        if requirement_file:
            self.requirement_md_path = requirement_file
            self.requirement_analysis_result = None
            self._logger.info("Using existing requirement file -> %s", requirement_file)
            return requirement_file

        out_path = os.path.join(self.root_dir, out_file)
        self._logger.info("Analyzing requirement -> %s", out_path)
        self._logger.debug(
            "Requirement analysis input length=%s output_file=%s",
            len(requirement_text or ""),
            out_path,
        )
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
    ) -> str:
        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")

        self.graph_plan_path = os.path.join(self.root_dir, graph_plan_filename)
        self._logger.info("Planning graph -> %s", self.graph_plan_path)
        self.planner.plan_from_file(self.requirement_md_path, self.graph_plan_path)

        max_audit_rounds = self._resolve_max_audit_rounds()
        for audit_round in range(1, max_audit_rounds + 1):
            self.planned_graph = Graph(self.graph_plan_path)
            ok, violations = self.graph_auditor.audit_graph_json(self.planned_graph)
            if ok:
                self._logger.info("Graph plan audit passed.")
                break
            amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            if audit_round >= max_audit_rounds:
                raise RuntimeError(
                    "graph plan audit did not pass after "
                    f"{max_audit_rounds} attempt(s). Last feedback:\n{amendment}"
                )
            self._logger.warning("Graph audit failed. Applying amendment %s...", amendment)
            self.planner.amend_file_with_feedback(self.graph_plan_path, amendment, temperature=temperature)
        self.planner._write_mermaid_from_graph_json(Path(self.graph_plan_path))
        return self.graph_plan_path

    def amend_graph(
        self,
        amendment: str,
        graph_plan_path: Optional[str] = None,
        temperature: float = 0.35,
    ) -> str:
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")
        if not isinstance(amendment, str) or not amendment.strip():
            raise ValueError("amendment must be a non-empty string.")

        current_amendment = amendment
        max_audit_rounds = self._resolve_max_audit_rounds()
        for audit_round in range(1, max_audit_rounds + 1):
            self.planner.amend_file_with_feedback(
                self.graph_plan_path,
                current_amendment,
                temperature=temperature,
            )
            self.planned_graph = Graph(self.graph_plan_path)
            ok, violations = self.graph_auditor.audit_graph_json(self.planned_graph)
            if ok:
                self._logger.info("Graph amendment audit passed.")
                break
            current_amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            if audit_round >= max_audit_rounds:
                raise RuntimeError(
                    "graph amendment audit did not pass after "
                    f"{max_audit_rounds} attempt(s). Last feedback:\n{current_amendment}"
                )
            self._logger.warning("Graph amendment audit failed. Applying amendment...")

        self.planner._write_mermaid_from_graph_json(Path(self.graph_plan_path))
        return self.graph_plan_path

    def amend_workflow_json(
        self,
        user_prompt: str,
        workflow_json_path: Optional[str] = None,
        temperature: float = 0.35,
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
        )

    def generate_nodes(
        self,
        graph_plan_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        language: str = "python",
        temperature: float = 0.35,
    ) -> List[str]:
        """Generate code for every node in the planned graph.

        A separate :class:`PromptNodeFileCoder` instance is created for each
        node.  After the file has been written and audited we record the coder
        object and the final file location in two dictionaries on ``self`` so
        that later stages (testing, amendments, etc.) can look them up.

        Returns a list of all generated file paths as before.
        """
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
        self._logger.info("Generating per-node markdown plans -> %s", output_dir)
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
        del requirement_md_path, graph_plan_path, output_dirname, temperature
        raise self._node_ui_removed_error()

    def update_nodes_plan(
        self,
        graph_plan_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        node_docs_dirname: str = "node_docs",
        node_ui_dirname: str = "node_ui",
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
    ) -> Dict[str, Any]:
        del node_ui_dirname
        requirement_text = self._read_requirement_text(requirement_md_path)
        planned_graph = self._load_planned_graph(graph_plan_path)
        node_names = planned_graph.get_topological_sorted_nodes()

        node_docs_dir = self._resolve_root_path(node_docs_dirname)
        node_docs_dir.mkdir(parents=True, exist_ok=True)

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

        all_plan_map = {
            node_name: str(node_docs_dir / f"{node_name}.md")
            for node_name in node_names
            if (node_docs_dir / f"{node_name}.md").is_file()
        }

        self.node_docs_dir = str(node_docs_dir)
        self.node_doc_paths = [all_plan_map[node_name] for node_name in node_names if node_name in all_plan_map]

        self.dynamic_graph_cache["graph_nodes"] = node_names
        self.dynamic_graph_cache["graph_plan_path"] = str(Path(self.graph_plan_path).expanduser().resolve())
        self.dynamic_graph_cache["node_plans"] = all_plan_map
        self.dynamic_graph_cache["node_ui"] = {}

        return {
            "graph_plan_path": self.dynamic_graph_cache["graph_plan_path"],
            "node_plan": {
                "existing": existing_plan_map,
                "generated": generated_plan_map,
                "all": all_plan_map,
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

        missing_plan_names = [node_name for node_name in node_names if node_name not in plan_result["node_plan"]["all"]]
        if missing_plan_names:
            raise FileNotFoundError(
                "update_backend_nodes requires node plan artifacts before code generation. "
                f"missing node plan files for: {missing_plan_names}"
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
        max_frontend_audit_rounds: Optional[int] = None,
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
        resolved_context_dir = str(self._resolve_root_path(context_base_dir or self.root_dir))
        workflow_json_path = self._sync_workflow_graph_json(context_base_dir=resolved_context_dir)

        main_output_target = getattr(self, "main_output_path", os.path.join(self.root_dir, main_output_filename))
        main_output_path = self.generate_main_entrypoint(
            self.graph_plan_path,
            output_filename=str(main_output_target),
            temperature=temperature,
            fastapi_port=backend_port,
        )

        self.dynamic_graph_cache["frontend_nodes"] = {}
        self.dynamic_graph_cache["frontend_shared"] = {}

        return {
            "node_plan": backend_result["node_plan"],
            "backend_nodes": backend_result["backend_nodes"],
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

        artifact_state = self._validate_generated_artifacts(
            graph_plan_path=self.graph_plan_path,
            node_docs_dirname=node_docs_dirname,
            node_ui_dirname=node_ui_dirname,
            backend_language=backend_language,
            main_entrypoint_path=main_entrypoint_path,
        )

        main_path = Path(artifact_state["main_entrypoint"]).expanduser().resolve()

        self._stop_managed_server_process(self.backend_server_process)
        self._stop_managed_server_process(self.frontend_server_process)
        self.frontend_server_process = None

        python_cmd = select_python_command()
        backend_command = [python_cmd, str(main_path)]

        self.backend_server_process = subprocess.Popen(
            backend_command,
            cwd=str(main_path.parent),
            env=os.environ.copy(),
        )

        server_runtime = {
            "backend": {
                "pid": getattr(self.backend_server_process, "pid", None),
                "command": backend_command,
                "cwd": str(main_path.parent),
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
        del node_name, amendment, existing_html_path, requirement_md_path, graph_plan_path, output_path, temperature, max_tokens, overwrite
        raise self._node_ui_removed_error()

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

        self._logger.info("Amending node markdown '%s' -> %s", node_name, target_markdown_path)
        amended_graph_path, amended_doc_path = self.node_planner.amend_graph_node_from_files(
            node_name=node_name,
            user_prompt=amendment,
            requirement_md_path=self.requirement_md_path,
            graph_plan_json_path=self.graph_plan_path,
            node_output_path=target_markdown_path,
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
        return final_path

    def _build_steps_meta(self, include_hidden_nodes: bool = False) -> List[Dict[str, Any]]:
        del include_hidden_nodes
        raise self._frontend_removed_error()

    @classmethod
    def _resolve_frontend_violation_target(cls, frontend_src_dir: str | Path, violation: Any) -> Optional[Path]:
        del cls, frontend_src_dir, violation
        raise RuntimeError("Frontend auditing has been removed from meta_agent.")

    def generate_frontend(
        self,
        output_filename: str = "frontend",
        frontend_mode: str = "vue_src",
        temperature: float = 0.3,
        frontend_style_prompt: Optional[str] = None,
        context_base_dir: Optional[str] = None,
        max_audit_rounds: Optional[int] = None,
        backend_port: int = 8000,
    ) -> str:
        del output_filename, frontend_mode, temperature, frontend_style_prompt, context_base_dir, max_audit_rounds, backend_port
        raise self._frontend_removed_error()

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
            raise self._frontend_removed_error()

        if write_proxy_config:
            raise self._frontend_removed_error()

        generated_main_output_path: str | None = None
        if generate_main_entrypoint:
            self.main_output_path = os.path.join(self.root_dir, output_filename)
            self._logger.info("Generating main entrypoint -> %s", self.main_output_path)
            self.main_writer.write_main_entrypoint(
                project_root_path=self.root_dir,
                graph_plan_json_path=graph_plan_path or "",
                output_path=self.main_output_path,
                requirement_analysis_result=self.requirement_analysis_result,
                fastapi_host=fastapi_host,
                fastapi_port=fastapi_port,
                temperature=temperature,
            )

            max_audit_rounds = self._resolve_max_audit_rounds()
            for audit_round in range(1, max_audit_rounds + 1):
                ok, violations = self.main_entry_auditor.audit_main_entrypoint_file(
                    str(self.main_output_path),
                    str(self.root_dir),
                )
                if ok:
                    self._logger.info("Main entrypoint audit passed.")
                    break
                amendment = "\n".join(
                    [f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations]
                )
                if audit_round >= max_audit_rounds:
                    raise RuntimeError(
                        "main entrypoint audit did not pass after "
                        f"{max_audit_rounds} attempt(s). Last feedback:\n{amendment}"
                    )
                self._logger.warning(amendment)
                self._logger.warning("Main entrypoint audit failed. Applying amendment...")
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
        del frontend_project_dir, backend_port
        raise self._frontend_removed_error()

    def _write_vue_proxy_config(self, frontend_dir: Path, backend_port: int = 8000) -> None:
        del frontend_dir, backend_port
        raise self._frontend_removed_error()

    def generate_frontend_views(
        self,
        graph_plan_path: Optional[str] = None,
        output_base_dir: str = "frontend/src",
        context_base_dir: Optional[str] = None,
        temperature: float = 0.3,
    ) -> Dict[str, Dict[str, str]]:
        del graph_plan_path, output_base_dir, context_base_dir, temperature
        raise self._frontend_removed_error()

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

        self._logger.info("Test log written to: %s", self.log_path)
        self._logger.debug("Main entrypoint test log generated for %s", abs_path)

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
                        coder = PromptNodeFileCoderBase(
                            api_key=self.api_key,
                            model=self.model,
                            provider=self.provider,
                            session_marking_prompt=self.session_marking_prompt,
                        )
                        if hasattr(self, 'node_location_map'):
                            for node_file_location in self.node_location_map.values():
                                if os.path.basename(node_file_location) == os.path.basename(fname):
                                    target_path = node_file_location
                                    break

                try:
                    self._logger.warning("Applying amendment to %s: %s", fname, detail)
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
                    self._logger.error("Failed to amend %s: %s", fname, e, exc_info=True)
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
        """Run full build pipeline and generate backend workflow deliverables.

        Args:
            requirement_text: Raw requirement text to analyze.
            requirement_file: Path to an existing requirement file (takes precedence).
            test_after_generation: Whether to test generated main.py after generation.
            generate_node_docs: Whether to generate per-node markdown planning docs.
            generate_node_html: Reserved for backward compatibility; ignored.
            frontend_mode: Reserved for backward compatibility; ignored.
            frontend_style_prompt: Reserved for backward compatibility; ignored.
            context_base_dir: Optional base directory for syncing workflow.json.
            backend_port: Backend API port used by the generated FastAPI app.
        """
        total_steps = 4
        if generate_node_docs:
            total_steps += 1
        if test_after_generation:
            total_steps += 1
        self._start_progress(total_steps=total_steps)

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

        self._logger.info("Starting node generation and audit...")
        self.generate_nodes(language="python", temperature=0.0)
        self._logger.info("All nodes generated and audited successfully.")
        self._advance_progress("Node files generated and audited")

        self._logger.info("Generating main entrypoint...")
        main_entrypoint_path = self.generate_main_entrypoint(
            self.graph_plan_path,
            output_filename="main.py",
            temperature=0.0,
        )
        self._advance_progress("main.py generated and audited")

        if test_after_generation:
            self._logger.info("Testing main.py...")
            max_audit_rounds = self._resolve_max_audit_rounds()
            for audit_round in range(1, max_audit_rounds + 1):
                finished = self.test_main_entrypoint(
                    main_entrypoint_path,
                    log_filename="test_log.txt",
                    graph_plan_path=self.graph_plan_path,
                )
                if finished:
                    self._logger.info("run sim tests all passed!")
                    break
                if audit_round >= max_audit_rounds:
                    raise RuntimeError(
                        "main.py test/amendment loop did not pass after "
                        f"{max_audit_rounds} attempt(s)."
                    )
                self._logger.warning("Amendments applied based on test log. Retesting...")
            self._advance_progress("main.py test and amendment loop completed")

        self._logger.info("Build outputs:")
        self._logger.info("- graph_plan_path.json: %s", self.graph_plan_path)
        if generate_node_docs:
            self._logger.info("- node_docs/: %s", getattr(self, "node_docs_dir", ""))
        self._logger.info("- main.py: %s", self.main_output_path)


from typing import Optional, List, Dict, Any, Mapping
import os
import subprocess
import json
from datetime import datetime
from pathlib import Path

from pydaograph import CStatus, GElement, GPipeline

from meta_agent.architect import GraphPlanner, NodePlanner, Graph
from meta_agent.auditor import GraphJsonAuditor, NodeAuditor, MainEntryPointAuditor, OutputAuditor, FrontendAuditor
from meta_agent.worker.main_writer import PromptMainFileCoder
from meta_agent.worker.node_writer import (
    PromptNodeFileCoderBase,
    WorkflowOperationNodeCoder,
    WorkflowServiceNodeCoder,
    WorkflowSkillNodeCoder,
    WorkflowChatNodeCoder,
    WorkflowFileNodeCoder,
    WorkflowImageNodeCoder,
    WorkflowStepNodeCoder,
    is_none_ext_data,
    is_service_ext_data,
    is_skill_ext_data,
    is_chat_ext_data,
    is_file_ext_data,
    is_image_ext_data,
)
from meta_agent.worker.frontend_writer import PromptFrontendCoder
from meta_agent.demand_analyzer import RequirementDisector

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

            self.builder.node_location_map[self.node_name] = file_path

            return CStatus()
        except Exception as exc:
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
        self.graph_plan_path: Optional[str] = None

        self.analyzer = RequirementDisector(api_key=self.api_key, model=self.model, provider=self.provider)

        # initialize a shared GraphPlanner and auditors for later validation steps
        self.planner = GraphPlanner(
            api_key=self.api_key,
            model=self.model,
            provider=self.provider,
            services_root_path=self.services_root_path,
            skills_root_path=self.skills_root_path,
        )
        self.node_planner = NodePlanner(api_key=self.api_key, model=self.model, provider=self.provider)
        self.main_writer = PromptMainFileCoder(api_key=self.api_key, model=self.model, provider=self.provider)
        self.frontend_writer = PromptFrontendCoder(api_key=self.api_key, model=self.model, provider=self.provider)
        # initialize auditors for later validation steps
        self.graph_auditor = GraphJsonAuditor()
        self.node_auditor = NodeAuditor()
        self.main_entry_auditor = MainEntryPointAuditor()
        self.frontend_auditor = FrontendAuditor()
        # output auditor will inspect test logs and help trigger amendments
        self.output_auditor = OutputAuditor()

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
        if is_chat_ext_data(ext_data):
            return WorkflowChatNodeCoder(
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
        if is_image_ext_data(ext_data):
            return WorkflowImageNodeCoder(
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

    def _set_services_root_path(self, services_root: Optional[str]) -> None:
        if services_root is None:
            return
        self.services_root_path = str(services_root).strip()
        self.planner.services_root_path = self.services_root_path

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
            return requirement_file

        out_path = os.path.join(self.root_dir, out_file)
        print(f"Analyzing requirement -> {out_path}")
        self.analyzer.code_to_file(requirement_text or "", out_path)
        self.requirement_md_path = out_path
        return out_path

    def plan_graph(
        self,
        requirement_md_path: Optional[str] = None,
        graph_plan_filename: str = "graph_plan.json",
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
        if graph_plan_path:
            self.graph_plan_path = graph_plan_path
        if requirement_md_path:
            self.requirement_md_path = requirement_md_path
        if not self.graph_plan_path:
            raise ValueError("graph_plan_path is not set. Call plan_graph(...) first or pass graph_plan_path.")
        if not self.requirement_md_path:
            raise ValueError("requirement_md_path is not set. Call analyze_requirement(...) first or pass requirement_md_path.")

        # ensure we start with fresh mappings each time
        self.node_coder_map = {}
        self.node_location_map = {}

        nodes = self.planned_graph.get_topological_sorted_nodes()
        total = len(nodes)
        pipeline = GPipeline()

        

        elements: Dict[str, _NodeGenerateElement] = {}
        for index, name in enumerate(nodes, start=1):
            elements[name] = _NodeGenerateElement(self, name, total, index, language=language, temperature=temperature)

        for name in nodes:
            node_meta = self.planned_graph.get_node_meta(name)
            depends = set()
            if node_meta and node_meta.depends:
                depends = {elements[dep] for dep in node_meta.depends if dep in elements}
            status = pipeline.registerGElement(elements[name], depends, name, 1)
            if status.isErr():
                raise RuntimeError(f"registerGElement failed for {name}: {status.getInfo()}")

        process_status = pipeline.process()
        if process_status.isErr():
            raise RuntimeError(f"generate_nodes pipeline.process failed: {process_status.getInfo()}")

        return [self.node_location_map[name] for name in nodes if name in self.node_location_map]

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

    def amend_node_ui(
        self,
        node_name: str,
        amendment: str,
        existing_html_path: Optional[str] = None,
        requirement_md_path: Optional[str] = None,
        graph_plan_path: Optional[str] = None,
        output_path: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 12000,
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

    def _build_steps_meta(self) -> List[Dict[str, Any]]:
        """Build step metadata for frontend generation from planned graph."""
        steps_meta: List[Dict[str, Any]] = []
        for node_name in self.planned_graph.get_topological_sorted_nodes():
            node_meta = self.planned_graph.get_node_meta(node_name)
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

            input_required = ext_type in {"user_input", "user_file_input", "chat_input"}
            if ext_type == "chat_input":
                node_kind = "chat"
            elif ext_type == "user_file_input":
                node_kind = "file"
            elif ext_type == "image":
                node_kind = "image"
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
                        "inputs_format": normalized_inputs_format if ext_type in ("user_input", "chat_input", "skill") else {},
                    },
                }
            )
        return steps_meta

    def generate_frontend(
        self,
        output_filename: str = "frontend.html",
        temperature: float = 0.3,
        frontend_style_prompt: Optional[str] = None,
        context_base_dir: Optional[str] = None,
        run_all_cron_endpoint: Optional[str] = "/api/run-all-cron",
    ) -> str:
        """Generate and audit frontend.html."""
        frontend_path = os.path.join(self.root_dir, output_filename)
        print(f"Generating frontend -> {frontend_path}")
        steps_meta = self._build_steps_meta()

        effective_style_prompt = frontend_style_prompt
        if effective_style_prompt is None:
            effective_style_prompt = self.frontend_style_prompt
        if isinstance(effective_style_prompt, str):
            effective_style_prompt = effective_style_prompt.strip() or None

        self.frontend_writer.write_frontend_html(
            steps_meta=steps_meta,
            output_path=frontend_path,
            context_base_dir=context_base_dir,
            run_step_endpoint="/api/run-step",
            run_all_cron_endpoint=run_all_cron_endpoint,
            reset_session_endpoint="/api/reset-session",
            frontend_style_prompt=effective_style_prompt,
            overwrite=True,
            temperature=temperature,
        )

        while True:
            ok, violations = self.frontend_auditor.audit_frontend_file(frontend_path)
            if ok:
                print("frontend.html audit passed.")
                break
            amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            print("frontend.html audit failed. Applying amendment...")
            self.frontend_writer._amend_frontend_with_feedback(frontend_path, amendment, temperature=max(0.2, temperature))

        self.frontend_output_path = frontend_path
        return frontend_path

    def generate_main_entrypoint(
        self,
        graph_plan_path: str,
        output_filename: str = "main.py",
        fastapi_host: str = "0.0.0.0",
        temperature: float = 0.0,
        crontab_expression: Optional[str] = None,
    ) -> str:
        self.main_output_path = os.path.join(self.root_dir, output_filename)
        print(f"Generating main entrypoint -> {self.main_output_path}")
        self.main_writer.write_main_entrypoint(
            project_root_path=self.root_dir,
            graph_plan_json_path=graph_plan_path,
            output_path=self.main_output_path,
            fastapi_host=fastapi_host,
            crontab_expression=crontab_expression,
            temperature=temperature,
        )

        while True:
            ok, violations = self.main_entry_auditor.audit_main_entrypoint_file(str(self.main_output_path), str(self.root_dir))
            if ok:
                print("Main entrypoint audit passed.")
                break
            amendment = "\n".join([f"Line {v.lineno}: {v.rule} - {v.detail}" for v in violations])
            print(amendment)
            print("Main entrypoint audit failed. Applying amendment...")
            self.main_writer.amend_code_with_feedback(self.main_output_path, amendment, language="python", temperature=0.2)

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
        frontend_style_prompt: Optional[str] = None,
        context_base_dir: Optional[str] = None,
        crontab_expression: Optional[str] = None,
        run_all_cron_endpoint: Optional[str] = "/api/run-all-cron",
    ) -> None:
        """Run full build pipeline and generate AG-UI deliverables.

        Args:
            requirement_text: Raw requirement text to analyze.
            requirement_file: Path to an existing requirement file (takes precedence).
            test_after_generation: Whether to test generated main.py after generation.
            generate_node_docs: Whether to generate per-node markdown planning docs.
            generate_node_html: Whether to generate per-node HTML interaction files for node writing context.
            frontend_style_prompt: Optional style guidance for generated frontend.html.
            context_base_dir: Optional base directory for loading graph_plan.json and node_ui/*.html used as frontend generation context.
            crontab_expression: Optional cron expression; when set, generated main.py should include /api/run-all-cron using this preset schedule.
            run_all_cron_endpoint: Optional frontend endpoint path for cron streaming; pass None to disable cron controls in generated frontend.
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

        self.graph_plan_path = self.plan_graph(req_path, graph_plan_filename="graph_plan.json")
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
        effective_run_all_cron_endpoint = run_all_cron_endpoint if crontab_expression is not None else None
        self.generate_frontend(
            output_filename="frontend.html",
            temperature=0.0,
            frontend_style_prompt=self.frontend_style_prompt,
            context_base_dir=context_base_dir,
            run_all_cron_endpoint=effective_run_all_cron_endpoint,
        )
        self._advance_progress("frontend.html generated and audited")

        print("Generating main entrypoint...")
        main_entrypoint_path = self.generate_main_entrypoint(
            self.graph_plan_path,
            output_filename="main.py",
            temperature=0.0,
            crontab_expression=crontab_expression,
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
        print(f"- frontend.html: {self.frontend_output_path}")
        print(f"- main.py: {self.main_output_path}")


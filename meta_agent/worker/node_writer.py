import json
import ast
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from meta_agent._paths import bootstrap_package_root


ROOT_DIR = bootstrap_package_root(__file__)

from meta_agent.llm_client.coder import Coder, MAX_TOKENS
from meta_agent.context_builder.context import Context, GraphContextBuilder
from meta_agent.architect.graph import Graph, NodeMeta
from meta_agent.tools.file_tools import compile_node_file_and_get_derived_keys


def grep_ext_data(node_spec: Mapping) -> Any:
    """
    Extract and return ext_data from node specification.
    
    Args:
        node_spec: A mapping containing node metadata including optional ext_data
        
    Returns:
        Any: The ext_data value if present, otherwise empty string
    """
    if not isinstance(node_spec, Mapping):
        return ""
    return node_spec.get("ext_data", "")


def is_none_ext_data(ext_data: Any) -> bool:
    """Return True when ext_data indicates no external input/source is needed."""
    if isinstance(ext_data, Mapping):
        ext_type = str(ext_data.get("type", "")).strip().lower()
        return ext_type == "none"
    if isinstance(ext_data, str):
        return ext_data.strip().lower() == "none"
    return False

def is_file_ext_data(ext_data: Any) -> bool:
    """Return True when ext_data indicates generic file upload input is needed."""
    if isinstance(ext_data, Mapping):
        ext_type = str(ext_data.get("type", "")).strip().lower()
        return ext_type == "user_file_input"
    if isinstance(ext_data, str):
        return ext_data.strip().lower() == "user_file_input"
    return False


def is_service_ext_data(ext_data: Any) -> bool:
    """Return True when ext_data indicates service bootstrap from service.md."""
    if isinstance(ext_data, Mapping):
        ext_type = str(ext_data.get("type", "")).strip().lower()
        service_name = str(ext_data.get("service_name", "")).strip()
        return ext_type == "service" or bool(service_name)
    if isinstance(ext_data, str):
        return ext_data.strip().lower() == "service"
    return False


def is_skill_ext_data(ext_data: Any) -> bool:
    """Return True when ext_data indicates a WorkflowSkillNode driven by skill.md."""
    if isinstance(ext_data, Mapping):
        ext_type = str(ext_data.get("type", "")).strip().lower()
        skill_name = str(ext_data.get("skill_name", "")).strip()
        return ext_type == "skill" or bool(skill_name)
    if isinstance(ext_data, str):
        return ext_data.strip().lower() == "skill"
    return False


def _build_dependency_derived_context(node_dir: Path, dependency_names: list[str]) -> str:
    if not dependency_names:
        return ""

    lines: list[str] = []
    for dep_name in dependency_names:
        dep_file = node_dir / f"{dep_name}.py"
        if not dep_file.is_file():
            continue

        derived_keys = compile_node_file_and_get_derived_keys(str(dep_file))
        if derived_keys:
            lines.append(f"- {dep_name}:")
            for key in derived_keys:
                lines.append(f"  - dependency_results['{dep_name}'].derived['{key}']")
        else:
            lines.append(f"- {dep_name}: (no derived keys detected)")

    return "\n".join(lines)


def _build_ancestor_session_state_context(graph_plan_path: str, node_name: str) -> str:
    if not graph_plan_path or not node_name:
        return ""

    try:
        graph = Graph(graph_plan_path)
        session_state_keys = graph.get_ancestor_session_state_keys(node_name)
    except Exception:
        return ""

    if not session_state_keys:
        return ""

    return f"- {node_name}: {', '.join(session_state_keys)}"


def _extract_declared_dependencies_from_code(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "DEPENDENCIES":
                    if isinstance(stmt.value, (ast.List, ast.Tuple)):
                        dependencies: list[str] = []
                        for item in stmt.value.elts:
                            if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.strip():
                                dependencies.append(item.value)
                        return dependencies
    return []


def _read_node_markdown_reference(
    node_name: str,
    requirement_md_path: Path,
    output_path: Path,
) -> str:
    # Read generated node markdown reference if available.

    # Search order (first existing file is used):
    # 1) <project_root>/node_docs/<node_name>.md
    # 2) <project_root>/<node_name>.md
    # 3) <output_parent>/node_docs/<node_name>.md
    

    filename = f"{node_name}.md"
    requirement_dir = requirement_md_path.resolve().parent
    output_parent = output_path.resolve().parent

    candidates = [
        requirement_dir / "node_docs" / filename,
        requirement_dir / filename,
        output_parent / "node_docs" / filename,
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return ""


def _read_node_html_reference(
    node_name: str,
    output_or_code_path: Path,
    *,
    requirement_md_path: Path | None = None,
    root_dir_path: str = "",
) -> str:
    # Read generated node HTML reference if available.

    # Search order (first existing file is used):
    # 1) <requirement_dir>/node_ui/<node_name>.html
    # 2) <requirement_dir>/node_html/<node_name>.html
    # 3) <requirement_dir>/<node_name>.html
    # 4) <output_parent>/node_ui/<node_name>.html
    # 5) <output_parent>/node_html/<node_name>.html
    # 6) <output_parent>/<node_name>.html
    # 7) <root_dir>/node_ui/<node_name>.html
    # 8) <root_dir>/node_html/<node_name>.html

    filename = f"{node_name}.html"
    output_parent = output_or_code_path.expanduser().resolve().parent

    candidates: list[Path] = []

    if requirement_md_path:
        requirement_dir = requirement_md_path.expanduser().resolve().parent
        candidates.extend(
            [
                requirement_dir / "node_ui" / filename,
                requirement_dir / "node_html" / filename,
                requirement_dir / filename,
            ]
        )

    candidates.extend(
        [
            output_parent / "node_ui" / filename,
            output_parent / "node_html" / filename,
            output_parent / filename,
        ]
    )

    if root_dir_path:
        root_dir = Path(root_dir_path).expanduser().resolve()
        candidates.extend(
            [
                root_dir / "node_ui" / filename,
                root_dir / "node_html" / filename,
            ]
        )

    visited: set[Path] = set()
    for candidate in candidates:
        if candidate in visited:
            continue
        visited.add(candidate)
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return ""


def _resolve_named_root(
    configured_root_path: str,
    root_dir_path: str,
    default_dirname: str,
) -> Path:
    if configured_root_path:
        configured = Path(configured_root_path).expanduser().resolve()
        if configured.is_dir():
            return configured

    if root_dir_path:
        root_dir = Path(root_dir_path).expanduser().resolve()
        direct = root_dir / default_dirname
        if direct.is_dir():
            return direct
        parent = root_dir.parent / default_dirname
        if parent.is_dir():
            return parent

    return ROOT_DIR.parent / default_dirname


def _read_named_markdown(root_dir: Path, item_name: str, markdown_name: str) -> str:
    if not item_name:
        return ""

    doc_path = root_dir / item_name / markdown_name
    if not doc_path.is_file():
        return ""
    return doc_path.read_text(encoding="utf-8").strip()


def _parse_markdown_sections(markdown_text: str) -> dict[str, str]:
    if not markdown_text.strip():
        return {}

    try:
        from meta_agent.tools.file_tools import parse_skill_md

        parsed = parse_skill_md(markdown_text)
    except Exception:
        return {}

    return {str(key).strip(): str(value).strip() for key, value in parsed.items()}
    

@dataclass
class PromptNodeFileCoderBase(Coder):
    prompt_path: str = "worker/prompts/pydaograph_node_prompt.md"
    reference_excerpt_path: str = "library/workflow_nodes_reference_excerpts.md"
    root_dir_path: str = ""
    context_text: str = ""
    ancestor_session_state_context_text: str = ""
    reference_excerpt_text: str = ""

    def __post_init__(self) -> None:
        prompt_file = ROOT_DIR / self.prompt_path
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        reference_file = ROOT_DIR / self.reference_excerpt_path
        if not reference_file.exists():
            raise FileNotFoundError(f"Reference excerpt file not found: {reference_file}")

        self.system_prompt = prompt_file.read_text(encoding="utf-8")
        self.reference_excerpt_text = reference_file.read_text(encoding="utf-8")
        super().__post_init__()

    @staticmethod
    def _language_extension(language: str) -> str:
        language_clean = language.strip().lower() if language else "python"
        ext_map = {
            "python": ".py",
            "py": ".py",
            "javascript": ".js",
            "js": ".js",
            "typescript": ".ts",
            "ts": ".ts",
            "java": ".java",
            "go": ".go",
            "golang": ".go",
            "csharp": ".cs",
            "c#": ".cs",
        }
        return ext_map.get(language_clean, f".{language_clean}" if language_clean else ".txt")

    @staticmethod
    def _format_ext_data(ext_data: Any) -> str:
        if not ext_data:
            return "none"
        if isinstance(ext_data, Mapping):
            return json.dumps(dict(ext_data), ensure_ascii=False)
        return str(ext_data)

    @staticmethod
    def _format_depends(depends: list[str] | None) -> str:
        return ", ".join(depends) if depends else "none"

    @staticmethod
    def _format_services(services: list[dict[str, str]] | None) -> str:
        if not services:
            return "none"
        normalized: list[dict[str, str]] = []
        for item in services:
            if not isinstance(item, Mapping):
                continue
            service_name = str(item.get("service_name", "")).strip()
            use_desc = str(item.get("use_desc", "")).strip()
            if not service_name:
                continue
            normalized.append({"service_name": service_name, "use_desc": use_desc})
        return json.dumps(normalized, ensure_ascii=False) if normalized else "none"

    @staticmethod
    def _format_inputs_format(inputs_format: Mapping[str, Any] | None) -> str:
        if not isinstance(inputs_format, Mapping) or not inputs_format:
            return "none"
        normalized: dict[str, str] = {}
        for key, value in inputs_format.items():
            field_name = str(key).strip()
            field_type = str(value).strip()
            if field_name and field_type:
                normalized[field_name] = field_type
        return json.dumps(normalized, ensure_ascii=False) if normalized else "none"

    @staticmethod
    def _has_default_config_audit_rule(amendment: str) -> bool:
        if not amendment:
            return False
        text = amendment.lower()
        return (
            "dependency_results_missing_dependency_keys" in text
            or "session_state_ancestor_key_invalid" in text
        )

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
        node_html_reference: str,
        output_path: str,
        graph_plan_path: str,
        language_clean: str,
        node_base_class: str,
        node_contract_text: str,
    ) -> str:
        depends_text = self._format_depends(node_meta.depends)
        ext_data_text = self._format_ext_data(node_meta.ext_data)
        services_text = self._format_services(node_meta.services)
        inputs_format_text = self._format_inputs_format(node_meta.inputs_format)

        minimal_policy_text = (
            "Minimal implementation policy (must follow):\n"
            "- Implement only requirement-critical behavior for this node; no extra features.\n"
            "- Keep structure flat and concise; avoid unnecessary helper functions/classes.\n"
            "- Prefer straightforward parsing/validation with simple guard clauses.\n"
            "- Every defined variable must be used; remove dead assignments.\n"
            "- Add detailed debug logging that writes to a local file path so node execution can be diagnosed after runs.\n"
            "- Keep the logging implementation simple and self-contained; prefer a module-local logger, FileHandler, and path creation via pathlib.\n"
            "- Do not add demo/example code, tests, or comments unless required.\n"
            "- Do not include TODO markers in generated code.\n\n"
        )

        state_routing_policy_text = (
            "State routing policy (authoritative):\n"
            "- If a value should be shared globally or reused across non-immediate downstream steps, store/update it in session_state.\n"
            "- If a value is only intended for downstream child-step passing, put it in StepRunOutput.derived.\n"
            "- Do not store child-step-only transit values in session_state unless long-lived/global reuse is explicitly required.\n"
            "- For values not found in session_state and dependency_results[dep].derived, apply safe fallback handling with explicit validation.\n"
            "- If a required value is still missing/invalid after fallback, return an explicit validation error.\n\n"
        )

        user_prompt = (
            "You are generating an AG-UI workflow step node for PyDaoGraph.\n"
            f"Node name: {node_name}\n"
            f"Type: {node_meta.type}\n"
            f"Description: {node_meta.desc}\n"
            f"Depends on: {depends_text}\n"
            f"External data: {ext_data_text}\n"
            f"User inputs format: {inputs_format_text}\n"
            f"Services usage: {services_text}\n"
            f"Expected base class: {node_base_class}\n"
            f"Target language: {language_clean}\n\n"
            f"{minimal_policy_text}"
            f"{state_routing_policy_text}"
            f"{node_contract_text}"
            "Requirement analysis that this node should satisfy:\n"
            f"{requirement_text}\n\n"
        )

        if not node_meta.show_frontend:
            user_prompt += (
                "Hidden frontend rule (authoritative):\n"
                "- node_meta.show_frontend is False for this node.\n"
                "- Define class constant INPUT_REQUIRED = False in the generated node class.\n"
                "- Treat this node as non-interactive from the frontend; do not require direct frontend user input.\n\n"
            )

        ext_data = node_meta.ext_data if isinstance(node_meta.ext_data, Mapping) else {}
        ext_type = str(ext_data.get("type", "none")).strip().lower()
        if ext_type in ("user_input", "skill") and inputs_format_text != "none":
            handler_map = {
                "user_input": ("user_input", "process_input"),
                "skill": ("process_operation", "process_skill / run"),
            }
            _, handler_fn = handler_map.get(ext_type, (ext_type, "process_input"))
            user_prompt += (
                "Input schema constraints (authoritative):\n"
                f"- This node is ext_data.type='{ext_type}' with explicit inputs_format.\n"
                f"- inputs_format: {inputs_format_text}\n"
                f"- In {handler_fn}, parse/validate user_input against this schema and produce structured derived fields using the same keys when reasonable.\n\n"
            )

        if self.reference_excerpt_text.strip():
            user_prompt += (
                "Reference implementation excerpts (aligned with workflow base classes):\n"
                f"{self.reference_excerpt_text}\n\n"
            )

        if node_markdown_reference:
            user_prompt += (
                "Node-specific markdown reference (authoritative for this node's implementation focus):\n"
                f"{node_markdown_reference}\n\n"
            )

        if node_html_reference:
            user_prompt += (
                "Node-specific HTML interaction reference (authoritative for user interaction expectations):\n"
                "- Use this as context for expected user-facing input/output shape and UI intent.\n"
                "- Keep node backend logic aligned with the referenced interaction model where applicable.\n"
                f"{node_html_reference}\n\n"
            )

        self.context_text = ""
        self.ancestor_session_state_context_text = ""

        dependency_context = _build_dependency_derived_context(
            node_dir=Path(output_path).expanduser().resolve().parent,
            dependency_names=list(node_meta.depends or []),
        )
        if dependency_context:
            user_prompt += (
                "\n\nDependency derived keys from existing dependency files "
                "(parsed via compile_node_file_and_get_derived_keys, authoritative):\n"
                f"{dependency_context}\n"
                "- Strict rule: any key read from dependency_results[dep].derived must come only from the keys listed in this dependency_context.\n"
                "- Never access or invent dependency derived keys outside this dependency_context.\n"
            )

        ancestor_session_state_context = _build_ancestor_session_state_context(
            graph_plan_path=graph_plan_path,
            node_name=node_name,
        )
        self.ancestor_session_state_context_text = ancestor_session_state_context
        if ancestor_session_state_context:
            user_prompt += (
                "\n\nAncestor session_state keys from node files "
                "(via get_ancestor_session_state_keys, authoritative):\n"
                f"{ancestor_session_state_context}\n"
                "- Strict rule: any key read/write in session_state must come only from this ancestor_session_state_context.\n"
                "- Never read/write or invent session_state keys outside this ancestor_session_state_context.\n"
                "- For missing allowed keys, use safe fallback handling and explicit validation errors when still unresolved.\n"
            )

        if graph_plan_path:
            context_builder = GraphContextBuilder(root_path=self.root_dir_path, language=language_clean)
            context_builder.search(current_node_name=node_name, graph_plan_path=graph_plan_path)

            context_text = context_builder.build(limit=5)
            self.context_text = context_text or ""
            if context_text:
                user_prompt += (
                    "\n\nDependency context from GraphContextBuilder (authoritative):\n"
                    "- Infer each dependency node's STEP_ID and available derived keys from this context.\n"
                    "- Prefer using the context node's derived key-values as the first-choice upstream fields.\n"
                    "- In process_input/process_operation, extract upstream variables from dependency_results using only those dependency STEP_IDs and derived keys.\n"
                    "- First resolve required values from dependency_results/session_state; if still unresolved, use safe fallback handling and then validate/fail clearly when still missing.\n"
                    "- Avoid guessed upstream field names; if a needed key is uncertain, use safe fallback handling without TODO markers.\n\n"
                    f"{context_text}"
                )

        if user_prompt.strip():
            user_prompt += (
                f"\n\nReturn only runnable {language_clean} code for this node."
                " Do not include markdown fences or explanation text."
            )

        return user_prompt

    def write_node_from_requirement(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_md_path: str,
        output_path: str,
        *,
        graph_plan_path: str = "",
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
    ) -> Path:
        requirement_path = Path(requirement_md_path)
        if not requirement_path.exists():
            raise FileNotFoundError(f"Requirement file not found: {requirement_path}")

        requirement_text = requirement_path.read_text(encoding="utf-8")
        node_markdown_reference = _read_node_markdown_reference(
            node_name=node_name,
            requirement_md_path=requirement_path,
            output_path=Path(output_path),
        )
        node_html_reference = _read_node_html_reference(
            node_name=node_name,
            output_or_code_path=Path(output_path),
            requirement_md_path=requirement_path,
            root_dir_path=self.root_dir_path,
        )

        language_clean = language.strip().lower() if language else "python"
        target_ext = self._language_extension(language_clean)

        user_prompt = self._build_requirement_prompt(
            node_name=node_name,
            node_meta=node_meta,
            requirement_text=requirement_text,
            node_markdown_reference=node_markdown_reference,
            node_html_reference=node_html_reference,
            output_path=output_path,
            graph_plan_path=graph_plan_path,
            language_clean=language_clean,
            node_base_class=self.node_base_class,
            node_contract_text=self.get_node_contract_text(),
        )

        target_path = Path(output_path)
        if target_path.suffix.lower() != target_ext:
            target_path = target_path.with_suffix(target_ext)

        return self.code_to_file(
            user_prompt,
            str(target_path),
            overwrite=overwrite,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _build_amendment_prompt(
        self,
        original_code: str,
        amendment: str,
        language_clean: str,
        contract_text: str,
    ) -> str:
        state_routing_policy_text = (
            "State routing policy (authoritative):\n"
            "- If a value should be shared globally or reused across non-immediate downstream steps, store/update it in session_state.\n"
            "- If a value is only intended for downstream child-step passing, put it in StepRunOutput.derived.\n"
            "- Do not store child-step-only transit values in session_state unless long-lived/global reuse is explicitly required.\n"
            "- If a required value is missing/invalid after resolution attempts, return an explicit validation error.\n\n"
        )

        user_prompt = (
            "You are updating an existing AG-UI workflow node implementation.\n"
            f"Target language: {language_clean}\n"
            "Keep the code as simple as possible while fully satisfying the amendment and node requirements.\n"
            "Avoid adding new abstractions unless they are strictly needed.\n"
            "Every defined variable must be used; remove dead assignments.\n"
            f"{state_routing_policy_text}"
            f"{contract_text}"
            "Apply the amendment or feedback to produce the improved code.\n"
            "Return only runnable code without commentary or markdown fences.\n\n"
            "Existing code:\n"
            f"{original_code}\n\n"
            "Amendment / feedback to apply:\n"
            f"{amendment}\n"
        )

        if self._has_default_config_audit_rule(amendment):
            user_prompt += (
                "\nAudit remediation rule (authoritative):\n"
                "- If audit reports dependency_results_missing_dependency_keys or session_state_ancestor_key_invalid, treat missing variables as potential config variables.\n"
                "- Add/ensure class-level DEFAULT_CONFIG = { ... } in the node file with placeholders for those missing keys.\n"
                "- If the value is still missing/invalid after resolution attempts, return an explicit validation error.\n"
            )

        return user_prompt

    def amend_code_with_feedback(
        self,
        code_path: str,
        amendment: str,
        *,
        graph_plan_path: str = "",
        requirement_md_path: str = "",
        current_node_name: str = "",
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.3,
        max_tokens: int = MAX_TOKENS,
    ) -> Path:
        language_clean = language.strip().lower() if language else "python"
        target_path = Path(code_path)
        inferred_node_name = current_node_name.strip() if current_node_name else target_path.stem
        target_ext = self._language_extension(language_clean)
        if target_path.suffix.lower() != target_ext:
            target_path = target_path.with_suffix(target_ext)

        if not target_path.exists():
            raise FileNotFoundError(f"Code file not found: {target_path}")

        original_code = target_path.read_text(encoding="utf-8")
        contract_text = self.get_feedback_contract_text()

        user_prompt = self._build_amendment_prompt(
            original_code=original_code,
            amendment=amendment,
            language_clean=language_clean,
            contract_text=contract_text,
        )

        requirement_path = Path(requirement_md_path).expanduser() if requirement_md_path else None
        if requirement_path and not requirement_path.exists():
            requirement_path = None
        node_html_reference = _read_node_html_reference(
            node_name=inferred_node_name,
            output_or_code_path=target_path,
            requirement_md_path=requirement_path,
            root_dir_path=self.root_dir_path,
        )
        if node_html_reference:
            user_prompt += (
                "\n\nNode-specific HTML interaction reference (authoritative for user interaction expectations):\n"
                "- Keep amendments consistent with this interaction context where applicable.\n"
                f"{node_html_reference}\n"
            )

        dependency_names = _extract_declared_dependencies_from_code(original_code)
        dependency_context = _build_dependency_derived_context(
            node_dir=target_path.parent.resolve(),
            dependency_names=dependency_names,
        )
        if dependency_context:
            user_prompt += (
                "\n\nDependency derived keys from existing dependency files "
                "(parsed via compile_node_file_and_get_derived_keys, authoritative):\n"
                f"{dependency_context}\n"
            )

        if graph_plan_path:
            context_builder = GraphContextBuilder(root_path=self.root_dir_path, language=language_clean)
            context_builder.search(current_node_name=inferred_node_name, graph_plan_path=graph_plan_path)
            self.context_text = context_builder.build(limit=5) or ""

        if self.context_text.strip():
            user_prompt += (
                "\n\nDependency context from GraphContextBuilder (authoritative):\n"
                "- Infer each dependency node's STEP_ID and available derived keys from this context.\n"
                "- Prefer using the context node's derived key-values as the first-choice upstream fields.\n"
                "- In process_input/process_operation, extract upstream variables from dependency_results using only those dependency STEP_IDs and derived keys.\n"
                "- Strict rule: node's get keys from derived must strictly come from dependency_context; do not access derived keys outside dependency_context.\n"
                "- First resolve required values from dependency_results/session_state; if still unresolved, use safe fallback handling and then validate/fail clearly when still missing.\n"
                "- Avoid guessed upstream field names; if a needed key is uncertain, use safe fallback handling without TODO markers.\n\n"
                f"{self.context_text}\n"
            )

        if graph_plan_path:
            self.ancestor_session_state_context_text = _build_ancestor_session_state_context(
                graph_plan_path=graph_plan_path,
                node_name=inferred_node_name,
            )

        if self.ancestor_session_state_context_text.strip():
            user_prompt += (
                "\n\nAncestor session_state keys from node files "
                "(via get_ancestor_session_state_keys, authoritative):\n"
                f"{self.ancestor_session_state_context_text}\n"
                "- Strict rule: node's get keys from session_state must strictly come from ancestor_session_state_context.\n"
                "- Never read/write session_state keys outside ancestor_session_state_context unless amendment explicitly adds and justifies a new key.\n"
            )

        return self.code_to_file(
            user_prompt,
            str(target_path),
            overwrite=overwrite,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def get_node_contract_text(self) -> str:
        raise NotImplementedError

    def get_feedback_contract_text(self) -> str:
        raise NotImplementedError


@dataclass
class WorkflowOperationNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowOperationNode"

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowOperationNode subclass with STEP_ID, TITLE, PROMPT, DEPENDENCIES, and SERVICES.\n"
            "Implement business logic in process_operation(dependency_results, session_state) and return StepRunOutput.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Set class constant SERVICES from node metadata services exactly (service_name/use_desc entries).\n"
            "If SERVICES is non-empty, call self.use_service(session_state) in process_operation before service-dependent logic.\n"
            "If process_operation needs direct service status/record lookup in addition to self.use_service, import workflow_service_registry from ag_ui_workflow.services and use it.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state.\n"
            "When a required variable is absent in both dependency_results[step_id].derived and session_state, use safe fallback handling before returning explicit validation errors.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "Do not require user input for this node.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowOperationNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES/SERVICES and process_operation returning StepRunOutput). "
            "If SERVICES is non-empty, keep/restore self.use_service(session_state) before service-dependent logic and import workflow_service_registry only when direct registry access is needed.\n"
        )


@dataclass
class WorkflowFileNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowFileNode"

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
        node_html_reference: str,
        output_path: str,
        graph_plan_path: str,
        language_clean: str,
        node_base_class: str,
        node_contract_text: str,
    ) -> str:
        base_prompt = super()._build_requirement_prompt(
            node_name=node_name,
            node_meta=node_meta,
            requirement_text=requirement_text,
            node_markdown_reference=node_markdown_reference,
            node_html_reference=node_html_reference,
            output_path=output_path,
            graph_plan_path=graph_plan_path,
            language_clean=language_clean,
            node_base_class=node_base_class,
            node_contract_text=node_contract_text,
        )

        ext_data = node_meta.ext_data if isinstance(node_meta.ext_data, Mapping) else {}
        remote_desc = ""
        if isinstance(ext_data, Mapping):
            remote_desc = str(ext_data.get("remote_desc", "")).strip()

        if not remote_desc:
            return (
                base_prompt
                + "\n\nWorkflowFileNode generation rule (authoritative):\n"
                + "- Do not implement any custom methods.\n"
                + "- Rely on WorkflowFileNode base implementation for save_files/save_files_remote/build_step_output.\n"
                + "- Only define required class constants (STEP_ID, TITLE, PROMPT, DEPENDENCIES).\n"
            )

        return (
            base_prompt
            + "\n\nWorkflowFileNode remote persistence rule (authoritative):\n"
            + "- ext_data.remote_desc is provided; implement save_files_remote(files, session_state) based on it.\n"
            + f"- remote_desc: {remote_desc}\n"
            + "- Do not modify or override other base persistence/output methods unless strictly required by remote_desc.\n"
        )

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowFileNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "By default, do not implement any custom methods; rely on WorkflowFileNode base behavior.\n"
            "Only when ext_data.remote_desc is present, implement save_files_remote(files, session_state) according to remote_desc.\n"
            "saved_files contains uploaded files already persisted by WorkflowFileNode save_files/save_files_remote, including original fileName(fileName) and saved location(path).\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "Ensure this node expects user file input and supports multiple uploaded files.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowFileNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES). "
            "Default to no custom methods; only override save_files_remote(files, session_state) when remote storage behavior is explicitly required (e.g., ext_data.remote_desc).\n"
        )
@dataclass
class WorkflowStepNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowStepNode"

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowStepNode subclass with STEP_ID, TITLE, PROMPT, DEPENDENCIES, and SERVICES.\n"
            "Implement business logic in process_input(user_input, dependency_results, session_state) and return StepRunOutput.\n"
            "If node metadata includes inputs_format, parse/validate user_input according to that schema (field names + primitive types).\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Set class constant SERVICES from node metadata services exactly (service_name/use_desc entries).\n"
            "If SERVICES is non-empty, call self.use_service(session_state) in process_input before service-dependent logic.\n"
            "If process_input needs direct service status/record lookup in addition to self.use_service, import workflow_service_registry from ag_ui_workflow.services and use it.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state.\n"
            "When a required variable is absent in both dependency_results[step_id].derived and session_state, use safe fallback handling before returning explicit validation errors.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowStepNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES/SERVICES and process_input returning StepRunOutput). "
            "If SERVICES is non-empty, keep/restore self.use_service(session_state) before service-dependent logic and import workflow_service_registry only when direct registry access is needed.\n"
        )


@dataclass
class WorkflowServiceNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowServiceNode"
    default_services_dirname: str = "agent_services"
    services_root_path: str = ""

    def _default_services_root(self) -> Path:
        return _resolve_named_root(
            configured_root_path=self.services_root_path,
            root_dir_path=self.root_dir_path,
            default_dirname=self.default_services_dirname,
        )

    def _extract_service_name(self, node_meta: NodeMeta) -> str:
        ext_data = node_meta.ext_data
        if isinstance(ext_data, Mapping):
            return str(ext_data.get("service_name", "")).strip()
        return ""

    def _current_os_label(self) -> str:
        system = platform.system().strip().lower()
        if system == "darwin":
            return "macOS"
        if system == "windows":
            return "Windows"
        if system == "linux":
            return "Linux"
        return platform.system().strip() or "unknown"

    def _list_available_services(self, services_root: Path) -> list[str]:
        if not services_root.is_dir():
            return []
        return sorted(
            child.name
            for child in services_root.iterdir()
            if child.is_dir()
        )

    def _read_service_markdown(self, services_root: Path, service_name: str) -> str:
        return _read_named_markdown(services_root, service_name, "service.md")

    def _extract_service_sections(self, service_markdown: str) -> tuple[str, str]:
        """Return (installation_section, start_service_section) from a parsed service.md.

        Sections are matched by H2 headings that start with '1.' or '2.' respectively.
        """
        sections = _parse_markdown_sections(service_markdown)
        # Match sections by numeric prefix to tolerate slight heading variants.
        installation = ""
        start_service = ""
        for key, value in sections.items():
            key_stripped = key.strip()
            if key_stripped.startswith("1. Installation"):
                installation = value.strip()
            elif key_stripped.startswith("2. Start Service"):
                start_service = value.strip()
        return installation, start_service

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
        node_html_reference: str,
        output_path: str,
        graph_plan_path: str,
        language_clean: str,
        node_base_class: str,
        node_contract_text: str,
    ) -> str:
        base_prompt = super()._build_requirement_prompt(
            node_name=node_name,
            node_meta=node_meta,
            requirement_text=requirement_text,
            node_markdown_reference=node_markdown_reference,
            node_html_reference=node_html_reference,
            output_path=output_path,
            graph_plan_path=graph_plan_path,
            language_clean=language_clean,
            node_base_class=node_base_class,
            node_contract_text=node_contract_text,
        )

        services_root = self._default_services_root()
        available_services = self._list_available_services(services_root)
        service_name = self._extract_service_name(node_meta)
        service_doc_text = self._read_service_markdown(services_root, service_name)
        installation_section, start_section = self._extract_service_sections(service_doc_text)
        current_os = self._current_os_label()

        service_context_lines = [
            "",
            "Service selection context (authoritative):",
            f"- services_root: {services_root}",
            f"- available_services: {', '.join(available_services) if available_services else 'none'}",
            f"- selected_service_name: {service_name or 'none'}",
            f"- current_operating_system: {current_os}",
        ]

        if service_doc_text:
            service_context_lines.extend(
                [
                    "",
                    "Full service run guide (service.md) for reference:",
                    service_doc_text,
                ]
            )

        if installation_section:
            service_context_lines.extend(
                [
                    "",
                    "service.md ## 1. Installation section (authoritative — implement this in install_environment):",
                    installation_section,
                ]
            )

        if start_section:
            service_context_lines.extend(
                [
                    "",
                    "service.md ## 2. Start Service section (authoritative — implement this in start_service):",
                    start_section,
                ]
            )

        service_context_lines.extend(
            [
                "",
                "Implementation constraints for this service node:",
                "- Subclass WorkflowServiceNode.",
                "- Import workflow_service_registry from ag_ui_workflow.services.",
                "- Implement install_environment(dependency_results, session_state) -> bool based on the ## 1. Installation section.",
                "- Implement start_service(dependency_results, session_state) -> int based on the ## 2. Start Service section; return the PID of the launched process (use subprocess.Popen and return proc.pid).",
                "- In start_service, after successful launch, call workflow_service_registry.update_service_status(..., status='running', is_running=True, pid=proc.pid, installed=True).",
                "- Do not override process_operation; the base class orchestrates install + start automatically.",
                "- Use DEFAULT_WORKDIR or session_state.get('serviceWorkdir') as working directory; do not hardcode absolute paths.",
                "- Command sequence must be compatible with current_operating_system. Prefer the OS-specific variant when service.md lists multiple variants.",
                "- Keep output JSON-serializable and include useful derived fields for downstream nodes.",
            ]
        )

        if not service_doc_text:
            service_context_lines.extend(
                [
                    "",
                    "No service.md found for selected service_name.",
                    "- Fall back to minimal safe stub implementations for install/start phases.",
                    "- install_environment: return True after a no-op check.",
                    "- start_service: launch a placeholder process and return its pid.",
                    "- In start_service, mark workflow_service_registry running state after launch.",
                    "- Do not invent unavailable service details.",
                ]
            )

        return base_prompt + "\n" + "\n".join(service_context_lines)

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowServiceNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Import workflow_service_registry from ag_ui_workflow.services.\n"
            "Implement the two-phase execution pattern by overriding these methods:\n"
            "\n"
            "Phase 1 — install_environment(self, dependency_results, session_state) -> bool:\n"
            "  Implement based on service.md ## 1. Installation section.\n"
            "  Run install commands (e.g. git clone, uv sync, pip install) using subprocess.run or equivalent.\n"
            "  Return True if installation succeeded, False otherwise.\n"
            "  Skip work if it was already done (e.g. check if directory/venv exists before cloning/installing).\n"
            "\n"
            "Phase 2 — start_service(self, dependency_results, session_state) -> int:\n"
            "  Implement based on service.md ## 2. Start Service section.\n"
            "  Launch the service as a background process using subprocess.Popen.\n"
            "  Return the integer PID of the launched process (proc.pid); <= 0 signals failure.\n"
            "  After successful launch, mark service running in workflow_service_registry via update_service_status(...).\n"
            "  The working directory should be session_state.get('serviceWorkdir') or self.DEFAULT_WORKDIR.\n"
            "  If a custom default workdir is required, define class constant DEFAULT_WORKDIR in the generated node.\n"
            "  The generated command must be valid for the current operating system context.\n"
            "\n"
            "Do NOT override process_operation — the base class calls install + start automatically.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state when needed.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "This node should not require direct user input.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowServiceNode two-phase contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES and install_environment returning bool, "
            "start_service returning int PID; start_service must update workflow_service_registry running state).\n"
            "Do NOT override process_operation.\n"
        )


@dataclass
class WorkflowSkillNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowSkillNode"
    default_skills_dirname: str = "skills"
    skills_root_path: str = ""

    def _default_skills_root(self) -> Path:
        return _resolve_named_root(
            configured_root_path=self.skills_root_path,
            root_dir_path=self.root_dir_path,
            default_dirname=self.default_skills_dirname,
        )

    def _extract_skill_name(self, node_meta: NodeMeta) -> str:
        ext_data = node_meta.ext_data
        if isinstance(ext_data, Mapping):
            return str(ext_data.get("skill_name", "")).strip()
        return ""

    def _read_skill_markdown(self, skills_root: Path, skill_name: str) -> str:
        return _read_named_markdown(skills_root, skill_name, "skill.md")

    def _extract_skill_sections(self, skill_markdown: str) -> tuple[str, str]:
        """Return (using_section, examples_section) from a parsed skill.md."""
        sections = _parse_markdown_sections(skill_markdown)
        return sections.get("Using", "").strip(), sections.get("Examples", "").strip()

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
        node_html_reference: str,
        output_path: str,
        graph_plan_path: str,
        language_clean: str,
        node_base_class: str,
        node_contract_text: str,
    ) -> str:
        base_prompt = super()._build_requirement_prompt(
            node_name=node_name,
            node_meta=node_meta,
            requirement_text=requirement_text,
            node_markdown_reference=node_markdown_reference,
            node_html_reference=node_html_reference,
            output_path=output_path,
            graph_plan_path=graph_plan_path,
            language_clean=language_clean,
            node_base_class=node_base_class,
            node_contract_text=node_contract_text,
        )

        skills_root = self._default_skills_root()
        skill_name = self._extract_skill_name(node_meta)
        skill_markdown = self._read_skill_markdown(skills_root, skill_name)
        skill_using, skill_examples = self._extract_skill_sections(skill_markdown)

        skill_context_lines = [
            "",
            "Skill node context (authoritative):",
            f"- skills_root: {skills_root}",
            f"- selected_skill_name: {skill_name or 'none'}",
            f"- SKILL_DIR class constant must be set to: {str(skills_root / skill_name) if skill_name else 'path/to/skill/dir'}",
        ]

        if skill_using:
            skill_context_lines.extend(
                [
                    "",
                    "skill.md ## Using section (authoritative — tells you how to invoke the skill):",
                    skill_using,
                ]
            )

        if skill_examples:
            skill_context_lines.extend(
                [
                    "",
                    "skill.md ## Examples section (authoritative — concrete usage patterns):",
                    skill_examples,
                ]
            )

        skill_context_lines.extend(
            [
                "",
                "Implementation constraints for this skill node:",
                "- Subclass WorkflowSkillNode.",
                "- Set SKILL_DIR to the exact skill directory path shown above.",
                "- Set SKILL_MD_PATH = str(Path(SKILL_DIR) / 'skill.md') so the base class parses the skill doc on init.",
                "- Implement process_operation(user_input, dependency_results, session_state) -> StepRunOutput.",
                "- In process_operation, invoke the skill using the pattern described in the ## Using section; use self.skill_using and self.skill_examples for inline reference if needed.",
                "- Use user_input when present; keep robust fallback behavior if user_input is empty.",
                "- Read upstream values from dependency_results[step_id].derived as needed.",
                "- Do not hardcode skill logic that contradicts skill.md ## Using; follow it exactly.",
                "- Keep output JSON-serializable and include useful derived fields for downstream nodes.",
            ]
        )

        return base_prompt + "\n" + "\n".join(skill_context_lines)

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowSkillNode subclass with STEP_ID, TITLE, PROMPT, DEPENDENCIES, SKILL_DIR, and SKILL_MD_PATH.\n"
            "Set SKILL_DIR to the absolute path of the chosen skill directory.\n"
            "Set SKILL_MD_PATH = str(Path(SKILL_DIR) / 'skill.md') — the base class reads and parses it on __init__.\n"
            "After __init__, self.skill_description, self.skill_using, self.skill_examples are available as strings parsed from skill.md.\n"
            "Implement skill invocation in process_operation(user_input, dependency_results, session_state) and return StepRunOutput.\n"
            "Use user_input when meaningful for the skill behavior; tolerate empty user_input when the step does not require it.\n"
            "Invoke the skill according to the ## Using section of skill.md; do not invent an invocation pattern.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state when needed.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "This node can consume direct user input when the workflow step is configured with inputRequired=true.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowSkillNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES/SKILL_DIR/SKILL_MD_PATH and process_operation returning StepRunOutput).\n"
        )
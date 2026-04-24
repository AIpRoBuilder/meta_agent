import sys
import json
import ast
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# Ensure repository root is on sys.path when run as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder
from context_builder.context import Context, GraphContextBuilder
from architect.graph import NodeMeta
from tools.file_tools import compile_node_file_and_get_derived_keys


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
        return ext_type in {"none", "image"}
    if isinstance(ext_data, str):
        return ext_data.strip().lower() in {"none", "image"}
    return False


def is_chat_ext_data(ext_data: Any) -> bool:
    """Return True when ext_data indicates conversational chat input is needed."""
    if isinstance(ext_data, Mapping):
        ext_type = str(ext_data.get("type", "")).strip().lower()
        return ext_type == "chat_input"
    if isinstance(ext_data, str):
        return ext_data.strip().lower() == "chat_input"
    return False


def is_image_ext_data(ext_data: Any) -> bool:
    """Return True when ext_data indicates image input is needed."""
    if isinstance(ext_data, Mapping):
        ext_type = str(ext_data.get("type", "")).strip().lower()
        return ext_type == "image"
    if isinstance(ext_data, str):
        return ext_data.strip().lower() == "image"
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
            lines.append(f"- {dep_name}: {', '.join(derived_keys)}")
        else:
            lines.append(f"- {dep_name}: (no derived keys detected)")

    return "\n".join(lines)


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
    

@dataclass
class PromptNodeFileCoderBase(Coder):
    prompt_path: str = "worker/prompts/pydaograph_node_prompt.md"
    reference_excerpt_path: str = "library/workflow_nodes_reference_excerpts.md"
    root_dir_path: str = ""
    context_text: str = ""
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

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
        output_path: str,
        graph_plan_path: str,
        language_clean: str,
        node_base_class: str,
        node_contract_text: str,
    ) -> str:
        depends_text = self._format_depends(node_meta.depends)
        ext_data_text = self._format_ext_data(node_meta.ext_data)

        minimal_policy_text = (
            "Minimal implementation policy (must follow):\n"
            "- Implement only requirement-critical behavior for this node; no extra features.\n"
            "- Keep structure flat and concise; avoid unnecessary helper functions/classes.\n"
            "- Prefer straightforward parsing/validation with simple guard clauses.\n"
            "- Every defined variable must be used; remove dead assignments.\n"
            "- Do not add demo/example code, logging, tests, or comments unless required.\n"
            "- Do not include TODO markers in generated code.\n\n"
        )

        user_prompt = (
            "You are generating an AG-UI workflow step node for PyDaoGraph.\n"
            f"Node name: {node_name}\n"
            f"Type: {node_meta.type}\n"
            f"Description: {node_meta.desc}\n"
            f"Depends on: {depends_text}\n"
            f"External data: {ext_data_text}\n"
            f"Expected base class: {node_base_class}\n"
            f"Target language: {language_clean}\n\n"
            f"{minimal_policy_text}"
            f"{node_contract_text}"
            "Requirement analysis that this node should satisfy:\n"
            f"{requirement_text}\n\n"
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

        self.context_text = ""

        dependency_context = _build_dependency_derived_context(
            node_dir=Path(output_path).expanduser().resolve().parent,
            dependency_names=list(node_meta.depends or []),
        )
        if dependency_context:
            user_prompt += (
                "\n\nDependency derived keys from existing dependency files "
                "(parsed via compile_node_file_and_get_derived_keys, authoritative):\n"
                f"{dependency_context}\n"
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
                    "- In process_input/process_chat/process_images_prompts/process_operation, extract upstream variables from dependency_results using only those dependency STEP_IDs and derived keys.\n"
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
        max_tokens: int = 20000,
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

        language_clean = language.strip().lower() if language else "python"
        target_ext = self._language_extension(language_clean)

        user_prompt = self._build_requirement_prompt(
            node_name=node_name,
            node_meta=node_meta,
            requirement_text=requirement_text,
            node_markdown_reference=node_markdown_reference,
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
        user_prompt = (
            "You are updating an existing AG-UI workflow node implementation.\n"
            f"Target language: {language_clean}\n"
            "Keep the code as simple as possible while fully satisfying the amendment and node requirements.\n"
            "Avoid adding new abstractions unless they are strictly needed.\n"
            "Every defined variable must be used; remove dead assignments.\n"
            f"{contract_text}"
            "Apply the amendment or feedback to produce the improved code.\n"
            "Return only runnable code without commentary or markdown fences.\n\n"
            "Existing code:\n"
            f"{original_code}\n\n"
            "Amendment / feedback to apply:\n"
            f"{amendment}\n"
        )

        return user_prompt

    def amend_code_with_feedback(
        self,
        code_path: str,
        amendment: str,
        *,
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 20000,
    ) -> Path:
        language_clean = language.strip().lower() if language else "python"
        target_path = Path(code_path)
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

        if self.context_text.strip():
            user_prompt += (
                "\n\nDependency context from GraphContextBuilder (authoritative):\n"
                "- Infer each dependency node's STEP_ID and available derived keys from this context.\n"
                "- In process_input/process_chat/process_operation, extract upstream variables from dependency_results using only those dependency STEP_IDs and derived keys.\n"
                "- Avoid guessed upstream field names; if a needed key is uncertain, use safe fallback handling without TODO markers.\n\n"
                f"{self.context_text}\n"
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
            "Generate a WorkflowOperationNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Implement business logic in process_operation(dependency_results, session_state) and return StepRunOutput.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "Do not require user input for this node.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowOperationNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES and process_operation returning StepRunOutput).\n"
        )


@dataclass
class WorkflowChatNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowChatNode"

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowChatNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Implement chat behavior in process_chat(user_input, dependency_results, session_state) and return str.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Use dependency_results and user_input together as context for chat responses.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "Ensure this node expects user input and supports conversational interaction.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowChatNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES and process_chat returning str).\n"
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
            "saved_files contains uploaded files already persisted by WorkflowFileNode save_files/save_files_remote, including original fileName and saved location.\n"
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
class WorkflowImageNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowImageNode"

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowImageNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Implement vision behavior in process_images_prompts(image_refs, request_text, dependency_results, session_state) and return a prompt string.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "image_refs is a list of uploaded file/image references and may contain multiple files.\n"
            "Use dependency_results and user-provided image/file list together as context for vision-language responses.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "Ensure this node expects user file/image input and supports multiple uploaded files.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowImageNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES and process_images_prompts returning prompt string; process_image_prompts may be kept for backward compatibility).\n"
        )


@dataclass
class WorkflowStepNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowStepNode"

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowStepNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Implement business logic in process_input(user_input, dependency_results, session_state) and return StepRunOutput.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowStepNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES and process_input returning StepRunOutput).\n"
        )


@dataclass
class WorkflowServiceNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowServiceNode"
    default_services_dirname: str = "agent_services"

    def _default_services_root(self) -> Path:
        if self.root_dir_path:
            root_dir = Path(self.root_dir_path).expanduser().resolve()
            direct = root_dir / self.default_services_dirname
            if direct.is_dir():
                return direct
            parent = root_dir.parent / self.default_services_dirname
            if parent.is_dir():
                return parent
        return ROOT_DIR.parent / self.default_services_dirname

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
        if not service_name:
            return ""
        service_doc = services_root / service_name / "service.md"
        if not service_doc.is_file():
            return ""
        return service_doc.read_text(encoding="utf-8").strip()

    def _extract_service_sections(self, service_markdown: str) -> tuple[str, str, str]:
        """Return (installation_section, start_service_section, using_section) from a parsed service.md.

        Sections are matched by H2 headings that start with '1.', '2.', or '3.' respectively.
        """
        if not service_markdown.strip():
            return "", "", ""
        try:
            from meta_agent.tools.file_tools import parse_skill_md
            sections = parse_skill_md(service_markdown)
        except Exception:
            sections = {}
        # Match sections by numeric prefix to tolerate slight heading variants.
        installation = ""
        start_service = ""
        using = ""
        for key, value in sections.items():
            key_stripped = key.strip()
            if key_stripped.startswith("1. Installation"):
                installation = value.strip()
            elif key_stripped.startswith("2. Start Service"):
                start_service = value.strip()
            elif key_stripped.startswith("3. Using"):
                using = value.strip()
        return installation, start_service, using

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
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
        installation_section, start_section, using_section = self._extract_service_sections(service_doc_text)
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

        if using_section:
            service_context_lines.extend(
                [
                    "",
                    "service.md ## 3. Using section (authoritative — implement this in use_service):",
                    using_section,
                ]
            )

        service_context_lines.extend(
            [
                "",
                "Implementation constraints for this service node:",
                "- Subclass WorkflowServiceNode.",
                "- Implement install_environment(dependency_results, session_state) -> bool based on the ## 1. Installation section.",
                "- Implement start_service(dependency_results, session_state) -> int based on the ## 2. Start Service section; return the PID of the launched process (use subprocess.Popen and return proc.pid).",
                "- Implement use_service(dependency_results, session_state) -> StepRunOutput based on the ## 3. Using section.",
                "- Do not override process_operation; the base class orchestrates the three phases automatically.",
                "- Use DEFAULT_WORKDIR or session_state.get('serviceWorkdir') as working directory; do not hardcode absolute paths.",
                "- Command sequence must be compatible with current_operating_system. Prefer the OS-specific variant when service.md lists multiple variants.",
                "- Keep output JSON-serializable and include useful derived fields for downstream nodes.",
            ]
            if not service_doc_text else [
                "",
                "Implementation constraints for this service node:",
                "- Subclass WorkflowServiceNode.",
                "- Implement install_environment(dependency_results, session_state) -> bool based on the ## 1. Installation section.",
                "- Implement start_service(dependency_results, session_state) -> int based on the ## 2. Start Service section; return the PID of the launched process (use subprocess.Popen and return proc.pid).",
                "- Implement use_service(dependency_results, session_state) -> StepRunOutput based on the ## 3. Using section.",
                "- Do not override process_operation; the base class orchestrates the three phases automatically.",
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
                    "- Fall back to minimal safe stub implementations for all three phases.",
                    "- install_environment: return True after a no-op check.",
                    "- start_service: launch a placeholder process and return its pid.",
                    "- use_service: return a minimal StepRunOutput with a descriptive summary.",
                    "- Do not invent unavailable service details.",
                ]
            )

        return base_prompt + "\n" + "\n".join(service_context_lines)

    def get_node_contract_text(self) -> str:
        return (
            "Generate a WorkflowServiceNode subclass with STEP_ID, TITLE, PROMPT, and DEPENDENCIES.\n"
            "Implement the three-phase execution pattern by overriding these three methods:\n"
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
            "  The working directory should be session_state.get('serviceWorkdir') or self.DEFAULT_WORKDIR.\n"
            "  If a custom default workdir is required, define class constant DEFAULT_WORKDIR in the generated node.\n"
            "  The generated command must be valid for the current operating system context.\n"
            "\n"
            "Phase 3 — use_service(self, dependency_results, session_state) -> StepRunOutput:\n"
            "  Implement based on service.md ## 3. Using section.\n"
            "  Interact with the running service (e.g. read output files, send HTTP requests, parse results).\n"
            "  Return StepRunOutput(summary=..., card=..., derived=...) with the service results.\n"
            "  Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "\n"
            "Do NOT override process_operation — the base class calls the three phases in order automatically.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state when needed.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "This node should not require direct user input.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowServiceNode three-phase contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES and install_environment returning bool, "
            "start_service returning int PID, use_service returning StepRunOutput).\n"
            "Do NOT override process_operation.\n"
        )


@dataclass
class WorkflowSkillNodeCoder(PromptNodeFileCoderBase):
    node_base_class: str = "WorkflowSkillNode"
    default_skills_dirname: str = "skills"

    def _default_skills_root(self) -> Path:
        if self.root_dir_path:
            root_dir = Path(self.root_dir_path).expanduser().resolve()
            direct = root_dir / self.default_skills_dirname
            if direct.is_dir():
                return direct
            parent = root_dir.parent / self.default_skills_dirname
            if parent.is_dir():
                return parent
        return ROOT_DIR.parent / self.default_skills_dirname

    def _extract_skill_name(self, node_meta: NodeMeta) -> str:
        ext_data = node_meta.ext_data
        if isinstance(ext_data, Mapping):
            return str(ext_data.get("skill_name", "")).strip()
        return ""

    def _read_skill_markdown(self, skills_root: Path, skill_name: str) -> str:
        if not skill_name:
            return ""
        skill_doc = skills_root / skill_name / "skill.md"
        if not skill_doc.is_file():
            return ""
        return skill_doc.read_text(encoding="utf-8").strip()

    def _extract_skill_sections(self, skill_markdown: str) -> tuple[str, str]:
        """Return (using_section, examples_section) from a parsed skill.md."""
        if not skill_markdown.strip():
            return "", ""
        try:
            from meta_agent.tools.file_tools import parse_skill_md
            sections = parse_skill_md(skill_markdown)
        except Exception:
            sections = {}
        return sections.get("Using", "").strip(), sections.get("Examples", "").strip()

    def _build_requirement_prompt(
        self,
        node_name: str,
        node_meta: NodeMeta,
        requirement_text: str,
        node_markdown_reference: str,
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
                "- Implement process_operation(dependency_results, session_state) -> StepRunOutput.",
                "- In process_operation, invoke the skill using the pattern described in the ## Using section; use self.skill_using and self.skill_examples for inline reference if needed.",
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
            "Implement skill invocation in process_operation(dependency_results, session_state) and return StepRunOutput.\n"
            "Invoke the skill according to the ## Using section of skill.md; do not invent an invocation pattern.\n"
            "Keep implementation minimal: only imports, constants, and methods required by this node contract.\n"
            "Read upstream values from dependency_results[step_id].derived and persist cross-step values in session_state when needed.\n"
            "Extract upstream variables only from nodes listed in DEPENDENCIES and from keys present in those dependencies' derived payloads.\n"
            "When dependency context is provided, treat it as authoritative for dependency ids and derived keys; do not invent non-existent upstream keys.\n"
            "Keep card payload JSON-serializable and derived payload structured for downstream nodes.\n"
            "This node should not require direct user input.\n\n"
        )

    def get_feedback_contract_text(self) -> str:
        return (
            "Preserve the WorkflowSkillNode contract "
            "(STEP_ID/TITLE/PROMPT/DEPENDENCIES/SKILL_DIR/SKILL_MD_PATH and process_operation returning StepRunOutput).\n"
        )
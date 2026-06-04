"""Utilities for generating a PyDaoGraph entrypoint via an LLM."""

from __future__ import annotations

import json
import sys
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

# Resolve package root consistently for both source checkout and pip-installed layouts.
_DEFAULT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_META_AGENT_SPEC = importlib.util.find_spec("meta_agent")
if _META_AGENT_SPEC and _META_AGENT_SPEC.origin:
    ROOT_DIR = Path(_META_AGENT_SPEC.origin).resolve().parent
else:
    ROOT_DIR = _DEFAULT_PACKAGE_ROOT

if str(ROOT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR.parent))

from meta_agent.llm_client.coder import Coder
from meta_agent.tools.text_tools import normalize_requirement_analysis_result


def _stringify_modules(module_names: Optional[Sequence[str]]) -> str:
    if not module_names:
        return "No explicit module list; auto-discover every Python file under nodes_root."
    return "Explicit node modules to import in order: " + ", ".join(module_names)


def _extract_enabled_node_class_names(graph_plan: Mapping[str, Any]) -> list[str]:
    nodes = graph_plan.get("nodes", []) if isinstance(graph_plan, Mapping) else []
    if not isinstance(nodes, list):
        return []

    node_class_names: list[str] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if node.get("enable", True) is False:
            continue

        class_name = str(node.get("name", "")).strip()
        if class_name:
            node_class_names.append(class_name)
    return node_class_names


@dataclass
class PromptMainFileCoder(Coder):
    """Coder that emits an AG-UI lifecycle FastAPI backend entrypoint."""

    prompt_path: str = "worker/prompts/pydaograph_main_prompt.md"

    def __post_init__(self) -> None:
        prompt_file = ROOT_DIR / self.prompt_path
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        self.system_prompt = prompt_file.read_text(encoding="utf-8")
        super().__post_init__()

    def _build_user_prompt(
        self,
        *,
        project_root_path: Path,
        graph_plan_json_path: Path,
        node_class_names: Sequence[str],
        nodes_package_name: str,
        fastapi_host: str,
        fastapi_port: int,
        uvicorn_reload: bool,
        requirement_analysis_result: Mapping[str, Any] | None = None,
    ) -> str:
        class_chain = ", ".join(node_class_names) if node_class_names else "none"
        cron_meta = normalize_requirement_analysis_result(requirement_analysis_result)
        cron_lines: list[str] = []
        if cron_meta and cron_meta["is_cron_task"]:
            cron_expression = cron_meta["crontab_expression"] or "TBD"
            cron_lines = [
                "- This workflow is a cron task according to requirement_analysis_result.",
                f"- Cron metadata: task_type={cron_meta['task_type'] or 'cron'}, crontab_expression={cron_expression}.",
                "- Import croniter and add a read-only cron config API GET /api/cron-config that returns isCronTask, taskType, and crontabExpression from the analyzed requirement.",
                "- Add a POST /api/cron-preview endpoint that accepts a crontabExpression and returns validation result plus the next five scheduled run times in ISO format.",
                "- Keep the cron API lightweight and self-contained in main.py; do not add persistence, auth, or unrelated scheduling infrastructure.",
            ]
        template_lines: Iterable[str] = (
            "Generate a single Python backend file that matches the AG-UI lifecycle workflow backend pattern.",
            f"Project root path: {project_root_path}",
            f"Workflow pipeline JSON path: {graph_plan_json_path}",
            f"Node classes in graph-plan order: {class_chain}",
            f"Node package root name: {nodes_package_name}",
            "The file must:",
            "- Use imports and module layout aligned with the lifecycle example: FastAPI, HTMLResponse, StreamingResponse, BaseModel, WorkflowEngine, and node imports from the root package.",
            "- Automatically load environment variables from a .env file on startup (prefer `from dotenv import load_dotenv`) before app/engine initialization.",
            "- Resolve .env path robustly by trying current file directory first and then project root fallback.",
            "- Import all node classes from the package root named above (for example `from example_agent_output import StepA, StepB`) and do NOT import from `.step_nodes`.",
            "- Do not use relative node imports such as `from . import ...`; use `from <root_package_name> import ...` directly.",
            "- Ensure node imports work when executed as script (`python main.py`) and avoid try/except import blocks.",
            "- In generated main.py, include `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before importing node classes.",
            "- Define app-level constants for pipeline json path, engine cache map, and ordered STEP_CHAIN built from each node's step_meta().",
            "- Implement RunStepInput, ResetSessionInput, and ResetSessionOutput pydantic models with camelCase fields.",
            "- In RunStepInput include: sessionId, stepId, input, and optional file_path.",
            "- Type RunStepInput.input as flexible payload (e.g. str | dict[str, Any] | None), not str-only.",
            "- Add a small helper (for example `_meta_field(meta, key, default=None)`) that reads step metadata from either dict-like or object-like shapes.",
            "- Implement _get_engine(session_id) that lazily creates WorkflowEngine per session and caches it in ENGINES.",
            "- Provide GET / returning frontend.html from the same directory.",
            "- Provide POST /api/run-step returning StreamingResponse(engine._run_step_events(...)) with SSE headers.",
			"- In /api/run-step, resolve step metadata by payload.stepId and branch by extData.type using dict-safe access from STEP_CHAIN step_meta() (no direct attribute access like `s.id` or `step_meta.extData`).",
			"- Use metadata lookup shape equivalent to: `next((s for s in STEP_CHAIN if _meta_field(s, \"id\") == payload.stepId), None)`.",
			"- Read ext type via mapping-safe logic equivalent to: `ext_data = _meta_field(step_meta, \"extData\"); ext_type = ext_data.get(\"type\") if isinstance(ext_data, Mapping) else None`.",
            "- Only for extData.type == 'user_file_input', if payload.file_path is provided pass {'file_path': payload.file_path}; otherwise pass payload.input.",
            "- Provide POST /api/reset-session returning ResetSessionOutput with ok/sessionId/threadId/runId.",
            "- Keep naming and endpoint shapes consistent with the lifecycle example and avoid adding unrelated routes.",
            f"- If adding a local server launcher helper, default host to {fastapi_host} and port to {fastapi_port}; reload default is {uvicorn_reload}.",
            *cron_lines,
            "- Only output runnable Python code; no Markdown fences or commentary.",
        )
        return "\n".join(template_lines)

    def write_nodes_package_init(
        self,
        *,
        graph_plan_json_path: str,
        package_dir_path: str,
        output_path: Optional[str] = None,
        overwrite: bool = True,
    ) -> Path:
        graph_plan_path = Path(graph_plan_json_path).expanduser().resolve()
        if not graph_plan_path.exists():
            raise FileNotFoundError(f"graph_plan_json_path does not exist: {graph_plan_path}")

        package_dir = Path(package_dir_path).expanduser().resolve()
        if not package_dir.exists() or not package_dir.is_dir():
            raise FileNotFoundError(f"package_dir_path does not exist or is not a directory: {package_dir}")

        graph_plan = json.loads(graph_plan_path.read_text(encoding="utf-8"))
        node_class_names = _extract_enabled_node_class_names(graph_plan)
        if not node_class_names:
            raise ValueError(f"No enabled nodes found in graph plan: {graph_plan_path}")

        missing_node_files = [name for name in node_class_names if not (package_dir / f"{name}.py").exists()]
        if missing_node_files:
            missing_preview = ", ".join(missing_node_files)
            raise FileNotFoundError(f"Node files missing under package directory {package_dir}: {missing_preview}")

        init_path = Path(output_path).expanduser() if output_path else package_dir / "__init__.py"
        if init_path.exists() and not overwrite:
            raise FileExistsError(f"Output file already exists and overwrite=False: {init_path}")

        lines: list[str] = [
            '"""Node package exports generated from graph_plan.json."""',
            "",
        ]
        for class_name in node_class_names:
            lines.append(f"from .{class_name} import {class_name}")

        lines.extend(
            [
                "",
                "__all__ = [",
                *[f'    "{class_name}",' for class_name in node_class_names],
                "]",
                "",
            ]
        )

        init_path.parent.mkdir(parents=True, exist_ok=True)
        init_path.write_text("\n".join(lines), encoding="utf-8")
        return init_path

    def write_main_entrypoint(
        self,
        *,
        project_root_path: str,
        graph_plan_json_path: str,
        output_path: str,
        requirement_analysis_result: Mapping[str, Any] | None = None,
        fastapi_host: str = "0.0.0.0",
        fastapi_port: int = 8000,
        uvicorn_reload: bool = False,
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> Path:
        project_root = Path(project_root_path).expanduser().resolve()
        if not project_root.exists() or not project_root.is_dir():
            raise FileNotFoundError(f"project_root_path does not exist or is not a directory: {project_root}")

        graph_plan_path = Path(graph_plan_json_path).expanduser().resolve()
        if not graph_plan_path.exists():
            raise FileNotFoundError(f"graph_plan_json_path does not exist: {graph_plan_path}")

        graph_plan = json.loads(graph_plan_path.read_text(encoding="utf-8"))
        node_class_names = _extract_enabled_node_class_names(graph_plan)
        if not node_class_names:
            raise ValueError(f"No enabled nodes found in graph plan: {graph_plan_path}")

        target_path = Path(output_path).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        nodes_package_name = target_path.parent.name

        self.write_nodes_package_init(
            graph_plan_json_path=str(graph_plan_path),
            package_dir_path=str(target_path.parent),
            overwrite=overwrite,
        )

        user_prompt = self._build_user_prompt(
            project_root_path=project_root,
            graph_plan_json_path=graph_plan_path,
            node_class_names=node_class_names,
            nodes_package_name=nodes_package_name,
            fastapi_host=fastapi_host,
            fastapi_port=fastapi_port,
            uvicorn_reload=uvicorn_reload,
            requirement_analysis_result=requirement_analysis_result,
        )

        return self.code_to_file(
            user_prompt,
            str(target_path),
            overwrite=overwrite,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
    def amend_code_with_feedback(
        self,
        code_path: str,
        amendment: str,
        *,
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> Path:
        """Amend existing code using feedback and write the updated code to disk."""

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
        target_path = Path(code_path)
        target_ext = ext_map.get(language_clean, f".{language_clean}" if language_clean else (target_path.suffix or ".txt"))
        if target_path.suffix.lower() != target_ext:
            target_path = target_path.with_suffix(target_ext)
        
        if not target_path.exists():
            raise FileNotFoundError(f"Code file not found: {target_path}")

        original_code = target_path.read_text(encoding="utf-8")
        
        user_prompt = (
            "You are updating an existing PyDaoGraph node implementation.\n"
            f"Target language: {language_clean}\n"
            "Apply the amendment or feedback to produce the improved code.\n"
            "Return only runnable code without commentary.\n\n"
            "Existing code:\n"
            f"{original_code}\n\n"
            "Amendment / feedback to apply:\n"
            f"{amendment}\n"
        )

        return self.code_to_file(
            user_prompt,
            str(target_path),
            overwrite=overwrite,
            temperature=temperature,
            max_tokens=max_tokens,
        )

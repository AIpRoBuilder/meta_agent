"""Utilities for generating a PyDaoGraph entrypoint via an LLM."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

# Ensure repository root is importable so we can reach llm_client.coder when executed
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder


def _stringify_modules(module_names: Optional[Sequence[str]]) -> str:
    if not module_names:
        return "No explicit module list; auto-discover every Python file under nodes_root."
    return "Explicit node modules to import in order: " + ", ".join(module_names)


@dataclass
class PromptMainFileCoder(Coder):
    """Coder that emits a FastAPI-wrapped PyDaoGraph entrypoint."""

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
        pipeline_json: Path,
        fastapi_host: str,
        fastapi_port: int,
        uvicorn_reload: bool,
    ) -> str:
        template_lines: Iterable[str] = (
            "Generate a single Python file that bootstraps a PyDaoGraph pipeline.",
            f"Graph definition JSON path: {pipeline_json}",
            "The file must:",
            "- Add nodes_root to sys.path and import the required node classes before building the pipeline.",
            "- Follow the canonical GPipeline build snippet shown in the system prompt.",
            "- Provide a CLI-friendly main() that prints build info and runs the pipeline.",
            "- Create a FastAPI app exposing /health, /pipeline, /pipeline/run, and /pipeline/destroy routes.",
            "- Reuse one GPipeline instance for both CLI and HTTP uses, guarding concurrent runs with an asyncio.Lock.",
            f"- Expose a serve(host=\"{fastapi_host}\", port={fastapi_port}, reload={uvicorn_reload}) helper that calls uvicorn.run.",
            "- Include an argparse entry so users can pick CLI vs server mode and override host/port at runtime.",
            "- Only output runnable Python code; no Markdown fences or commentary.",
        )
        return "\n".join(template_lines)

    def write_main_entrypoint(
        self,
        *,
        pipeline_json: str,
        output_path: str,
        fastapi_host: str = "0.0.0.0",
        fastapi_port: int = 8000,
        uvicorn_reload: bool = False,
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> Path:
        pipeline_json_path = Path(pipeline_json).expanduser().resolve()
        if not pipeline_json_path.exists():
            raise FileNotFoundError(f"pipeline_json does not exist: {pipeline_json_path}")

        target_path = Path(output_path).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        user_prompt = self._build_user_prompt(
            pipeline_json=pipeline_json_path,
            fastapi_host=fastapi_host,
            fastapi_port=fastapi_port,
            uvicorn_reload=uvicorn_reload,
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
        target_ext = ext_map.get(language_clean, f".{language_clean}" if language_clean else source_path.suffix)


        target_path = Path(code_path)
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

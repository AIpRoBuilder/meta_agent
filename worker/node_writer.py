import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# Ensure repository root is on sys.path when run as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder

@dataclass
class PromptNodeFileCoder(Coder):
    """Coder that preloads a system prompt from a markdown file."""

    prompt_path: str = "worker/prompts/pydaograph_node_prompt.md"

    def __post_init__(self) -> None:
        prompt_file = ROOT_DIR / self.prompt_path
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        self.system_prompt = prompt_file.read_text(encoding="utf-8")
        super().__post_init__()

    def write_node_from_requirement(
        self,
        node_name: str,
        node_spec: Mapping[str, Any],
        requirement_md_path: str,
        output_path: str,
        *,
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Path:
        """Generate a node file using requirement context and node metadata."""

        requirement_path = Path(requirement_md_path)
        if not requirement_path.exists():
            raise FileNotFoundError(f"Requirement file not found: {requirement_path}")

        requirement_text = requirement_path.read_text(encoding="utf-8")

        depends = node_spec.get("depends", []) if isinstance(node_spec, Mapping) else []
        if isinstance(depends, (str, bytes)):
            depends_list = [depends]
        elif isinstance(depends, list):
            depends_list = depends
        else:
            depends_list = list(depends) if depends is not None else []

        node_meta = {
            "type": node_spec.get("type", "") if isinstance(node_spec, Mapping) else "",
            "desc": node_spec.get("desc", "") if isinstance(node_spec, Mapping) else "",
            "depends": depends_list,
        }

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
        target_ext = ext_map.get(language_clean, f".{language_clean}" if language_clean else ".txt")

        depends_text = ", ".join(node_meta["depends"]) if node_meta["depends"] else "none"
        user_prompt = (
            "You are generating a PyDaoGraph node.\n"
            f"Node name: {node_name}\n"
            f"Type: {node_meta['type']}\n"
            f"Description: {node_meta['desc']}\n"
            f"Depends on: {depends_text}\n"
            f"Target language: {language_clean}\n\n"
            "Requirement analysis that this node should satisfy:\n"
            f"{requirement_text}\n\n"
            f"Return only runnable {language_clean} code for this node."
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

    def amend_code_with_feedback(
        self,
        code_path: str,
        amendment: str,
        *,
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 4096,
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
    
    
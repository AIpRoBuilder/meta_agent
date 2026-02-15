import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.graph_tools import graph_to_nodes

# Ensure repository root is on sys.path when run as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder
from context_builder.context import Context, GraphContextBuilder

@dataclass
class PromptNodeFileCoder(Coder):
    """Coder that preloads a system prompt from a markdown file."""

    prompt_path: str = "worker/prompts/pydaograph_node_prompt.md"
    root_dir_path: str = ""

    def __post_init__(self) -> None:
        prompt_file = ROOT_DIR / self.prompt_path
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

        self.system_prompt = prompt_file.read_text(encoding="utf-8")
        super().__post_init__()

    def write_node_from_requirement(
        self,
        node_name: str,
        param_name: str,
        graph_plan_path: str,
        requirement_md_path: str,
        output_path: str,
        *,
        language: str = "python",
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> Path:
        """Generate a node file using requirement context and node metadata."""
        node_spec = graph_to_nodes(graph_plan_path)

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
        )

        # Build context from graph_plan.json dependencies
        context_builder = GraphContextBuilder(root_path=self.root_dir_path, language=language_clean)
        context_builder.search(current_node_name=node_name, graph_plan_path=graph_plan_path)
        # Add the built context to the user prompt
        # context_path = self.root_dir_path + f"/{param_name}{target_ext}"
        # context_builder.add_context(Context(
        #     current_file_location=str(self.root_dir_path + f"/{node_name}{target_ext}"),
        #     current_file_name=f"{node_name}{target_ext}",
        #     context_file_location=context_path,
        #     context_file_name=param_name,
        #     context_file_description=f"{param_name} context class to store data across node executions and have to be imported to current node files if needed.",
        #     context_file_text=Path(context_path).read_text(encoding="utf-8") if Path(context_path).exists() else "",
        #     relevance=1.0,
        # ))
        context_text = context_builder.build(limit=5)
        if context_text:
            user_prompt += f"\n\nContext from dependencies:\n{context_text}"
        
        
        if user_prompt.strip():
            user_prompt += f"\n\nReturn only runnable {language_clean} code for this node."

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
    
    
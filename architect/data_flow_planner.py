import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder


@dataclass
class DataFlowPlanner(Coder):
	"""Generate a data-flow diagram JSON from a requirements analysis."""

	prompt_path: str = "architect/prompts/data_flow_diagram_planner_prompt.md"

	def __post_init__(self) -> None:
		prompt_file = ROOT_DIR / self.prompt_path
		if not prompt_file.exists():
			raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

		self.system_prompt = prompt_file.read_text(encoding="utf-8")
		super().__post_init__()

	def diagram_from_file(
		self,
		requirement_md_path: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = 8192,
	) -> Path:
		"""Read requirement_analysis.md and write a data-flow diagram JSON."""

		requirement_path = Path(requirement_md_path)
		if not requirement_path.exists():
			raise FileNotFoundError(f"Requirement file not found: {requirement_path}")

		requirement_text = requirement_path.read_text(encoding="utf-8")
		return self.diagram(
			requirement_text,
			output_path,
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

	def diagram(
		self,
		requirement_text: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = 8192,
	) -> Path:
		"""Call the LLM and persist the data-flow diagram as JSON."""

		target_path = Path(output_path)
		if target_path.suffix.lower() != ".json":
			target_path = target_path.with_suffix(".json")

		return self.code_to_file(
			requirement_text,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

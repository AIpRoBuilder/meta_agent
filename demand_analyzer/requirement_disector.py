import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR))

from llm_client.coder import Coder


@dataclass
class RequirementDisector(Coder):
	"""Generate requirements analysis markdown from a demand description."""

	prompt_path: str = "demand_analyzer/prompts/requirement_disector_prompt.md"

	def __post_init__(self) -> None:
		prompt_file = ROOT_DIR / self.prompt_path
		if not prompt_file.exists():
			raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

		self.system_prompt = prompt_file.read_text(encoding="utf-8")
		super().__post_init__()

	def analyze(
		self,
		user_prompt: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = 8192,
	) -> Path:
		"""Call the LLM and persist the requirements analysis as markdown."""

		target_path = Path(output_path)
		if target_path.suffix.lower() != ".md":
			target_path = target_path.with_suffix(".md")

		return self.code_to_file(
			user_prompt,
			str(target_path),
			overwrite=overwrite,
			temperature=temperature,
			max_tokens=max_tokens,
		)

import json
from dataclasses import dataclass
from pathlib import Path

from croniter import croniter

from meta_agent._paths import bootstrap_package_root


ROOT_DIR = bootstrap_package_root(__file__)

from meta_agent.llm_client.coder import Coder, MAX_TOKENS


def _load_json_object(text: str) -> dict:
	"""Parse a JSON object, tolerating extra wrapper text around it."""

	try:
		return json.loads(text)
	except json.JSONDecodeError:
		start = text.find("{")
		end = text.rfind("}")
		if start == -1 or end == -1 or end <= start:
			raise
		return json.loads(text[start : end + 1])


@dataclass
class RequirementAnalysisResult:
	"""Artifacts and metadata produced from requirement analysis."""

	output_path: Path
	is_cron_task: bool
	task_type: str
	crontab_expression: str | None = None


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

	def _classify_cron_task(
		self,
		user_prompt: str,
		requirement_analysis: str,
		*,
		temperature: float,
		max_tokens: int,
	) -> dict:
		"""Use the LLM to classify whether the requirement describes a cron task."""

		classification_prompt = (
			"判断下面的用户需求和需求分析是否描述了一个定时任务。"
			"如果是定时任务，task_type 必须返回 cron，并尽量返回标准 5 段 crontab 表达式。"
			"如果无法确定具体调度，请根据语义给出最合理的 crontab；若不是定时任务，crontab_expression 返回 null。\n\n"
			"只返回 JSON，不要添加额外说明。JSON Schema:"
			'{"is_cron_task": boolean, "task_type": string, "crontab_expression": string | null}\n\n'
			f"用户需求:\n{user_prompt}\n\n"
			f"需求分析:\n{requirement_analysis}\n"
		)
		response_text = self.generate_code(
			classification_prompt,
			temperature=temperature,
			max_tokens=max_tokens,
		)
		payload = _load_json_object(response_text)
		is_cron_task = bool(payload.get("is_cron_task"))
		task_type = str(payload.get("task_type") or "cron" if is_cron_task else "general").strip()
		crontab_expression = payload.get("crontab_expression")
		if isinstance(crontab_expression, str):
			crontab_expression = crontab_expression.strip() or None
		else:
			crontab_expression = None

		if is_cron_task:
			task_type = "cron"
			if crontab_expression and not croniter.is_valid(crontab_expression):
				crontab_expression = None
		else:
			crontab_expression = None

		return {
			"is_cron_task": is_cron_task,
			"task_type": task_type or ("cron" if is_cron_task else "general"),
			"crontab_expression": crontab_expression,
		}

	def analyze(
		self,
		user_prompt: str,
		output_path: str,
		*,
		overwrite: bool = True,
		temperature: float = 0.2,
		max_tokens: int = MAX_TOKENS,
	) -> RequirementAnalysisResult:
		"""Call the LLM, persist the requirements analysis, and classify cron metadata."""

		target_path = Path(output_path)
		if target_path.suffix.lower() != ".md":
			target_path = target_path.with_suffix(".md")

		requirement_analysis = self.generate_code(
			user_prompt,
			temperature=temperature,
			max_tokens=max_tokens,
		)
		written_path = self.write_code_to_file(
			requirement_analysis,
			str(target_path),
			overwrite=overwrite,
		)
		classification = self._classify_cron_task(
			user_prompt,
			requirement_analysis,
			temperature=temperature,
			max_tokens=max_tokens,
		)
		return RequirementAnalysisResult(output_path=written_path, **classification)

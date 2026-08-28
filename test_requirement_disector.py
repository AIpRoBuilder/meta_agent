from types import SimpleNamespace

from meta_agent.demand_analyzer.requirement_disector import RequirementDisector


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        content = self._responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_analyze_returns_cron_metadata_and_writes_markdown(tmp_path):
    output_path = tmp_path / "requirement_analysis.md"
    analyzer = RequirementDisector(
        client=_FakeClient(
            [
                "# 需求分析\n\n- 每天早上 9 点执行一次同步任务",
                '{"is_cron_task": true, "task_type": "cron", "crontab_expression": "0 9 * * *"}',
            ]
        )
    )

    result = analyzer.analyze("每天早上9点同步一次数据", str(output_path))

    assert result.output_path == output_path
    assert output_path.read_text(encoding="utf-8") == "# 需求分析\n\n- 每天早上 9 点执行一次同步任务"
    assert result.is_cron_task is True
    assert result.task_type == "cron"
    assert result.crontab_expression == "0 9 * * *"


def test_analyze_clears_crontab_when_not_cron(tmp_path):
    output_path = tmp_path / "requirement_analysis"
    analyzer = RequirementDisector(
        client=_FakeClient(
            [
                "# 需求分析\n\n- 用户提交后立即触发处理",
                '{"is_cron_task": false, "task_type": "event", "crontab_expression": "*/5 * * * *"}',
            ]
        )
    )

    result = analyzer.analyze("用户上传文件后立即处理", str(output_path))

    assert result.output_path == output_path.with_suffix(".md")
    assert result.is_cron_task is False
    assert result.task_type == "general"
    assert result.crontab_expression is None


def test_requirement_disector_prompt_requires_show_frontend_column() -> None:
    analyzer = RequirementDisector(client=_FakeClient([]))

    assert "是否展示前端(show_frontend)" in analyzer.system_prompt
    assert "必须为 true/false" in analyzer.system_prompt
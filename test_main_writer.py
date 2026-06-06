from types import SimpleNamespace

from meta_agent.worker.main_writer import PromptMainFileCoder


class _FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="print('ok')"))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_build_user_prompt_includes_cron_trigger_requirements(tmp_path):
    writer = PromptMainFileCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        project_root_path=tmp_path,
        graph_plan_json_path=tmp_path / "graph_plan.json",
        node_class_names=["CollectInput", "ProcessInput"],
        nodes_package_name="example_agent_output",
        fastapi_host="0.0.0.0",
        fastapi_port=8000,
        uvicorn_reload=False,
        requirement_analysis_result={
            "is_cron_task": True,
            "task_type": "cron",
            "crontab_expression": "0 9 * * *",
        },
    )

    assert "POST /cron/start" in prompt
    assert "do not generate /api/run-step" in prompt
    assert "background cron runner" in prompt
    assert "WorkflowEngine._run_all_steps_events" in prompt
    assert "asyncio.create_task" in prompt
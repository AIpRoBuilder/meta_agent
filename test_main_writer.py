from types import SimpleNamespace

import meta_agent.agent_builder as agent_builder_module
from meta_agent.agent_builder import AgentBuilder
from meta_agent.worker.main_writer import PromptMainFileCoder


class _FakeComponent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


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


def test_build_user_prompt_requires_uvicorn_launcher(tmp_path):
    writer = PromptMainFileCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        project_root_path=tmp_path,
        graph_plan_json_path=tmp_path / "graph_plan.json",
        node_class_names=["CollectInput"],
        nodes_package_name="example_agent_output",
        fastapi_host="127.0.0.1",
        fastapi_port=9000,
        uvicorn_reload=True,
        requirement_analysis_result=None,
    )

    assert "uvicorn" in prompt
    assert "if __name__ == \"__main__\":" in prompt
    assert "uvicorn.run(app" in prompt


def test_agent_builder_reset_llm_config_recreates_llm_components(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)

    builder = AgentBuilder(
        api_key="old-key",
        model="old-model",
        provider="old-provider",
        root_dir=str(tmp_path),
        services_root_path="services-dir",
        skills_root_path="skills-dir",
    )

    initial_main_writer = builder.main_writer

    builder.reset_llm_config(api_key="new-key", model="new-model", provider="new-provider")

    assert builder.api_key == "new-key"
    assert builder.model == "new-model"
    assert builder.provider == "new-provider"
    assert builder.main_writer is not initial_main_writer
    assert builder.analyzer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
    }
    assert builder.planner.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
        "services_root_path": "services-dir",
        "skills_root_path": "skills-dir",
    }
    assert builder.node_planner.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
    }
    assert builder.main_writer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
    }
    assert builder.frontend_writer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
    }
    assert builder.frontend_view_writer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
    }
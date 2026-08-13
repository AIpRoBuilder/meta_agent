from types import SimpleNamespace

import pytest

import meta_agent.agent_builder as agent_builder_module
from meta_agent.agent_builder import AgentBuilder
from meta_agent.architect.graph import NodeMeta
from meta_agent.architect.node_planner import NodePlanner
from meta_agent.llm_client.coder import compose_session_marking_prompt
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


class _FakePlanner:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.plan_calls = []
        self.amend_calls = []

    def plan_from_file(self, requirement_md_path, graph_plan_path):
        self.plan_calls.append((requirement_md_path, graph_plan_path))

    def amend_file_with_feedback(self, graph_plan_path, amendment, temperature=0.35):
        self.amend_calls.append((graph_plan_path, amendment, temperature))


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
        session_marking_prompt="Keep request_id on all file/text IO.",
    )

    expected_session_prompt = compose_session_marking_prompt(
        "Keep request_id on all file/text IO."
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
        "session_marking_prompt": expected_session_prompt,
    }
    assert builder.planner.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
        "services_root_path": "services-dir",
        "skills_root_path": "skills-dir",
        "session_marking_prompt": expected_session_prompt,
    }
    assert builder.node_planner.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
        "skills_root_path": "skills-dir",
        "session_marking_prompt": expected_session_prompt,
    }
    assert builder.main_writer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
        "session_marking_prompt": expected_session_prompt,
    }
    assert builder.frontend_writer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
        "session_marking_prompt": expected_session_prompt,
    }
    assert builder.frontend_view_writer.kwargs == {
        "api_key": "new-key",
        "model": "new-model",
        "provider": "new-provider",
        "session_marking_prompt": expected_session_prompt,
    }


def test_agent_builder_make_node_coder_passes_session_marking_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "WorkflowStepNodeCoder", _FakeComponent)

    builder = AgentBuilder(
        api_key="key",
        model="model",
        provider="provider",
        root_dir=str(tmp_path),
        session_marking_prompt="Use request_marker in generated node IO.",
    )

    coder = builder._make_node_coder(
        NodeMeta(
            name="CollectInput",
            type="",
            desc="Collect input",
            ext_data={"type": "user_input", "desc": "Collect request text"},
        )
    )

    assert coder.kwargs["session_marking_prompt"] == compose_session_marking_prompt(
        "Use request_marker in generated node IO."
    )


def test_node_planner_system_prompt_includes_session_marking_prompt():
    planner = NodePlanner(
        client=_FakeClient(),
        session_marking_prompt=compose_session_marking_prompt(
            "Keep node brief examples request scoped."
        ),
    )

    assert "Request-scoped session marking policy" in planner.system_prompt
    assert "Keep node brief examples request scoped." in planner.system_prompt


def test_build_steps_meta_skips_nodes_with_show_frontend_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)

    builder = AgentBuilder(
        api_key="key",
        model="model",
        provider="provider",
        root_dir=str(tmp_path),
        services_root_path="services-dir",
        skills_root_path="skills-dir",
    )

    class _FakePlannedGraph:
        def get_topological_sorted_nodes(self):
            return ["VisibleNode", "HiddenNode"]

        def get_node_meta(self, node_name):
            if node_name == "VisibleNode":
                return NodeMeta(name="VisibleNode", type="", desc="Visible node", show_frontend=True)
            if node_name == "HiddenNode":
                return NodeMeta(name="HiddenNode", type="", desc="Hidden node", show_frontend=False)
            return None

    builder.planned_graph = _FakePlannedGraph()

    steps_meta = builder._build_steps_meta()

    assert [step["id"] for step in steps_meta] == ["VisibleNode"]


def test_build_steps_meta_can_include_hidden_nodes(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)

    builder = AgentBuilder(
        api_key="key",
        model="model",
        provider="provider",
        root_dir=str(tmp_path),
        services_root_path="services-dir",
        skills_root_path="skills-dir",
    )

    class _FakePlannedGraph:
        def get_topological_sorted_nodes(self):
            return ["VisibleNode", "HiddenNode"]

        def get_node_meta(self, node_name):
            if node_name == "VisibleNode":
                return NodeMeta(name="VisibleNode", type="", desc="Visible node", show_frontend=True)
            if node_name == "HiddenNode":
                return NodeMeta(name="HiddenNode", type="", desc="Hidden node", show_frontend=False)
            return None

    builder.planned_graph = _FakePlannedGraph()

    steps_meta = builder._build_steps_meta(include_hidden_nodes=True)

    assert [step["id"] for step in steps_meta] == ["VisibleNode", "HiddenNode"]


def test_agent_builder_defaults_max_audit_rounds_to_seven(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)

    builder = AgentBuilder(
        api_key="key",
        model="model",
        provider="provider",
        root_dir=str(tmp_path),
    )

    assert builder.max_audit_rounds == 7


def test_plan_graph_stops_after_configured_max_audit_rounds(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakePlanner)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "Graph", lambda path: SimpleNamespace(path=path))

    builder = AgentBuilder(
        api_key="key",
        model="model",
        provider="provider",
        root_dir=str(tmp_path),
        max_audit_rounds=2,
    )
    builder.graph_auditor = SimpleNamespace(
        audit_graph_json=lambda _graph: (
            False,
            [SimpleNamespace(lineno=3, rule="invalid_graph", detail="graph invalid")],
        )
    )

    with pytest.raises(RuntimeError, match="graph plan audit did not pass after 2 attempt\\(s\\)"):
        builder.plan_graph(requirement_md_path=str(tmp_path / "requirement.md"))

    assert len(builder.planner.amend_calls) == 1
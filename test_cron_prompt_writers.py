from types import SimpleNamespace
from pathlib import Path

from meta_agent.worker.frontend_writer import PromptFrontendCoder
from meta_agent.worker.main_writer import PromptMainFileCoder


class _FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="unused"))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_main_writer_prompt_adds_cron_api_when_requirement_analysis_marks_cron():
    writer = PromptMainFileCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        project_root_path=Path("/tmp/project"),
        graph_plan_json_path=Path("/tmp/project/graph_plan.json"),
        node_class_names=["FetchData", "SyncData"],
        nodes_package_name="example_agent",
        fastapi_host="0.0.0.0",
        fastapi_port=8000,
        uvicorn_reload=False,
        requirement_analysis_result={
            "is_cron_task": True,
            "task_type": "cron",
            "crontab_expression": "0 9 * * *",
        },
    )

    assert "GET /api/cron-config" in prompt
    assert "POST /api/cron-preview" in prompt
    assert "crontab_expression=0 9 * * *" in prompt


def test_frontend_writer_prompt_adds_cron_tab_when_requirement_analysis_marks_cron():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        steps_meta=[
            {
                "id": "FetchData",
                "title": "Fetch Data",
                "prompt": "Fetch",
                "dependencies": [],
                "services": [],
                "inputRequired": False,
                "nodeKind": "operation",
                "extData": {"type": "none", "desc": "", "inputs_format": {}},
            }
        ],
        run_step_endpoint="/api/run-step",
        reset_session_endpoint="/api/reset-session",
        requirement_analysis_result={
            "is_cron_task": True,
            "task_type": "cron",
            "crontab_expression": "0 9 * * *",
        },
        reference_frontend="<html></html>",
        node_ui_context="",
        graph_plan_context="{}",
    )

    assert "dedicated Cron tab" in prompt
    assert "GET /api/cron-config" in prompt
    assert "POST /api/cron-preview" in prompt


def test_writer_prompts_skip_cron_instructions_when_not_marked_cron():
    main_writer = PromptMainFileCoder(client=_FakeClient())
    frontend_writer = PromptFrontendCoder(client=_FakeClient())

    main_prompt = main_writer._build_user_prompt(
        project_root_path=Path("/tmp/project"),
        graph_plan_json_path=Path("/tmp/project/graph_plan.json"),
        node_class_names=["FetchData"],
        nodes_package_name="example_agent",
        fastapi_host="0.0.0.0",
        fastapi_port=8000,
        uvicorn_reload=False,
        requirement_analysis_result={"is_cron_task": False, "task_type": "general", "crontab_expression": None},
    )
    frontend_prompt = frontend_writer._build_user_prompt(
        steps_meta=[
            {
                "id": "FetchData",
                "title": "Fetch Data",
                "prompt": "Fetch",
                "dependencies": [],
                "services": [],
                "inputRequired": False,
                "nodeKind": "operation",
                "extData": {"type": "none", "desc": "", "inputs_format": {}},
            }
        ],
        run_step_endpoint="/api/run-step",
        reset_session_endpoint="/api/reset-session",
        requirement_analysis_result={"is_cron_task": False, "task_type": "general", "crontab_expression": None},
        reference_frontend="<html></html>",
        node_ui_context="",
        graph_plan_context="{}",
    )

    assert "/api/cron-config" not in main_prompt
    assert "Cron tab" not in frontend_prompt
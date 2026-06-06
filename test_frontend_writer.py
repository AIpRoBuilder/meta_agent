from types import SimpleNamespace

from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema
from meta_agent.worker.frontend_writer import PromptFrontendCoder


class _FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="<html></html>"))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_build_user_prompt_requires_unlock_based_progressive_reveal():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        steps_meta=[
            {
                "id": "collect",
                "title": "Collect Input",
                "prompt": "Collect the user's request",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "input",
                "extData": {"type": "user_input", "desc": "", "inputs_format": {}},
            },
            {
                "id": "process",
                "title": "Process Input",
                "prompt": "Process the request",
                "dependencies": ["collect"],
                "services": [],
                "inputRequired": False,
                "nodeKind": "operation",
                "extData": {"type": "none", "desc": "", "inputs_format": {}},
            },
        ],
        run_step_endpoint="/api/run-step",
        reset_session_endpoint="/api/reset-session",
        requirement_analysis_result=None,
        reference_frontend="<html></html>",
        node_ui_context="[missing]",
        graph_plan_context="{}",
        step_output_card_context="[]",
    )

    assert "reveal each later card only when that card becomes unlocked" in prompt
    assert "Do not gate card visibility on the previous card's STEP_FINISHED event alone." in prompt
    assert "reveal each next card only after the previous card has finished" not in prompt
    assert "renderCardSchemaSections" in prompt


def test_compile_node_file_and_get_step_output_card_schema_reads_card_shape(tmp_path):
    node_path = tmp_path / "CollectInput.py"
    node_path.write_text(
        """
from ag_ui_workflow.types import StepRunOutput
from ag_ui_workflow.nodes import WorkflowStepNode


class CollectInput(WorkflowStepNode):
    STEP_ID = "collect"
    TITLE = "Collect Input"

    def process_input(self, user_input, dependency_results, session_state):
        card = {
            "label": "Collection result",
            "rows": [
                {"name": "query", "value": user_input},
                {"name": "status", "value": "saved"},
            ],
            "actions": [
                {"label": "Review", "href": "/review"},
            ],
        }
        return StepRunOutput(summary="ok", card=card, derived={"query": user_input})
""".strip(),
        encoding="utf-8",
    )

    schema = compile_node_file_and_get_step_output_card_schema(str(node_path))

    assert schema is not None
    assert schema["step_id"] == "collect"
    assert schema["title"] == "Collect Input"
    assert schema["card"]["label"] == "Collection result"
    assert schema["card"]["rows"][0]["name"] == "query"
    assert schema["card"]["rows"][0]["value"] == "<user_input>"
    assert schema["card"]["actions"][0]["label"] == "Review"


def test_build_user_prompt_includes_step_output_card_context():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        steps_meta=[
            {
                "id": "collect",
                "title": "Collect Input",
                "prompt": "Collect the user's request",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "input",
                "extData": {"type": "user_input", "desc": "", "inputs_format": {}},
            }
        ],
        run_step_endpoint="/api/run-step",
        reset_session_endpoint="/api/reset-session",
        requirement_analysis_result=None,
        reference_frontend="<html></html>",
        node_ui_context="[missing]",
        graph_plan_context="{}",
        step_output_card_context='[{"stepId":"collect","card":{"label":"Collection result"}}]',
    )

    assert "Per-step StepRunOutput.card format context parsed from generated node files" in prompt
    assert '"stepId":"collect"' in prompt
    assert "Use the per-step StepRunOutput.card format context above to shape the response UI" in prompt
    assert "renderCardSchemaSections" in prompt


def test_build_user_prompt_includes_cron_trigger_requirements():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_user_prompt(
        steps_meta=[
            {
                "id": "collect",
                "title": "Collect Input",
                "prompt": "Collect the user's request",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "input",
                "extData": {"type": "user_input", "desc": "", "inputs_format": {}},
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
        node_ui_context="[missing]",
        graph_plan_context="{}",
        step_output_card_context="[]",
    )

    assert "Start Cron button" in prompt
    assert "POST /cron/start" in prompt
    assert "do not render per-step Run buttons" in prompt
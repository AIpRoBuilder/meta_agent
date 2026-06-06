import json

from meta_agent.auditor.frontend_auditor import FrontendAuditor


def test_audit_frontend_requires_schema_renderer_when_step_card_schema_exists(tmp_path):
    (tmp_path / "workflow.json").write_text(
        json.dumps({"nodes": [{"name": "CollectInput"}]}),
        encoding="utf-8",
    )
    (tmp_path / "CollectInput.py").write_text(
        """
from ag_ui_workflow.types import StepRunOutput
from ag_ui_workflow.nodes import WorkflowStepNode


class CollectInput(WorkflowStepNode):
    STEP_ID = "CollectInput"
    TITLE = "Collect Input"

    def process_input(self, user_input, dependency_results, session_state):
        card = {"label": "Result", "rows": [{"name": "query", "value": user_input}]}
        return StepRunOutput(summary="ok", card=card, derived={})
""".strip(),
        encoding="utf-8",
    )
    frontend_path = tmp_path / "frontend.html"
    frontend_path.write_text(
        "<html><body>/api/run-step /api/reset-session step_card sessionId</body></html>",
        encoding="utf-8",
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(frontend_path))

    assert ok is False
    assert any(v.rule == "step_output_schema_renderer_missing" for v in violations)


def test_audit_frontend_passes_with_schema_renderer_when_step_card_schema_exists(tmp_path):
    (tmp_path / "workflow.json").write_text(
        json.dumps({"nodes": [{"name": "CollectInput"}]}),
        encoding="utf-8",
    )
    (tmp_path / "CollectInput.py").write_text(
        """
from ag_ui_workflow.types import StepRunOutput
from ag_ui_workflow.nodes import WorkflowStepNode


class CollectInput(WorkflowStepNode):
    STEP_ID = "CollectInput"
    TITLE = "Collect Input"

    def process_input(self, user_input, dependency_results, session_state):
        card = {"label": "Result", "rows": [{"name": "query", "value": user_input}]}
        return StepRunOutput(summary="ok", card=card, derived={})
""".strip(),
        encoding="utf-8",
    )
    frontend_path = tmp_path / "frontend.html"
    frontend_path.write_text(
        "<html><body>/api/run-step /api/reset-session step_card sessionId renderCardSchemaSections</body></html>",
        encoding="utf-8",
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(frontend_path))

    assert ok is True
    assert violations == []


def test_audit_frontend_accepts_cron_start_endpoint(tmp_path):
    frontend_path = tmp_path / "frontend.html"
    frontend_path.write_text(
        "<html><body>/cron/start /api/reset-session step_card sessionId</body></html>",
        encoding="utf-8",
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(frontend_path))

    assert ok is True
    assert violations == []
import json
import subprocess

import meta_agent.auditor.frontend_auditor as frontend_auditor_module
from meta_agent.auditor.frontend_auditor import FrontendAuditor


def _write_required_frontend_src(
    tmp_path,
    *,
    app_text,
    workflow_nodes=None,
    include_schema_renderer=True,
    view_files=None,
    css_files=None,
):
    if workflow_nodes is None:
        workflow_nodes = []

    (tmp_path / "workflow.json").write_text(
        json.dumps({"nodes": workflow_nodes}),
        encoding="utf-8",
    )
    (tmp_path / "api").mkdir()
    (tmp_path / "store").mkdir()
    (tmp_path / "components").mkdir()
    (tmp_path / "views").mkdir()
    (tmp_path / "api" / "workflow.js").write_text(
        "export async function runStep() { return '/api/run-step' } export async function resetSession() { return '/api/reset-session' }",
        encoding="utf-8",
    )
    (tmp_path / "store" / "workflow.js").write_text(
        "const token = 'step_card'; const sessionId = 'demo';",
        encoding="utf-8",
    )
    app_shell_body = "renderCardSchemaSections" if include_schema_renderer else "workflow"
    (tmp_path / "components" / "AppShell.vue").write_text(
        f"<template><div>{app_shell_body}</div></template>",
        encoding="utf-8",
    )
    (tmp_path / "App.vue").write_text(app_text, encoding="utf-8")
    for view_name, view_text in (view_files or {}).items():
        (tmp_path / "views" / view_name).write_text(view_text, encoding="utf-8")
    if css_files:
        (tmp_path / "styles").mkdir(exist_ok=True)
        for css_name, css_text in css_files.items():
            (tmp_path / "styles" / css_name).write_text(css_text, encoding="utf-8")


def test_audit_frontend_requires_schema_renderer_when_step_card_schema_exists(tmp_path):
    (tmp_path / "workflow.json").write_text(
        json.dumps({"nodes": [{"name": "CollectInput"}]}),
        encoding="utf-8",
    )
    (tmp_path / "CollectInput.py").write_text(
        """
from ag_ui_workflow.workflow_types import StepRunOutput
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
from ag_ui_workflow.workflow_types import StepRunOutput
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


def test_audit_frontend_src_requires_schema_renderer_when_step_card_schema_exists(tmp_path):
    (tmp_path / "workflow.json").write_text(
        json.dumps({"nodes": [{"name": "CollectInput"}]}),
        encoding="utf-8",
    )
    (tmp_path / "CollectInput.py").write_text(
        """
from ag_ui_workflow.workflow_types import StepRunOutput
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
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
import CollectInput from './views/CollectInput.vue'
</script>
""".strip(),
        workflow_nodes=[{"name": "CollectInput"}],
        include_schema_renderer=False,
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is False
    assert any(v.rule == "step_output_schema_renderer_missing" for v in violations)


def test_audit_frontend_src_passes_with_required_tokens(tmp_path):
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is True
    assert violations == []


def test_audit_frontend_src_requires_app_shell_import_in_app_vue(tmp_path):
    _write_required_frontend_src(
        tmp_path,
        app_text="<script>import CollectInput from './views/CollectInput.vue'</script>",
        workflow_nodes=[{"name": "CollectInput"}],
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is False
    assert any(
        v.rule == "app_shell_import_missing" and v.class_name == str(tmp_path / "App.vue")
        for v in violations
    )


def test_audit_frontend_src_requires_app_vue_to_provide_app_shell_inject_keys(tmp_path):
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
    )
    (tmp_path / "components" / "AppShell.vue").write_text(
        """
<script>
export default {
    inject: ['workflowStore']
}
</script>
""".strip(),
        encoding="utf-8",
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is False
    assert any(
        v.rule == "app_shell_inject_not_provided"
        and "workflowStore" in v.detail
        and v.class_name == str(tmp_path / "App.vue")
        for v in violations
    )


def test_audit_frontend_src_accepts_app_shell_inject_keys_when_app_vue_provides_store_binding(tmp_path):
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'

export default {
    setup() {
        const store = {}
        provide('workflowStore', store)
        return { store }
    },
}
</script>
""".strip(),
    )
    (tmp_path / "components" / "AppShell.vue").write_text(
        """
<script>
export default {
    inject: ['workflowStore']
}
</script>
""".strip(),
        encoding="utf-8",
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is True
    assert violations == []


def test_audit_frontend_src_requires_all_graph_node_view_imports_in_app_vue(tmp_path):
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
import CollectInput from './views/CollectInput.vue'
</script>
""".strip(),
        workflow_nodes=[{"name": "CollectInput"}, {"name": "ReviewResult"}],
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is False
    assert any(
        v.rule == "app_view_import_missing"
        and "ReviewResult" in v.detail
        and v.class_name == str(tmp_path / "App.vue")
        for v in violations
    )


def test_audit_frontend_src_rejects_invalid_stores_workflow_store_import_in_views(tmp_path):
        _write_required_frontend_src(
                tmp_path,
                app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
                view_files={
                        "CollectInput.vue": """
<script>
import { useWorkflowStore } from '../stores/workflowStore'
export default {
    inject: ['workflowStore']
}
</script>
""".strip()
                },
        )

        ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

        assert ok is False
        assert any(v.rule == "view_store_import_invalid" for v in violations)


def test_audit_frontend_src_rejects_invalid_submit_step_signature_in_views(tmp_path):
        _write_required_frontend_src(
                tmp_path,
                app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
                view_files={
                        "CollectInput.vue": """
<script>
export default {
    methods: {
        runCurrentStep() {
            return this.workflowStore.submitStep(this.stepId)
        }
    }
}
</script>
""".strip()
                },
        )

        ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

        assert ok is False
        assert any(v.rule == "view_submit_step_signature_invalid" for v in violations)


def test_audit_frontend_src_accepts_expected_submit_step_signature_in_views(tmp_path):
        _write_required_frontend_src(
                tmp_path,
                app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
                view_files={
                        "CollectInput.vue": """
<script>
export default {
    methods: {
        runCurrentStep(userInput) {
            return this.workflowStore.submitStep(this.stepId, userInput)
        }
    }
}
</script>
""".strip()
                },
        )

        ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

        assert ok is True
        assert violations == []


def test_audit_frontend_src_uses_shared_graph_loader_from_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    frontend_src_dir = project_root / "frontend" / "src"
    frontend_src_dir.mkdir(parents=True)
    _write_required_frontend_src(
        frontend_src_dir,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
import CollectInput from './views/CollectInput.vue'
</script>
""".strip(),
        workflow_nodes=[{"name": "CollectInput"}],
    )
    (project_root / "workflow.json").write_text(
        json.dumps({"nodes": [{"name": "CollectInput"}]}),
        encoding="utf-8",
    )

    observed = {}

    def fake_load_graph_json(source):
        observed["source"] = source
        return {"nodes": [{"name": "CollectInput"}]}

    monkeypatch.setattr(frontend_auditor_module, "_load_graph_json", fake_load_graph_json)

    ok, violations = FrontendAuditor(base_dir=project_root).audit_frontend_file(str(frontend_src_dir))

    assert observed["source"] == project_root / "workflow.json"
    assert ok is True
    assert violations == []


def test_audit_frontend_lint_errors_returns_file_error_map_from_eslint_json(tmp_path, monkeypatch):
    frontend_project_dir = tmp_path / "frontend"
    frontend_src_dir = frontend_project_dir / "src"
    frontend_src_dir.mkdir(parents=True)
    (frontend_project_dir / "package.json").write_text("{}", encoding="utf-8")

    lint_stdout = json.dumps(
        [
            {
                "filePath": str(frontend_src_dir / "App.vue"),
                "messages": [
                    {
                        "ruleId": "semi",
                        "severity": 2,
                        "message": "Missing semicolon.",
                        "line": 2,
                        "column": 10,
                    },
                    {
                        "ruleId": "no-unused-vars",
                        "severity": 1,
                        "message": "Unused variable.",
                        "line": 3,
                        "column": 2,
                    },
                ],
            }
        ]
    )

    def fake_run(command, cwd, capture_output, text, check):
        assert command[1:] == ["run", "lint", "--", "--format", "json"]
        assert command[0] == "npm" or command[0].endswith("/npm")
        assert cwd == str(frontend_project_dir)
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(command, 1, stdout=lint_stdout, stderr="")

    monkeypatch.setattr(frontend_auditor_module.subprocess, "run", fake_run)

    lint_errors = FrontendAuditor().audit_frontend_lint_errors(str(frontend_src_dir))

    assert lint_errors == {
        str(frontend_src_dir / "App.vue"): "line 2, col 10: Missing semicolon. (semi)"
    }


def test_parse_eslint_json_output_ignores_prefixed_npm_output():
    log_text = """

/Users/xiechuxi/Desktop/codes/WorkGear/data/frontend/src/components/AppShell.vue
  48:21  error  This 'v-if' should be moved to the wrapper element  vue/no-use-v-if-with-v-for

/Users/xiechuxi/Desktop/codes/WorkGear/data/frontend/src/store/workflow.js
  185:12  error 'ensureConversationAssistantEntry' is defined but never used  no-unused-vars

[{"filePath":"/Users/xiechuxi/Desktop/codes/WorkGear/data/frontend/src/components/AppShell.vue","messages":[{"ruleId":"vue/no-use-v-if-with-v-for","severity":2,"message":"This 'v-if' should be moved to the wrapper element","line":48,"column":21}]},{"filePath":"/Users/xiechuxi/Desktop/codes/WorkGear/data/frontend/src/store/workflow.js","messages":[{"ruleId":"no-unused-vars","severity":2,"message":"'ensureConversationAssistantEntry' is defined but never used.","line":185,"column":12}]}]
""".strip()

    lint_errors = FrontendAuditor._parse_eslint_json_output(log_text)

    assert lint_errors == {
        "/Users/xiechuxi/Desktop/codes/WorkGear/data/frontend/src/components/AppShell.vue": (
            "line 48, col 21: This 'v-if' should be moved to the wrapper element "
            "(vue/no-use-v-if-with-v-for)"
        ),
        "/Users/xiechuxi/Desktop/codes/WorkGear/data/frontend/src/store/workflow.js": (
            "line 185, col 12: 'ensureConversationAssistantEntry' is defined but never used. "
            "(no-unused-vars)"
        ),
    }


def test_audit_frontend_lint_errors_falls_back_to_stylish_output(tmp_path, monkeypatch):
    frontend_project_dir = tmp_path / "frontend"
    frontend_src_dir = frontend_project_dir / "src"
    frontend_src_dir.mkdir(parents=True)
    (frontend_project_dir / "package.json").write_text("{}", encoding="utf-8")

    stylish_stderr = """
/tmp/project/frontend/src/App.vue
  2:10  error  Missing semicolon  semi
  3:4   error  Unexpected console statement  no-console
""".strip()

    def fake_run(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=stylish_stderr)

    monkeypatch.setattr(frontend_auditor_module.subprocess, "run", fake_run)

    lint_errors = FrontendAuditor().audit_frontend_lint_errors(str(frontend_src_dir))

    assert lint_errors == {
        "/tmp/project/frontend/src/App.vue": (
            "2:10  error  Missing semicolon  semi\n"
            "3:4   error  Unexpected console statement  no-console"
        )
    }


def test_audit_frontend_lint_errors_skips_when_lint_script_is_missing(tmp_path, monkeypatch):
    frontend_project_dir = tmp_path / "frontend"
    frontend_src_dir = frontend_project_dir / "src"
    frontend_src_dir.mkdir(parents=True)
    (frontend_project_dir / "package.json").write_text("{}", encoding="utf-8")

    npm_stderr = 'npm ERR! Missing script: "lint"'

    def fake_run(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=npm_stderr)

    monkeypatch.setattr(frontend_auditor_module.subprocess, "run", fake_run)

    lint_errors = FrontendAuditor().audit_frontend_lint_errors(str(frontend_src_dir))

    assert lint_errors == {}


def test_audit_frontend_src_reports_lint_errors_as_rule_violations(tmp_path, monkeypatch):
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
    )

    monkeypatch.setattr(
        FrontendAuditor,
        "audit_frontend_lint_errors",
        lambda self, frontend_path: {
            str(tmp_path / "App.vue"): "line 7, col 3: Missing semicolon. (semi)"
        },
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is False
    expected_path = str(tmp_path / "App.vue")
    assert any(
        v.class_name == expected_path
        and
        v.rule == "frontend_lint_error"
        and v.lineno == 7
        and expected_path in v.detail
        and "Missing semicolon." in v.detail
        for v in violations
    )


def test_audit_frontend_src_rejects_this_dollar_set_syntax(tmp_path):
    _write_required_frontend_src(
        tmp_path,
        app_text="""
<script>
import AppShell from './components/AppShell.vue'
export default {
    methods: {
        updateState() {
            this.$set(this, 'status', 'done')
        }
    }
}
</script>
""".strip(),
    )

    ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

    assert ok is False
    assert any(v.rule == "vue_set_syntax_forbidden" for v in violations)


def test_audit_frontend_src_rejects_invalid_css_syntax(tmp_path):
        _write_required_frontend_src(
                tmp_path,
                app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
                css_files={
                        "app.css": """
.panel {
    color: #333;
""".strip()
                },
        )

        ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

        assert ok is False
        assert any(v.rule == "frontend_css_syntax_error" for v in violations)


def test_audit_frontend_src_accepts_valid_css_syntax(tmp_path):
        _write_required_frontend_src(
                tmp_path,
                app_text="""
<script>
import AppShell from './components/AppShell.vue'
</script>
""".strip(),
                css_files={
                        "app.css": """
.panel {
    color: #333;
}

@media (max-width: 640px) {
    .panel {
        color: #111;
    }
}
""".strip()
                },
        )

        ok, violations = FrontendAuditor().audit_frontend_file(str(tmp_path))

        assert ok is True
        assert violations == []
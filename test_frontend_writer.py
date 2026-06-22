from pathlib import Path
from types import SimpleNamespace

from meta_agent.architect.graph import NodeMeta
import meta_agent.worker.frontend_writer as frontend_writer_module
from meta_agent.tools.file_tools import compile_node_file_and_get_step_output_card_schema
from meta_agent.worker.frontend_view_writer import FrontendViewCoder
from meta_agent.worker.frontend_writer import PromptFrontendCoder


class _FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="<html></html>"))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def _write_reference_frontend_src(base_dir):
    (base_dir / "api").mkdir(parents=True, exist_ok=True)
    (base_dir / "store").mkdir(parents=True, exist_ok=True)
    (base_dir / "components").mkdir(parents=True, exist_ok=True)
    (base_dir / "styles").mkdir(parents=True, exist_ok=True)
    (base_dir / "api" / "workflow.js").write_text("export async function runStep() {}", encoding="utf-8")
    (base_dir / "store" / "workflow.js").write_text("export function createWorkflowStore() {}", encoding="utf-8")
    (base_dir / "components" / "AppShell.vue").write_text("<template></template>", encoding="utf-8")
    (base_dir / "styles" / "app.css").write_text(":root {}", encoding="utf-8")
    (base_dir / "App.vue").write_text("<template><AppShell /></template>", encoding="utf-8")


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


def test_build_api_user_prompt_includes_sse_and_reset_requirements():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_api_user_prompt(
        run_step_endpoint="/api/run-step",
        reset_session_endpoint="/api/reset-session",
        reference_api_source="export async function runStep() {}",
        requirement_analysis_result=None,
    )

    assert "frontend/src/api/workflow.js" in prompt
    assert "Export runStep(payload, onEvent) targeting /api/run-step." in prompt
    assert "Export resetSession(sessionId) targeting /api/reset-session." in prompt
    assert "handle lines starting with 'data: '" in prompt


def test_build_store_user_prompt_includes_store_contracts():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_store_user_prompt(
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
        reference_store_source="export function createWorkflowStore() {}",
        graph_plan_context="{}",
        step_output_card_context='[{"stepId":"collect","card":{"label":"Collection result"}}]',
    )

    assert "frontend/src/store/workflow.js" in prompt
    assert "export createWorkflowStore()".lower() in prompt.lower()
    assert "CUSTOM with name='step_card'" in prompt
    assert "never use this.$set or Vue.set" in prompt
    assert '"id": "collect"' in prompt


def test_build_app_shell_user_prompt_includes_schema_and_file_input_requirements():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_app_shell_user_prompt(
        steps_meta=[
            {
                "id": "collect",
                "title": "Collect Input",
                "prompt": "Collect the user's request",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "file",
                "extData": {"type": "user_file_input", "desc": "", "inputs_format": {}},
            }
        ],
        store_workflow_source="export function createWorkflowStore() {}",
        reference_app_shell_source="<template></template>",
        node_view_template_context="=== Collect.vue ===\n<template><section>Collect</section></template>",
        step_output_card_context='[{"stepId":"collect","card":{"label":"Collection result"}}]',
    )

    assert "frontend/src/components/AppShell.vue" in prompt
    assert "Store workflow.js context" in prompt
    assert "export function createWorkflowStore() {}" in prompt
    assert "Node view template context from frontend/src/views/{Node}.vue" in prompt
    assert "<template><section>Collect</section></template>" in prompt
    assert "renderCardSchemaSections" in prompt
    assert "Never use this.$set or Vue.set" in prompt
    assert "conversation bar centered along the middle bottom of the page" in prompt
    assert "call workflowStore.submitStep(stepId, payload) so the request flows to /api/run-step" in prompt
    assert "serialize files into JSON strings shaped like {files:[{fileName,bytes},...]} before submission" in prompt
    assert "Graph plan JSON context" not in prompt


def test_build_app_css_user_prompt_includes_style_guidance():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_app_css_user_prompt(
        reference_app_css_source=":root {}",
        node_style_context="=== CollectInput.css ===\n.collect { color: red; }",
        frontend_style_prompt="Use a warm neutral palette with strong contrast.",
    )

    assert "frontend/src/styles/app.css" in prompt
    assert "Node stylesheet context from frontend/src/styles/{Node}.css" in prompt
    assert ".collect { color: red; }" in prompt
    assert "User-defined frontend style guidance" in prompt
    assert "warm neutral palette" in prompt


def test_build_app_vue_user_prompt_includes_generated_context_requirements():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_app_vue_user_prompt(
        node_names=["CollectInput", "ReviewResult"],
        reference_app_source="<template><AppShell /></template>",
        generated_api_source="export async function runStep() {}",
        generated_store_source="export function createWorkflowStore() {}",
        generated_app_shell_source="<template></template>",
    )

    assert "frontend/src/App.vue" in prompt
    assert "Import createWorkflowStore from ./store/workflow" in prompt
    assert "AppShell from './components/AppShell.vue'" in prompt
    assert "Import one node view component per visible graph node name" in prompt
    assert "Visible graph node names for imports" in prompt
    assert "./views/<NodeName>.vue" in prompt
    assert '"CollectInput"' in prompt


def test_frontend_view_prompt_prioritizes_literal_html_reuse():
    writer = FrontendViewCoder(client=_FakeClient())

    prompt = writer._build_vue_user_prompt(
        node_name="CollectInput",
        node_meta=NodeMeta(name="CollectInput", type="", desc="Collect Input"),
        graph_plan_context='{"nodes":[]}',
        node_html_context='<section class="collect"><button type="button">Run</button></section>',
        node_python_context='def process_input():\n    return "ok"',
        style_filename="CollectInput.css",
    )

    assert "preserve it as literally as possible" in prompt
    assert "Never use this.$set or Vue.set" in prompt
    assert "Keep the same tag hierarchy, section ordering, class names, attributes, and visible text" in prompt
    assert "Do not redesign, summarize, or replace the HTML context with a different layout" in prompt
    assert "append or minimally wrap the existing HTML instead of rewriting the original structure" in prompt
    assert "Never import workflowStore or createWorkflowStore from ../stores/workflowStore or ../store/workflow" in prompt


def test_frontend_view_prompt_includes_file_upload_backend_payload_contract():
    writer = FrontendViewCoder(client=_FakeClient())

    prompt = writer._build_vue_user_prompt(
        node_name="UploadFiles",
        node_meta=NodeMeta(
            name="UploadFiles",
            type="",
            desc="",
            ext_data={"type": "user_file_input", "desc": "Upload source files"},
        ),
        graph_plan_context='{"nodes":[]}',
        node_html_context='<section class="upload"><input type="file" multiple></section>',
        node_python_context='def save_files_remote():\n    return "ok"',
        style_filename="UploadFiles.css",
    )

    assert "ext_data.type='user_file_input'" in prompt
    assert '{"files":[{"fileName":"new_file","bytes":"sdsdsk"}]}' in prompt
    assert "use real uploaded file names and file bytes encoded to a string value" in prompt


def test_frontend_view_writer_skips_nodes_with_show_frontend_disabled(tmp_path, monkeypatch):
    writer = FrontendViewCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    output_dir = tmp_path / "frontend" / "src"
    context_dir.mkdir()
    (context_dir / "VisibleNode.html").write_text("<section>Visible</section>", encoding="utf-8")
    (context_dir / "VisibleNode.py").write_text("def run():\n    return 'visible'\n", encoding="utf-8")

    observed_paths = []

    def fake_code_to_file(user_prompt, output_file, **kwargs):
        observed_paths.append(Path(output_file))
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text("generated", encoding="utf-8")
        return Path(output_file)

    monkeypatch.setattr(writer, "code_to_file", fake_code_to_file)

    result = writer.write_graph_node_files(
        graph_plan={
            "nodes": [
                {"name": "VisibleNode", "desc": "visible", "show_frontend": True},
                {"name": "HiddenNode", "desc": "hidden", "show_frontend": False},
            ]
        },
        context_base_dir=str(context_dir),
        output_base_dir=str(output_dir),
    )

    assert set(result.keys()) == {"VisibleNode"}
    assert all("HiddenNode" not in str(path) for path in observed_paths)


def test_write_app_file_uses_workflow_json_with_resolved_base_dir(tmp_path, monkeypatch):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    output_path = tmp_path / "frontend" / "src" / "App.vue"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    expected_path = context_dir / "workflow.json"
    expected_path.write_text('{"nodes": [{"name": "CollectInput"}]}', encoding="utf-8")
    (output_path.parent / "api").mkdir(parents=True)
    (output_path.parent / "store").mkdir(parents=True)
    (output_path.parent / "components").mkdir(parents=True)
    (output_path.parent / "api" / "workflow.js").write_text("export async function runStep() {}", encoding="utf-8")
    (output_path.parent / "store" / "workflow.js").write_text("export function createWorkflowStore() {}", encoding="utf-8")
    (output_path.parent / "components" / "AppShell.vue").write_text("<template></template>", encoding="utf-8")

    observed = {}

    def fake_code_to_file(user_prompt, output_file, **kwargs):
        observed["user_prompt"] = user_prompt
        return Path(output_file)

    monkeypatch.setattr(writer, "code_to_file", fake_code_to_file)

    result = writer.write_app_file(
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
        output_path=output_path,
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
    )

    assert '"CollectInput"' in observed["user_prompt"]
    assert result == output_path


def test_write_app_file_skips_nodes_with_show_frontend_disabled(tmp_path, monkeypatch):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    output_path = tmp_path / "frontend" / "src" / "App.vue"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    (context_dir / "workflow.json").write_text(
        '{"nodes": [{"name": "VisibleNode", "show_frontend": true}, {"name": "HiddenNode", "show_frontend": false}]}',
        encoding="utf-8",
    )
    (output_path.parent / "api").mkdir(parents=True)
    (output_path.parent / "store").mkdir(parents=True)
    (output_path.parent / "components").mkdir(parents=True)
    (output_path.parent / "api" / "workflow.js").write_text("export async function runStep() {}", encoding="utf-8")
    (output_path.parent / "store" / "workflow.js").write_text("export function createWorkflowStore() {}", encoding="utf-8")
    (output_path.parent / "components" / "AppShell.vue").write_text("<template></template>", encoding="utf-8")

    observed = {}

    def fake_code_to_file(user_prompt, output_file, **kwargs):
        observed["user_prompt"] = user_prompt
        return Path(output_file)

    monkeypatch.setattr(writer, "code_to_file", fake_code_to_file)

    writer.write_app_file(
        steps_meta=[
            {
                "id": "visible",
                "title": "Visible",
                "prompt": "Visible",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "input",
                "extData": {"type": "user_input", "desc": "", "inputs_format": {}},
            }
        ],
        output_path=output_path,
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
    )

    assert '"VisibleNode"' in observed["user_prompt"]
    assert '"HiddenNode"' not in observed["user_prompt"]


def test_write_app_shell_vue_file_writes_reference_app_css(tmp_path, monkeypatch):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    output_path = tmp_path / "frontend" / "src" / "components" / "AppShell.vue"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    (context_dir / "workflow.json").write_text('{"nodes": []}', encoding="utf-8")
    (context_dir / "node_ui").mkdir()

    def fake_code_to_file(user_prompt, output_file, **kwargs):
        return Path(output_file)

    monkeypatch.setattr(writer, "code_to_file", fake_code_to_file)

    result = writer.write_app_shell_vue_file(
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
        output_path=output_path,
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
    )

    assert (output_path.parent.parent / "styles" / "app.css").read_text(encoding="utf-8") == ":root {}"
    assert result == output_path


def test_write_app_shell_vue_file_generates_app_css_when_style_prompt_is_present(tmp_path, monkeypatch):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    output_path = tmp_path / "frontend" / "src" / "components" / "AppShell.vue"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    (context_dir / "workflow.json").write_text('{"nodes": []}', encoding="utf-8")
    (context_dir / "node_ui").mkdir()
    (output_path.parent.parent / "styles").mkdir(parents=True)
    (output_path.parent.parent / "styles" / "CollectInput.css").write_text(
        ".collect-input { padding: 12px; }",
        encoding="utf-8",
    )

    observed_calls = []

    def fake_code_to_file(user_prompt, output_file, **kwargs):
        observed_calls.append((user_prompt, Path(output_file)))
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text("generated", encoding="utf-8")
        return Path(output_file)

    monkeypatch.setattr(writer, "code_to_file", fake_code_to_file)

    result = writer.write_app_shell_vue_file(
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
        output_path=output_path,
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
        frontend_style_prompt="Use a newsroom aesthetic.",
    )

    assert len(observed_calls) == 2
    assert observed_calls[0][1] == output_path.parent.parent / "styles" / "app.css"
    assert "Node stylesheet context from frontend/src/styles/{Node}.css" in observed_calls[0][0]
    assert ".collect-input { padding: 12px; }" in observed_calls[0][0]
    assert "User-defined frontend style guidance" in observed_calls[0][0]
    assert observed_calls[1][1] == output_path
    assert result == output_path


def test_write_app_shell_vue_file_includes_generated_store_and_view_template_context(tmp_path, monkeypatch):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    output_path = tmp_path / "frontend" / "src" / "components" / "AppShell.vue"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    (context_dir / "workflow.json").write_text('{"nodes": []}', encoding="utf-8")
    (output_path.parent.parent / "store").mkdir(parents=True)
    (output_path.parent.parent / "views").mkdir(parents=True)
    (output_path.parent.parent / "store" / "workflow.js").write_text(
        "export function createWorkflowStore() { return { steps: [] } }",
        encoding="utf-8",
    )
    (output_path.parent.parent / "views" / "CollectInput.vue").write_text(
        "<template><section class=\"collect\">Collect</section></template>\n<script>export default {}</script>",
        encoding="utf-8",
    )

    observed = {}

    def fake_code_to_file(user_prompt, output_file, **kwargs):
        if Path(output_file) == output_path:
            observed["prompt"] = user_prompt
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text("generated", encoding="utf-8")
        return Path(output_file)

    monkeypatch.setattr(writer, "code_to_file", fake_code_to_file)

    writer.write_app_shell_vue_file(
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
        output_path=output_path,
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
    )

    assert "Store workflow.js context" in observed["prompt"]
    assert "return { steps: [] }" in observed["prompt"]
    assert "Node view template context from frontend/src/views/{Node}.vue" in observed["prompt"]
    assert "=== CollectInput.vue ===" in observed["prompt"]
    assert "<template><section class=\"collect\">Collect</section></template>" in observed["prompt"]


def test_write_frontend_src_files_writes_requested_targets(tmp_path):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    (context_dir / "workflow.json").write_text('{"nodes": []}', encoding="utf-8")
    (context_dir / "node_ui").mkdir()

    output = writer.write_frontend_src_files(
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
        output_base_dir=tmp_path / "frontend" / "src",
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
    )

    assert output["api"].name == "workflow.js"
    assert output["store"].name == "workflow.js"
    assert output["app_shell"].name == "AppShell.vue"
    assert output["app"].name == "App.vue"
    assert output["app_css"].name == "app.css"
    assert output["api"].parent.name == "api"
    assert output["store"].parent.name == "store"
    assert output["app_shell"].parent.name == "components"
    assert output["app"].parent.name == "src"
    assert output["app_css"].parent.name == "styles"
    assert output["app_css"].read_text(encoding="utf-8") == ":root {}"


def test_write_frontend_src_files_uses_store_steps_meta_when_provided(tmp_path, monkeypatch):
    writer = PromptFrontendCoder(client=_FakeClient())
    context_dir = tmp_path / "context"
    reference_dir = tmp_path / "reference" / "src"
    context_dir.mkdir()
    _write_reference_frontend_src(reference_dir)
    (context_dir / "workflow.json").write_text('{"nodes": []}', encoding="utf-8")
    (context_dir / "node_ui").mkdir()

    observed = {}

    def fake_write_store_workflow_file(*, steps_meta, output_path, **kwargs):
        observed["store_steps_meta"] = steps_meta
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("export const STEP_METADATA = []", encoding="utf-8")
        return Path(output_path)

    monkeypatch.setattr(writer, "write_store_workflow_file", fake_write_store_workflow_file)

    writer.write_frontend_src_files(
        steps_meta=[
            {
                "id": "VisibleNode",
                "title": "Visible",
                "prompt": "Visible",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "input",
                "extData": {"type": "user_input", "desc": "", "inputs_format": {}},
            }
        ],
        store_steps_meta=[
            {
                "id": "VisibleNode",
                "title": "Visible",
                "prompt": "Visible",
                "dependencies": [],
                "services": [],
                "inputRequired": True,
                "nodeKind": "input",
                "extData": {"type": "user_input", "desc": "", "inputs_format": {}},
            },
            {
                "id": "HiddenNode",
                "title": "Hidden",
                "prompt": "Hidden",
                "dependencies": ["VisibleNode"],
                "services": [],
                "inputRequired": False,
                "nodeKind": "operation",
                "extData": {"type": "none", "desc": "no need for ext data", "inputs_format": {}},
            },
        ],
        output_base_dir=tmp_path / "frontend" / "src",
        context_base_dir=str(context_dir),
        reference_frontend_src_dir=str(reference_dir),
    )

    assert [step["id"] for step in observed["store_steps_meta"]] == ["VisibleNode", "HiddenNode"]


def test_detect_frontend_file_kind_supports_node_view_vue_paths():
    writer = PromptFrontendCoder(client=_FakeClient())

    file_kind = writer._detect_frontend_file_kind(Path("/tmp/frontend/src/views/CollectInput.vue"))

    assert file_kind == "view"


def test_build_amendment_prompt_includes_view_contract_for_node_vue_files():
    writer = PromptFrontendCoder(client=_FakeClient())

    prompt = writer._build_amendment_prompt(
        file_path=Path("/tmp/frontend/src/views/CollectInput.vue"),
        original_code="<template><section class=\"collect\">Run</section></template>",
        rule_violations="Line 1: vue/no-unused-vars - Remove unused variable",
    )

    assert "Preserve the views/<Node>.vue contract" in prompt
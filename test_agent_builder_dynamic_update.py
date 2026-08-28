import json
from pathlib import Path

import meta_agent.agent_builder as agent_builder_module
from meta_agent.agent_builder import AgentBuilder


class _FakeComponent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _make_builder(monkeypatch, tmp_path: Path) -> AgentBuilder:
    monkeypatch.setattr(agent_builder_module, "RequirementDisector", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "GraphPlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "NodePlanner", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptMainFileCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "PromptFrontendCoder", _FakeComponent)
    monkeypatch.setattr(agent_builder_module, "FrontendViewCoder", _FakeComponent)
    return AgentBuilder(
        api_key="key",
        model="model",
        provider="provider",
        root_dir=str(tmp_path),
    )


def test_builder_progress_logs_to_runtime_file(monkeypatch, tmp_path):
    builder = _make_builder(monkeypatch, tmp_path)

    builder._start_progress(3)

    log_path = Path(builder.runtime_log_path)
    assert log_path.is_file()

    log_text = log_path.read_text(encoding="utf-8")
    assert "Pipeline started. Total steps: 3" in log_text
    assert "Initializing" in log_text


def _write_graph(graph_path: Path, nodes: list[dict]) -> None:
    graph_path.write_text(json.dumps({"nodes": nodes}, ensure_ascii=False, indent=2), encoding="utf-8")


def test_update_nodes_plan_preserves_existing_files_and_generates_only_missing(monkeypatch, tmp_path):
    builder = _make_builder(monkeypatch, tmp_path)

    requirement_path = tmp_path / "requirement.md"
    requirement_path.write_text("# Requirement\n", encoding="utf-8")
    graph_path = tmp_path / "graph_plan.json"
    _write_graph(
        graph_path,
        [
            {
                "name": "ExistingNode",
                "type": "WorkflowOperationNode",
                "desc": "existing",
                "show_frontend": True,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "none", "desc": "none"},
            },
            {
                "name": "AddedNode",
                "type": "WorkflowOperationNode",
                "desc": "added",
                "show_frontend": True,
                "enable": True,
                "depends": ["ExistingNode"],
                "ext_data": {"type": "none", "desc": "none"},
            },
            {
                "name": "HiddenNode",
                "type": "WorkflowOperationNode",
                "desc": "hidden",
                "show_frontend": False,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "none", "desc": "none"},
            },
        ],
    )

    existing_plan_path = tmp_path / "node_docs" / "ExistingNode.md"
    existing_plan_path.parent.mkdir(parents=True, exist_ok=True)
    existing_plan_path.write_text("existing plan\n", encoding="utf-8")

    existing_ui_path = tmp_path / "node_ui" / "ExistingNode.html"
    existing_ui_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ui_path.write_text("<div>existing ui</div>\n", encoding="utf-8")

    class _FakeNodePlanner:
        def __init__(self):
            self.plan_payloads = []
            self.ui_payloads = []

        def plan_each(self, *, requirement_text, graph_plan_text, output_dir, **kwargs):
            payload = json.loads(graph_plan_text)
            self.plan_payloads.append(payload)
            written = []
            for node in payload["nodes"]:
                path = Path(output_dir) / f"{node['name']}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {node['name']}\n", encoding="utf-8")
                written.append(path)
            return written

        def plan_each_ui(self, *, requirement_text, graph_plan_text, output_dir, **kwargs):
            payload = json.loads(graph_plan_text)
            self.ui_payloads.append(payload)
            written = []
            for node in payload["nodes"]:
                path = Path(output_dir) / f"{node['name']}.html"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"<div>{node['name']}</div>\n", encoding="utf-8")
                written.append(path)
            return written

    builder.node_planner = _FakeNodePlanner()
    builder.requirement_md_path = str(requirement_path)
    builder.graph_plan_path = str(graph_path)

    result = builder.update_nodes_plan()

    assert existing_plan_path.read_text(encoding="utf-8") == "existing plan\n"
    assert existing_ui_path.read_text(encoding="utf-8") == "<div>existing ui</div>\n"
    assert (tmp_path / "node_docs" / "AddedNode.md").is_file()
    assert (tmp_path / "node_docs" / "HiddenNode.md").is_file()
    assert (tmp_path / "node_ui" / "AddedNode.html").is_file()
    assert not (tmp_path / "node_ui" / "HiddenNode.html").exists()
    assert [node["name"] for node in builder.node_planner.plan_payloads[0]["nodes"]] == ["AddedNode", "HiddenNode"]
    assert [node["name"] for node in builder.node_planner.ui_payloads[0]["nodes"]] == ["AddedNode"]
    assert result["node_plan"]["existing"] == {"ExistingNode": str(existing_plan_path)}
    assert set(result["node_plan"]["generated"]) == {"AddedNode", "HiddenNode"}
    assert set(builder.dynamic_graph_cache["node_plans"]) == {"ExistingNode", "AddedNode", "HiddenNode"}
    assert set(builder.dynamic_graph_cache["node_ui"]) == {"ExistingNode", "AddedNode"}


def test_update_nodes_generates_only_missing_backend_and_frontend_nodes(monkeypatch, tmp_path):
    builder = _make_builder(monkeypatch, tmp_path)

    requirement_path = tmp_path / "requirement.md"
    requirement_path.write_text("# Requirement\n", encoding="utf-8")
    graph_path = tmp_path / "graph_plan.json"
    _write_graph(
        graph_path,
        [
            {
                "name": "ExistingNode",
                "type": "WorkflowOperationNode",
                "desc": "existing",
                "show_frontend": True,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "none", "desc": "none"},
            },
            {
                "name": "AddedNode",
                "type": "WorkflowOperationNode",
                "desc": "added",
                "show_frontend": True,
                "enable": True,
                "depends": ["ExistingNode"],
                "ext_data": {"type": "none", "desc": "none"},
            },
        ],
    )

    (tmp_path / "node_docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_ui").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "src" / "views").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "src" / "styles").mkdir(parents=True, exist_ok=True)

    (tmp_path / "node_docs" / "ExistingNode.md").write_text("existing plan\n", encoding="utf-8")
    (tmp_path / "node_ui" / "ExistingNode.html").write_text("<div>existing ui</div>\n", encoding="utf-8")
    (tmp_path / "ExistingNode.py").write_text("class ExistingNode: ...\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "views" / "ExistingNode.vue").write_text("<template>existing</template>\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "styles" / "ExistingNode.css").write_text(".existing {}\n", encoding="utf-8")

    class _FakeNodePlanner:
        def plan_each(self, *, requirement_text, graph_plan_text, output_dir, **kwargs):
            payload = json.loads(graph_plan_text)
            written = []
            for node in payload["nodes"]:
                path = Path(output_dir) / f"{node['name']}.md"
                path.write_text(f"# {node['name']}\n", encoding="utf-8")
                written.append(path)
            return written

        def plan_each_ui(self, *, requirement_text, graph_plan_text, output_dir, **kwargs):
            payload = json.loads(graph_plan_text)
            written = []
            for node in payload["nodes"]:
                path = Path(output_dir) / f"{node['name']}.html"
                path.write_text(f"<div>{node['name']}</div>\n", encoding="utf-8")
                written.append(path)
            return written

    class _FakeFrontendAuditor:
        def audit_frontend_file(self, frontend_path):
            return True, []

    class _FakeFrontendWriter:
        def __init__(self):
            self.calls = []

        def write_frontend_src_files(self, **kwargs):
            self.calls.append(kwargs)
            base_dir = Path(kwargs["output_base_dir"])
            api_path = base_dir / "api" / "workflow.js"
            store_path = base_dir / "store" / "workflow.js"
            app_shell_path = base_dir / "components" / "AppShell.vue"
            app_path = base_dir / "App.vue"
            app_css_path = base_dir / "styles" / "app.css"
            for path in [api_path, store_path, app_shell_path, app_path, app_css_path]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"// {path.name}\n", encoding="utf-8")
            return {
                "api": api_path,
                "store": store_path,
                "app_shell": app_shell_path,
                "app": app_path,
                "app_css": app_css_path,
            }

    backend_calls = []
    frontend_calls = []
    main_calls = []

    def fake_generate_selected_nodes(node_names, *, language="python", temperature=0.3, reset_mappings=False):
        backend_calls.append(list(node_names))
        written = []
        for node_name in node_names:
            path = tmp_path / f"{node_name}.py"
            path.write_text(f"class {node_name}: ...\n", encoding="utf-8")
            written.append(str(path))
        builder.node_location_map = {Path(path).stem: path for path in written}
        return written

    def fake_generate_selected_frontend_views(node_names, *, output_base_dir, context_base_dir=None, temperature=0.3, overwrite_existing=False):
        frontend_calls.append(list(node_names))
        base_dir = Path(output_base_dir)
        (base_dir / "views").mkdir(parents=True, exist_ok=True)
        (base_dir / "styles").mkdir(parents=True, exist_ok=True)
        generated = {}
        for node_name in node_names:
            view_path = base_dir / "views" / f"{node_name}.vue"
            style_path = base_dir / "styles" / f"{node_name}.css"
            view_path.write_text(f"<template>{node_name}</template>\n", encoding="utf-8")
            style_path.write_text(f".{node_name.lower()} {{}}\n", encoding="utf-8")
            generated[node_name] = {"view": str(view_path), "style": str(style_path)}
        return generated

    def fake_ensure_vue_frontend_project(frontend_output_dir, backend_port=8000):
        frontend_dir = tmp_path / frontend_output_dir
        frontend_dir.mkdir(parents=True, exist_ok=True)
        (frontend_dir / "src").mkdir(parents=True, exist_ok=True)
        (frontend_dir / "package.json").write_text("{}\n", encoding="utf-8")
        return str(frontend_dir)

    def fake_generate_main_entrypoint(graph_plan_path, output_filename="main.py", fastapi_host="0.0.0.0", temperature=0.0, fastapi_port=8000):
        main_calls.append(
            {
                "graph_plan_path": graph_plan_path,
                "output_filename": output_filename,
                "fastapi_port": fastapi_port,
            }
        )
        output_path = Path(output_filename)
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("print('main')\n", encoding="utf-8")
        builder.main_output_path = str(output_path)
        return str(output_path)

    builder.node_planner = _FakeNodePlanner()
    builder.frontend_auditor = _FakeFrontendAuditor()
    builder.frontend_writer = _FakeFrontendWriter()
    builder._generate_selected_nodes = fake_generate_selected_nodes
    builder._generate_selected_frontend_views = fake_generate_selected_frontend_views
    builder._ensure_vue_frontend_project = fake_ensure_vue_frontend_project
    builder.generate_main_entrypoint = fake_generate_main_entrypoint
    builder.requirement_md_path = str(requirement_path)
    builder.graph_plan_path = str(graph_path)

    result = builder.update_nodes(backend_port=8123)

    assert backend_calls == [["AddedNode"]]
    assert frontend_calls == [["AddedNode"]]
    assert (tmp_path / "ExistingNode.py").read_text(encoding="utf-8") == "class ExistingNode: ...\n"
    assert (tmp_path / "frontend" / "src" / "views" / "ExistingNode.vue").read_text(encoding="utf-8") == "<template>existing</template>\n"
    assert set(result["backend_nodes"]["generated"]) == {"AddedNode"}
    assert set(result["frontend_nodes"]["generated"]) == {"AddedNode"}
    assert [step["id"] for step in builder.frontend_writer.calls[0]["steps_meta"]] == ["ExistingNode", "AddedNode"]
    assert builder.frontend_writer.calls[0]["context_base_dir"] == str(tmp_path.resolve())
    assert main_calls == [
        {
            "graph_plan_path": str(graph_path),
            "output_filename": str(tmp_path / "main.py"),
            "fastapi_port": 8123,
        }
    ]
    assert json.loads((tmp_path / "workflow.json").read_text(encoding="utf-8"))["nodes"][1]["name"] == "AddedNode"
    assert set(builder.dynamic_graph_cache["backend_nodes"]) == {"ExistingNode", "AddedNode"}
    assert set(builder.dynamic_graph_cache["frontend_nodes"]) == {"ExistingNode", "AddedNode"}


def test_generate_nodes_writes_backend_files_next_to_graph_plan(monkeypatch, tmp_path):
    project_root = tmp_path / "project_root"
    graph_dir = tmp_path / "graph_dir"
    builder = _make_builder(monkeypatch, project_root)

    requirement_path = graph_dir / "requirement.md"
    requirement_path.parent.mkdir(parents=True, exist_ok=True)
    requirement_path.write_text("# Requirement\n", encoding="utf-8")
    graph_path = graph_dir / "workflow.json"
    _write_graph(
        graph_path,
        [
            {
                "name": "GeneratedNode",
                "type": "WorkflowOperationNode",
                "desc": "generated",
                "show_frontend": False,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "none", "desc": "none"},
            }
        ],
    )

    class _FakeNodeCoder:
        def __init__(self):
            self.root_dir_path = ""
            self.write_calls = []

        def write_node_from_requirement(self, node_name, node_meta, requirement_md_path, output_path, **kwargs):
            self.write_calls.append(
                {
                    "node_name": node_name,
                    "requirement_md_path": requirement_md_path,
                    "output_path": output_path,
                    "root_dir_path": self.root_dir_path,
                }
            )
            target_path = Path(output_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.suffix != ".py":
                target_path = target_path.with_suffix(".py")
            target_path.write_text(f"class {node_name}: ...\n", encoding="utf-8")
            return str(target_path)

        def amend_code_with_feedback(self, *args, **kwargs):
            raise AssertionError("audit amendment should not be called")

    fake_node_coder = _FakeNodeCoder()
    builder._make_node_coder = lambda node_meta: fake_node_coder
    builder.node_auditor = type(
        "_FakeNodeAuditor",
        (),
        {"audit_node_file": staticmethod(lambda *args, **kwargs: (True, []))},
    )()
    builder.requirement_md_path = str(requirement_path)
    builder.graph_plan_path = str(graph_path)

    generated_paths = builder.generate_nodes()

    expected_path = (graph_dir / "GeneratedNode.py").resolve()
    assert generated_paths == [str(expected_path)]
    assert fake_node_coder.write_calls == [
        {
            "node_name": "GeneratedNode",
            "requirement_md_path": str(requirement_path),
            "output_path": str(expected_path),
            "root_dir_path": str(graph_dir.resolve()),
        }
    ]
    assert expected_path.is_file()
    assert builder.node_location_map == {"GeneratedNode": str(expected_path)}


def test_generate_selected_frontend_views_uses_element_path_and_skips_existing_view(monkeypatch, tmp_path):
    builder = _make_builder(monkeypatch, tmp_path)

    graph_path = tmp_path / "graph_plan.json"
    _write_graph(
        graph_path,
        [
            {
                "name": "SelectedNode",
                "type": "WorkflowOperationNode",
                "desc": "selected",
                "show_frontend": True,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "none", "desc": "none"},
            }
        ],
    )
    builder.graph_plan_path = str(graph_path)

    (tmp_path / "node_ui").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_ui" / "SelectedNode.html").write_text("<div>SelectedNode</div>\n", encoding="utf-8")
    (tmp_path / "SelectedNode.py").write_text("class SelectedNode: ...\n", encoding="utf-8")

    frontend_src_dir = tmp_path / "frontend" / "src"
    (frontend_src_dir / "views").mkdir(parents=True, exist_ok=True)
    (frontend_src_dir / "styles").mkdir(parents=True, exist_ok=True)
    existing_view_path = frontend_src_dir / "views" / "SelectedNode.vue"
    existing_view_path.write_text("<template>existing view</template>\n", encoding="utf-8")

    class _FakeViewWriter:
        def __init__(self):
            self.vue_calls = 0
            self.css_calls = 0

        def _read_context_file(self, base_dir, node_name, suffix):
            return f"{node_name}{suffix}"

        def write_node_vue_file(self, **kwargs):
            self.vue_calls += 1
            Path(kwargs["output_path"]).write_text("<template>new view</template>\n", encoding="utf-8")

        def write_node_css_file(self, **kwargs):
            self.css_calls += 1
            Path(kwargs["output_path"]).write_text(".selected {}\n", encoding="utf-8")

    fake_view_writer = _FakeViewWriter()
    builder._make_frontend_view_writer = lambda node_meta: fake_view_writer

    generated = builder._generate_selected_frontend_views(
        ["SelectedNode"],
        output_base_dir=str(frontend_src_dir),
        overwrite_existing=False,
    )

    assert fake_view_writer.vue_calls == 0
    assert fake_view_writer.css_calls == 1
    assert existing_view_path.read_text(encoding="utf-8") == "<template>existing view</template>\n"
    assert generated == {
        "SelectedNode": {
            "style": str(frontend_src_dir / "styles" / "SelectedNode.css")
        }
    }
    assert builder.frontend_view_output_map["SelectedNode"] == {
        "view": str(existing_view_path),
        "style": str(frontend_src_dir / "styles" / "SelectedNode.css"),
    }


def test_get_node_input_output_formats_collects_inputs_and_backend_card_schema(monkeypatch, tmp_path):
    builder = _make_builder(monkeypatch, tmp_path)

    graph_path = tmp_path / "graph_plan.json"
    _write_graph(
        graph_path,
        [
            {
                "name": "CollectInput",
                "type": "WorkflowStepNode",
                "desc": "collect user input",
                "show_frontend": True,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "user_input", "desc": "collect input"},
                "inputs_format": {"query": "String", "limit": "NUMBER"},
            },
            {
                "name": "Summarize",
                "type": "WorkflowOperationNode",
                "desc": "summarize results",
                "show_frontend": False,
                "enable": True,
                "depends": ["CollectInput"],
                "ext_data": {"type": "none", "desc": "none"},
            },
        ],
    )

    (tmp_path / "CollectInput.py").write_text(
        "class CollectInput(WorkflowStepNode):\n"
        "    STEP_ID = 'CollectInput'\n"
        "    TITLE = 'Collect Input'\n"
        "    def process_input(self, user_input, dependency_results, session_state):\n"
        "        return StepRunOutput(card={'kind': 'summary', 'fields': [{'name': 'query', 'type': 'string'}]})\n",
        encoding="utf-8",
    )
    (tmp_path / "Summarize.py").write_text(
        "class Summarize(WorkflowOperationNode):\n"
        "    STEP_ID = 'Summarize'\n"
        "    TITLE = 'Summarize'\n"
        "    def process_operation(self, dependency_results, session_state):\n"
        "        return StepRunOutput(card={'kind': 'report', 'status': 'done'})\n",
        encoding="utf-8",
    )

    builder.graph_plan_path = str(graph_path)

    formats = builder.get_node_input_output_formats()

    assert formats == {
        "CollectInput": {
            "user_input_format": {"query": "string", "limit": "number"},
            "backend_output_card_format": {
                "kind": "summary",
                "fields": [{"name": "query", "type": "string"}],
            },
            "backend_node_path": str(tmp_path / "CollectInput.py"),
        },
        "Summarize": {
            "user_input_format": {},
            "backend_output_card_format": {"kind": "report", "status": "done"},
            "backend_node_path": str(tmp_path / "Summarize.py"),
        },
    }
    assert builder.dynamic_graph_cache["node_input_output_formats"] == formats


def test_rerun_server_validates_artifacts_and_restarts_processes(monkeypatch, tmp_path):
    builder = _make_builder(monkeypatch, tmp_path)

    graph_path = tmp_path / "graph_plan.json"
    _write_graph(
        graph_path,
        [
            {
                "name": "ExistingNode",
                "type": "WorkflowOperationNode",
                "desc": "existing",
                "show_frontend": True,
                "enable": True,
                "depends": [],
                "ext_data": {"type": "none", "desc": "none"},
            }
        ],
    )

    (tmp_path / "node_docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_ui").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "src" / "views").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "src" / "styles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "node_docs" / "ExistingNode.md").write_text("# ExistingNode\n", encoding="utf-8")
    (tmp_path / "node_ui" / "ExistingNode.html").write_text("<div>ExistingNode</div>\n", encoding="utf-8")
    (tmp_path / "ExistingNode.py").write_text("class ExistingNode: ...\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "views" / "ExistingNode.vue").write_text("<template />\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "styles" / "ExistingNode.css").write_text(".existing {}\n", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text("{}\n", encoding="utf-8")
    main_path = tmp_path / "main.py"
    main_path.write_text("print('main')\n", encoding="utf-8")

    class _RunningProcess:
        def __init__(self, pid=1):
            self.pid = pid
            self.terminated = False
            self.killed = False
            self._running = True

        def poll(self):
            return None if self._running else 0

        def terminate(self):
            self.terminated = True
            self._running = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True
            self._running = False

    spawned = []

    class _SpawnedProcess(_RunningProcess):
        next_pid = 100

        def __init__(self, command, cwd=None, env=None):
            super().__init__(pid=_SpawnedProcess.next_pid)
            _SpawnedProcess.next_pid += 1
            self.command = command
            self.cwd = cwd
            self.env = env
            spawned.append(self)

    def fake_popen(command, cwd=None, env=None):
        return _SpawnedProcess(command, cwd=cwd, env=env)

    def fake_which(name):
        if name == "npm":
            return "/usr/bin/npm"
        if name in {"python3.10", "python3", "python"}:
            return "/usr/bin/python3.10"
        return None

    old_backend = _RunningProcess(pid=11)
    old_frontend = _RunningProcess(pid=22)
    builder.backend_server_process = old_backend
    builder.frontend_server_process = old_frontend
    builder.graph_plan_path = str(graph_path)
    builder.frontend_project_dir = str(tmp_path / "frontend")
    builder.main_output_path = str(main_path)

    monkeypatch.setattr(agent_builder_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(agent_builder_module.shutil, "which", fake_which)

    runtime = builder.rerun_server(frontend_port=7777, backend_port=9001)

    assert old_backend.terminated is True
    assert old_frontend.terminated is True
    assert len(spawned) == 2
    assert runtime["backend"]["pid"] == spawned[0].pid
    assert runtime["frontend"]["pid"] == spawned[1].pid
    assert spawned[0].command == ["/usr/bin/python3.10", str(main_path)]
    assert spawned[1].command == ["/usr/bin/npm", "run", "serve", "--", "--host", "127.0.0.1", "--port", "7777"]
    assert spawned[0].cwd == str(tmp_path)
    assert spawned[1].cwd == str((tmp_path / "frontend").resolve())
    assert (tmp_path / "frontend" / "vue.config.js").is_file()
    assert runtime["artifacts"]["backend_nodes"] == {"ExistingNode": str(tmp_path / "ExistingNode.py")}
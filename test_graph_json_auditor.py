import json
import tempfile
from pathlib import Path

from meta_agent.architect.graph import Graph
from meta_agent.architect.graph_planner import GraphPlanner
from meta_agent.auditor.graph_json_auditor import GraphJsonAuditor


def _write_graph(payload: dict) -> Graph:
    with tempfile.TemporaryDirectory() as tmp_dir:
        graph_path = Path(tmp_dir) / "graph.json"
        graph_path.write_text(json.dumps(payload), encoding="utf-8")
        graph = Graph(str(graph_path))
        graph._temp_dir = tmp_dir
        return graph


def test_graph_json_auditor_requires_show_frontend() -> None:
    graph = _write_graph(
        {
            "nodes": [
                {"name": "VisibleStep", "type": "VisibleStep", "desc": "visible step"},
            ]
        }
    )

    is_valid, violations = GraphJsonAuditor().audit_graph_json(graph)

    assert not is_valid
    assert any(v.rule == "show_frontend_missing" for v in violations)


def test_graph_json_auditor_rejects_non_boolean_show_frontend() -> None:
    graph = _write_graph(
        {
            "nodes": [
                {
                    "name": "VisibleStep",
                    "type": "VisibleStep",
                    "desc": "visible step",
                    "show_frontend": "yes",
                },
            ]
        }
    )

    is_valid, violations = GraphJsonAuditor().audit_graph_json(graph)

    assert not is_valid
    assert any(v.rule == "show_frontend_not_boolean" for v in violations)


def test_graph_json_auditor_accepts_boolean_show_frontend() -> None:
    graph = _write_graph(
        {
            "nodes": [
                {
                    "name": "VisibleStep",
                    "type": "VisibleStep",
                    "desc": "visible step",
                    "show_frontend": True,
                },
                {
                    "name": "HiddenStep",
                    "type": "HiddenStep",
                    "desc": "hidden step",
                    "show_frontend": False,
                    "depends": ["VisibleStep"],
                },
            ]
        }
    )

    is_valid, violations = GraphJsonAuditor().audit_graph_json(graph)

    assert is_valid
    assert violations == []


def test_graph_planner_normalizes_show_frontend_field(tmp_path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "name": "VisibleStep",
                        "type": "VisibleStep",
                        "desc": "visible step",
                        "show_frontend": "true",
                    },
                    {
                        "name": "HiddenStep",
                        "type": "HiddenStep",
                        "desc": "hidden step",
                        "show_frontend": "false",
                    },
                    {
                        "name": "DefaultStep",
                        "type": "DefaultStep",
                        "desc": "default step",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    planner = GraphPlanner(client=object())
    planner._normalize_ext_data_in_file(graph_path)
    normalized = json.loads(graph_path.read_text(encoding="utf-8"))

    assert normalized["nodes"][0]["show_frontend"] is True
    assert normalized["nodes"][1]["show_frontend"] is False
    assert normalized["nodes"][2]["show_frontend"] is True
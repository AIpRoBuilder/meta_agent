import json
import tempfile
import unittest
from pathlib import Path

from meta_agent.architect.graph import Graph


class TestGraphGetAllSubgraph(unittest.TestCase):
    def test_get_all_subgraph_returns_root_to_each_node_json(self) -> None:
        graph_payload = {
            "nodes": [
                {"name": "A", "type": "A", "desc": "root"},
                {"name": "B", "type": "B", "desc": "b", "depends": ["A"]},
                {"name": "C", "type": "C", "desc": "c", "depends": ["A"]},
                {"name": "D", "type": "D", "desc": "d", "depends": ["B", "C"]},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            graph_path = Path(tmp_dir) / "graph.json"
            graph_path.write_text(json.dumps(graph_payload), encoding="utf-8")

            graph = Graph(str(graph_path))
            subgraphs = graph.get_all_subgraph()

        self.assertEqual(set(subgraphs.keys()), {"A", "B", "C", "D"})

        self.assertEqual(
            subgraphs["A"],
            {"nodes": [{"name": "A", "type": "A", "desc": "root", "depends": []}]},
        )

        self.assertEqual(
            subgraphs["B"],
            {
                "nodes": [
                    {"name": "A", "type": "A", "desc": "root", "depends": []},
                    {"name": "B", "type": "B", "desc": "b", "depends": ["A"]},
                ]
            },
        )

        self.assertEqual(
            subgraphs["D"],
            {
                "nodes": [
                    {"name": "A", "type": "A", "desc": "root", "depends": []},
                    {"name": "B", "type": "B", "desc": "b", "depends": ["A"]},
                    {"name": "C", "type": "C", "desc": "c", "depends": ["A"]},
                    {"name": "D", "type": "D", "desc": "d", "depends": ["B", "C"]},
                ]
            },
        )

    def test_get_ancestor_session_state_keys_collects_from_node_files(self) -> None:
        graph_payload = {
            "nodes": [
                {"name": "A", "type": "A", "desc": "root"},
                {"name": "B", "type": "B", "desc": "middle", "depends": ["A"]},
                {"name": "C", "type": "C", "desc": "leaf", "depends": ["B"]},
            ]
        }

        a_code = '''
class A:
    def run(self, session_state):
        session_state["root_key"] = "v"
        return session_state.get("shared_key")
'''

        b_code = '''
class B:
    def run(self, session_state):
        session_state.setdefault("mid_key", 1)
        session_state.update({"update_key": 2}, kw_key=3)
'''

        c_code = '''
class C:
    def run(self, session_state):
        session_state.pop("leaf_key", None)
'''

        with tempfile.TemporaryDirectory() as tmp_dir:
            graph_path = Path(tmp_dir) / "graph.json"
            graph_path.write_text(json.dumps(graph_payload), encoding="utf-8")
            (Path(tmp_dir) / "A.py").write_text(a_code, encoding="utf-8")
            (Path(tmp_dir) / "B.py").write_text(b_code, encoding="utf-8")
            (Path(tmp_dir) / "C.py").write_text(c_code, encoding="utf-8")

            graph = Graph(str(graph_path))
            keys = graph.get_ancestor_session_state_keys("C")

        self.assertEqual(
            keys,
            ["kw_key", "leaf_key", "mid_key", "root_key", "shared_key", "update_key"],
        )


if __name__ == "__main__":
    unittest.main()

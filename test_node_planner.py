import json
from types import SimpleNamespace

from meta_agent.architect.node_planner import NodePlanner


class _FakeCompletions:
	def __init__(self, responses):
		self._responses = list(responses)

	def create(self, **kwargs):
		content = self._responses.pop(0)
		return SimpleNamespace(
			choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
		)


class _FakeClient:
	def __init__(self, responses):
		self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_node_context_lists_selectable_types_and_skill_descriptions() -> None:
	planner = NodePlanner(client=_FakeClient([]))

	context = planner._node_context(
		{
			"name": "SearchSkill",
			"desc": "search for external data",
			"show_frontend": True,
			"depends": [],
			"ext_data": {
				"type": "skill",
				"desc": "use a search skill",
				"skill_name": "baidu_search",
			},
			"inputs_format": {"query": "string"},
		},
		1,
	)

	assert "- selectable node types:" in context
	assert "user_input -> WorkflowStepNode" in context
	assert "skill -> WorkflowSkillNode" in context
	assert "- available skills:" in context
	assert "baidu_search:" in context


def test_amend_graph_node_from_files_updates_graph_and_regenerates_node_plan(tmp_path) -> None:
	requirement_path = tmp_path / "requirement.md"
	requirement_path.write_text("# Requirement\n\nCollect a search query and call a skill.", encoding="utf-8")

	graph_path = tmp_path / "graph_plan.json"
	graph_path.write_text(
		json.dumps(
			{
				"nodes": [
					{
						"name": "SearchSkill",
						"type": "SearchSkill",
						"desc": "search for data",
						"show_frontend": True,
						"enable": True,
						"depends": [],
						"ext_data": {
							"type": "skill",
							"desc": "search via skill",
							"skill_name": "baidu_search",
						},
						"inputs_format": {"query": "string"},
					}
				]
			},
			ensure_ascii=False,
			indent=2,
		),
		encoding="utf-8",
	)

	node_plan_path = tmp_path / "node_docs" / "SearchSkill.md"
	planner = NodePlanner(
		client=_FakeClient(
			[
				json.dumps(
					{
						"name": "SearchSkill",
						"type": "SearchSkill",
						"desc": "collect query and search with optional locale",
						"show_frontend": True,
						"enable": True,
						"depends": [],
						"ext_data": {
							"type": "skill",
							"desc": "search via skill",
							"skill_name": "baidu_search",
						},
						"inputs_format": {"query": "string", "locale": "string"},
					},
					ensure_ascii=False,
				),
				"# Node Brief\n\n## What This Node Achieves\nCollects a query and locale, then uses the selected skill.\n\n## Core Functions\n- process_operation: runs the skill using the validated user input.\n",
			]
		)
	)

	amended_graph_path, regenerated_plan_path = planner.amend_graph_node_from_files(
		node_name="SearchSkill",
		user_prompt="Add locale as an optional user input field and update the description.",
		requirement_md_path=str(requirement_path),
		graph_plan_json_path=str(graph_path),
		node_output_path=str(node_plan_path),
	)

	amended_graph = json.loads(amended_graph_path.read_text(encoding="utf-8"))
	amended_node = amended_graph["nodes"][0]

	assert amended_graph_path == graph_path
	assert regenerated_plan_path == node_plan_path
	assert amended_node["ext_data"]["type"] == "skill"
	assert amended_node["ext_data"]["skill_name"] == "baidu_search"
	assert amended_node["inputs_format"] == {"query": "string", "locale": "string"}
	assert "collect query and search with optional locale" == amended_node["desc"]
	assert "Collects a query and locale" in node_plan_path.read_text(encoding="utf-8")
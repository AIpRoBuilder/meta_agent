import tempfile
import textwrap
import unittest
from pathlib import Path

from meta_agent.tools.file_tools import compile_node_file_and_get_derived_keys


class TestCompileNodeFileAndGetDerivedKeys(unittest.TestCase):
	def test_infers_keys_from_step_run_output_derived_variable(self) -> None:
		node_source = textwrap.dedent(
			"""
			from meta_agent.ag_ui_workflow.nodes import WorkflowOperationNode
			from meta_agent.ag_ui_workflow.types import StepRunOutput

			class DemoNode(WorkflowOperationNode):
				def process_operation(self, user_input, dependency_results, session_state):
					payload = {"alpha": 1}
					payload["beta"] = 2
					payload.update({"gamma": 3})
					return StepRunOutput(summary="ok", card={}, derived=payload)
			"""
		)

		with tempfile.TemporaryDirectory() as tmp_dir:
			node_file = Path(tmp_dir) / "demo_node.py"
			node_file.write_text(node_source, encoding="utf-8")

			derived_keys = compile_node_file_and_get_derived_keys(str(node_file))

		self.assertEqual(derived_keys, ["alpha", "beta", "gamma"])

	def test_infers_keys_from_aliased_derived_variable(self) -> None:
		node_source = textwrap.dedent(
			"""
			from meta_agent.ag_ui_workflow.nodes import WorkflowOperationNode
			from meta_agent.ag_ui_workflow.types import StepRunOutput

			class DemoAliasNode(WorkflowOperationNode):
				def process_operation(self, user_input, dependency_results, session_state):
					derived = {"root": 1}
					alias_payload = derived
					alias_payload["leaf"] = 2
					return StepRunOutput(summary="ok", card={}, derived=alias_payload)
			"""
		)

		with tempfile.TemporaryDirectory() as tmp_dir:
			node_file = Path(tmp_dir) / "demo_alias_node.py"
			node_file.write_text(node_source, encoding="utf-8")

			derived_keys = compile_node_file_and_get_derived_keys(str(node_file))

		self.assertEqual(derived_keys, ["leaf", "root"])


if __name__ == "__main__":
	unittest.main()

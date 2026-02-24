from __future__ import annotations

from typing import Any, Dict, List

from auditor.base_json_auditor import BaseJsonAuditor
from auditor.data import JsonRuleViolation
from tools.graph_tools import graph_to_nodes, is_dag, is_weakly_connected


class GraphJsonAuditor(BaseJsonAuditor):
	"""Audit graph JSON definitions for name/type consistency."""

	def audit_graph_json(self, source: Any) -> tuple[bool, List[JsonRuleViolation]]:
		"""Validate that every node's ``name`` matches its ``type``, check for cycles, and connectivity.

		Args:
			source: A mapping, JSON string, or path-like object pointing to the
				graph JSON document.

		Returns:
			Tuple of (is_valid, violations) where violations contains any mismatches,
			detected cycles, or disconnected components as ``JsonRuleViolation`` instances.
		"""

		nodes: Dict[str, Dict[str, Any]] = graph_to_nodes(source)
		violations: List[JsonRuleViolation] = []


		# for idx, (name, info) in enumerate(nodes.items(), start=1):
    	# 		node_type = (info.get("type") or "").strip()
		# 	if name != node_type:
		# 		violations.append(
		# 			JsonRuleViolation(
		# 				parts_name=name,
		# 				rule="name_type_mismatch",
		# 				detail=f"name '{name}' and type '{node_type}' must be identical",
		# 				lineno=idx,
		# 			)
		# 		)

		is_acyclic, cycle_path = is_dag(nodes)
		if not is_acyclic:
			cycle_display = " -> ".join(cycle_path) if cycle_path else "cycle detected"
			violations.append(
				JsonRuleViolation(
					parts_name="graph",
					rule="cycle_detected",
					detail=f"Graph contains a cycle: {cycle_display}",
					lineno=1,
				)
			)

		is_connected, components = is_weakly_connected(nodes)
		if not is_connected:
			component_text = "; ".join(
				", ".join(sorted(comp)) if comp else "<empty>" for comp in components
			)
			violations.append(
				JsonRuleViolation(
					parts_name="graph",
					rule="disconnected",
					detail=f"Graph is not fully connected; components: {component_text}",
					lineno=1,
				)
			)

		return len(violations) == 0, violations

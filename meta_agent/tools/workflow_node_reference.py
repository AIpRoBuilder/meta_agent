from __future__ import annotations

import inspect
from importlib import import_module
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkflowNodeReference:
	base_class: type
	meta_node_kind: str
	capability_category: str
	input_required: bool
	recommended_ext_data_type: str
	planner_hooks: tuple[str, ...]
	summary: str
	step_meta: dict[str, Any]
	supports_inputs_format: bool


_WORKFLOW_NODE_CLASS_NAMES = (
	"WorkflowStepNode",
	"WorkflowOperationNode",
	"WorkflowFileNode",
	"WorkflowSkillNode",
	"SpatialTemporalContractNode",
)


_META_NODE_KIND_TRAITS: dict[str, dict[str, Any]] = {
	"WorkflowStepNode": {
		"capability_category": "input",
		"recommended_ext_data_type": "user_input",
		"supports_inputs_format": True,
	},
	"WorkflowOperationNode": {
		"capability_category": "operation",
		"recommended_ext_data_type": "none",
		"supports_inputs_format": False,
	},
	"WorkflowFileNode": {
		"capability_category": "file",
		"recommended_ext_data_type": "user_file_input",
		"supports_inputs_format": False,
	},
	"WorkflowSkillNode": {
		"capability_category": "skill",
		"recommended_ext_data_type": "skill",
		"supports_inputs_format": True,
	},
	"SpatialTemporalContractNode": {
		"capability_category": "spatial_temporal_contract",
		"recommended_ext_data_type": "spatial_temporal_contract",
		"supports_inputs_format": False,
	},
}


@lru_cache(maxsize=1)
def _workflow_nodes_module() -> Any:
	try:
		return import_module("ag_ui_workflow.nodes")
	except Exception as exc:
		raise RuntimeError(
			"ag_ui_workflow.nodes is required to inspect workflow base step metadata. "
			"Install project dependencies first."
		) from exc


def _base_node_classes() -> tuple[type, ...]:
	workflow_nodes = _workflow_nodes_module()
	result: list[type] = []
	for class_name in _WORKFLOW_NODE_CLASS_NAMES:
		base_class = getattr(workflow_nodes, class_name, None)
		if not isinstance(base_class, type):
			raise RuntimeError(
				f"ag_ui_workflow.nodes.{class_name} is unavailable; cannot build workflow node metadata catalog."
			)
		result.append(base_class)
	return tuple(result)


def _step_meta_node_kind(base_class: type, step_meta: Mapping[str, Any]) -> str:
	meta_node_kind = str(step_meta.get("metaNodeKind", "")).strip()
	if meta_node_kind:
		return meta_node_kind
	return str(base_class.meta_node_kind()).strip()


def _traits_for_meta_node_kind(meta_node_kind: str) -> dict[str, Any]:
	return _META_NODE_KIND_TRAITS.get(
		meta_node_kind,
		{
			"capability_category": "operation",
			"recommended_ext_data_type": "none",
			"supports_inputs_format": False,
		},
	)


def _recommended_ext_data_type(meta_node_kind: str) -> str:
	return str(_traits_for_meta_node_kind(meta_node_kind)["recommended_ext_data_type"])


def _supports_inputs_format(meta_node_kind: str) -> bool:
	return bool(_traits_for_meta_node_kind(meta_node_kind)["supports_inputs_format"])


def _planner_hooks(base_class: type, meta_node_kind: str) -> tuple[str, ...]:
	available_methods = {
		name
		for name, value in inspect.getmembers(base_class, predicate=callable)
		if not name.startswith("__")
	}
	if meta_node_kind == "WorkflowStepNode" and "process_input" in available_methods:
		return ("process_input",)
	if meta_node_kind == "SpatialTemporalContractNode":
		if "clone" in available_methods:
			return ("clone",)
		if "process_operation" in available_methods:
			return ("process_operation",)
		return tuple()
	if meta_node_kind in {"WorkflowOperationNode", "WorkflowSkillNode"} and "process_operation" in available_methods:
		return ("process_operation",)
	if meta_node_kind == "WorkflowFileNode":
		if "save_files_remote" in available_methods:
			return ("save_files_remote",)
		if "build_step_output" in available_methods:
			return ("build_step_output",)
	return tuple()


def _summary_from_step_meta(step_meta: Mapping[str, Any]) -> str:
	for key in ("function", "structure", "implementationGuide"):
		value = str(step_meta.get(key, "")).strip()
		if not value:
			continue
		for line in value.splitlines():
			stripped = line.strip()
			if stripped.startswith("- "):
				return stripped[2:].strip()
			if stripped:
				return stripped
	meta_description = str(step_meta.get("metaDescription", "")).strip()
	return meta_description.splitlines()[0].strip() if meta_description else ""


@lru_cache(maxsize=1)
def workflow_node_references() -> tuple[WorkflowNodeReference, ...]:
	references: list[WorkflowNodeReference] = []
	for base_class in _base_node_classes():
		step_meta = dict(base_class.step_meta())
		meta_node_kind = _step_meta_node_kind(base_class, step_meta)
		traits = _traits_for_meta_node_kind(meta_node_kind)
		references.append(
			WorkflowNodeReference(
				base_class=base_class,
				meta_node_kind=meta_node_kind,
				capability_category=str(traits["capability_category"]),
				input_required=bool(step_meta.get("inputRequired", False)),
				recommended_ext_data_type=_recommended_ext_data_type(meta_node_kind),
				planner_hooks=_planner_hooks(base_class, meta_node_kind),
				summary=_summary_from_step_meta(step_meta),
				step_meta=step_meta,
				supports_inputs_format=_supports_inputs_format(meta_node_kind),
			)
		)
	return tuple(references)


@lru_cache(maxsize=1)
def workflow_meta_node_kind_names() -> tuple[str, ...]:
	return tuple(reference.meta_node_kind for reference in workflow_node_references())


@lru_cache(maxsize=1)
def workflow_meta_node_kind_name_set() -> frozenset[str]:
	return frozenset(workflow_meta_node_kind_names())


def _ext_type_from_value(ext_data: Any) -> str:
	if isinstance(ext_data, Mapping):
		skill_name = str(ext_data.get("skill_name", "")).strip()
		if skill_name:
			return "skill"
		return str(ext_data.get("type", "")).strip().lower()
	if isinstance(ext_data, str):
		return ext_data.strip().lower()
	return ""


def resolve_workflow_node_reference(
	*,
	meta_node_kind: str | None = None,
	ext_data: Any = None,
) -> WorkflowNodeReference:
	meta_lookup = {
		reference.meta_node_kind: reference for reference in workflow_node_references()
	}
	if meta_node_kind:
		matched = meta_lookup.get(str(meta_node_kind).strip())
		if matched is not None:
			return matched

	ext_type = _ext_type_from_value(ext_data)
	for reference in workflow_node_references():
		if reference.recommended_ext_data_type == ext_type:
			return reference

	return meta_lookup["WorkflowOperationNode"]


def canonical_meta_node_kind(*, meta_node_kind: str | None = None, ext_data: Any = None) -> str:
	return resolve_workflow_node_reference(
		meta_node_kind=meta_node_kind,
		ext_data=ext_data,
	).meta_node_kind


def render_workflow_step_meta_catalog() -> str:
	sections: list[str] = []
	for reference in workflow_node_references():
		step_meta = reference.step_meta
		parts = [
			f"### {reference.meta_node_kind}",
			f"- capability category: {reference.capability_category}",
			f"- recommended ext_data.type: {reference.recommended_ext_data_type}",
			f"- inputRequired: {str(reference.input_required).lower()}",
		]
		if reference.planner_hooks:
			parts.append(f"- primary subclass hooks: {', '.join(reference.planner_hooks)}")
		parts.extend(
			[
				"- step_meta reference:",
				f"  - metaNodeKind: {step_meta.get('metaNodeKind', reference.meta_node_kind)}",
				f"  - structure: {str(step_meta.get('structure', '')).strip() or 'n/a'}",
				f"  - function: {str(step_meta.get('function', '')).strip() or 'n/a'}",
				f"  - implementationGuide: {str(step_meta.get('implementationGuide', '')).strip() or 'n/a'}",
			]
		)
		sections.append("\n".join(parts))
	return "\n\n".join(sections).strip()


def render_workflow_node_reference(reference: WorkflowNodeReference) -> str:
	step_meta = reference.step_meta
	return "\n".join(
		[
			f"### {reference.meta_node_kind}",
			f"- capability category: {reference.capability_category}",
			f"- recommended ext_data.type: {reference.recommended_ext_data_type}",
			f"- inputRequired: {str(reference.input_required).lower()}",
			f"- supports inputs_format: {str(reference.supports_inputs_format).lower()}",
			f"- primary subclass hooks: {', '.join(reference.planner_hooks) if reference.planner_hooks else 'none'}",
			f"- structure: {str(step_meta.get('structure', '')).strip() or 'n/a'}",
			f"- function: {str(step_meta.get('function', '')).strip() or 'n/a'}",
			f"- implementationGuide: {str(step_meta.get('implementationGuide', '')).strip() or 'n/a'}",
		]
	)
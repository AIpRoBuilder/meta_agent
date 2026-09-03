from meta_agent.tools.workflow_node_reference import (
    render_workflow_step_meta_catalog,
    workflow_node_references,
)


def test_workflow_node_references_derive_traits_from_meta_node_kind() -> None:
    references = {reference.meta_node_kind: reference for reference in workflow_node_references()}

    assert references["WorkflowStepNode"].step_meta.get("nodeKind") is None
    assert references["WorkflowStepNode"].capability_category == "input"
    assert references["WorkflowStepNode"].recommended_ext_data_type == "user_input"
    assert references["WorkflowStepNode"].supports_inputs_format is True
    assert references["WorkflowStepNode"].planner_hooks == ("process_input",)

    assert references["WorkflowOperationNode"].capability_category == "operation"
    assert references["WorkflowOperationNode"].recommended_ext_data_type == "none"
    assert references["WorkflowOperationNode"].planner_hooks == ("process_operation",)

    assert references["WorkflowFileNode"].capability_category == "file"
    assert references["WorkflowFileNode"].recommended_ext_data_type == "user_file_input"

    assert references["WorkflowSkillNode"].capability_category == "skill"
    assert references["WorkflowSkillNode"].recommended_ext_data_type == "skill"
    assert references["WorkflowSkillNode"].supports_inputs_format is True
    assert references["WorkflowSkillNode"].planner_hooks == ("process_operation",)

    assert references["SpatialTemporalContractNode"].capability_category == "spatial_temporal_contract"
    assert references["SpatialTemporalContractNode"].recommended_ext_data_type == "spatial_temporal_contract"
    assert references["SpatialTemporalContractNode"].planner_hooks == ("clone",)


def test_workflow_step_meta_catalog_uses_meta_node_kind_metadata() -> None:
    catalog = render_workflow_step_meta_catalog()

    assert "metaNodeKind: WorkflowStepNode" in catalog
    assert "capability category: input" in catalog
    assert "nodeKind:" not in catalog
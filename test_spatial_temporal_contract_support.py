from meta_agent.architect.graph import NodeMeta
from meta_agent.auditor.node_auditor import NodeAuditor
from meta_agent.tools.file_tools import (
    compile_node_file_and_get_derived_keys,
    compile_node_file_and_get_step_output_card_schema,
)


def _write_spatial_temporal_node(node_file_path):
    node_file_path.write_text(
        "from pydaograph import register_class\n"
        "from ag_ui_workflow.nodes import SpatialTemporalContractNode\n\n"
        "@register_class\n"
        "class BuildContract(SpatialTemporalContractNode):\n"
        "    STEP_ID = \"BuildContract\"\n"
        "    TITLE = \"Build Contract\"\n"
        "    PROMPT = \"Generate contract\"\n"
        "    DEPENDENCIES = [\"DescribeScene\"]\n"
        "\n"
        "    def clone(self):\n"
        "        return self\n",
        encoding="utf-8",
    )


def test_node_auditor_accepts_spatial_temporal_contract_node(tmp_path):
    node_file_path = tmp_path / "BuildContract.py"
    _write_spatial_temporal_node(node_file_path)

    ok, violations = NodeAuditor().audit_node_file(
        str(node_file_path),
        node_meta=NodeMeta(
            name="BuildContract",
            type="BuildContract",
            desc="Generate a spatial-temporal contract",
            ext_data={
                "type": "spatial_temporal_contract",
                "desc": "build contract json from upstream description",
            },
            depends=["DescribeScene"],
        ),
    )

    assert ok is True
    assert violations == []


def test_file_tools_fallback_to_spatial_temporal_contract_base_methods(tmp_path):
    node_file_path = tmp_path / "BuildContract.py"
    _write_spatial_temporal_node(node_file_path)

    derived_keys = compile_node_file_and_get_derived_keys(str(node_file_path))
    assert "spatialTemporalContract" in derived_keys
    assert "spatialTemporalContractJson" in derived_keys
    assert "objectCount" in derived_keys
    assert "relationCount" in derived_keys

    card_schema = compile_node_file_and_get_step_output_card_schema(str(node_file_path))
    assert card_schema is not None
    assert card_schema["step_id"] == "BuildContract"
    assert card_schema["card"]["title"] == "<expr:boolop>"
    assert "response" in card_schema["card"]
    assert "contract" in card_schema["card"]
    assert "model" in card_schema["card"]
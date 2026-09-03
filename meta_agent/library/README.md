# Prompt Asset Library

This directory stores reusable prompt/reference assets shared by code generators.

## Files

- Workflow node base-class metadata is now injected directly from `ag_ui_workflow` base classes at runtime.
- Default consumers: `meta_agent/architect/graph_planner.py`, `meta_agent/architect/node_planner.py`, `meta_agent/demand_analyzer/requirement_disector.py`, and `meta_agent/worker/node_writer.py` through `meta_agent.tools.workflow_node_reference`.

## Why this exists

- Keeps shared prompt/reference assets that are still repository-local and not derived from installed runtime packages.

## Update guidance

- If a prompt needs workflow base-node contract details, prefer updating `meta_agent.tools.workflow_node_reference` so all planners/writers/auditors keep using the same injected ag_ui_workflow metadata.

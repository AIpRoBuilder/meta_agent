# Prompt Asset Library

This directory stores reusable prompt/reference assets shared by code generators.

## Files

- `frontend_reference.html`
  - Baseline AG-UI frontend template used by frontend generation.
  - Default consumer: `meta_agent/worker/frontend_writer.py` (`PromptFrontendCoder.write_frontend_html`).

- `workflow_nodes_reference_excerpts.md`
  - Workflow node base-class reference excerpt used to ground node generation.
  - Default consumer: `meta_agent/worker/node_writer.py` (`PromptNodeFileCoder.__post_init__` and prompt assembly in `write_node_from_requirement`).

## Why this exists

- Keeps large reference content out of prompt instruction files.
- Makes shared assets easier to maintain and version.
- Reduces duplication across writer prompts.

## Update guidance

- If you update either reference asset, keep the consumer code paths in sync.
- Prefer editing assets here instead of re-embedding large blocks into prompt files.

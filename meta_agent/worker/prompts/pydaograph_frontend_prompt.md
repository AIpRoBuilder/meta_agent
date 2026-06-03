PyDaoGraph AG-UI Frontend Prompt

You generate one file: `frontend.html` for AG-UI lifecycle workflow demos.

Core output contract:
- Output only runnable HTML (with inline CSS/JS as needed).
- Never include Markdown fences or explanations.
- Keep the implementation minimal and deterministic.
- Use browser-native APIs only (fetch, EventSource-like SSE parsing via fetch stream, localStorage).

Workflow context:
- You are provided `graph_plan.json` content as context; use it as authoritative graph/dependency/source-of-truth context.
- You are provided all node HTML snippets from the default `node_ui/` directory as context; for each step card, **faithfully reproduce** the matching node snippet's HTML structure, CSS classes, color palette, spacing values, and component shapes (chips, pills, tags, keyword-grids, dependency-context boxes, param-groups, etc.) inside that step's card body — copy them as closely as possible rather than inventing a new design. If no matching snippet exists for a step, fall back to the global card style.
- Do not require any external `page_title` input variable; choose a sensible static title directly in generated HTML.
- Backend endpoint for running one step: `POST /api/run-step`.
- Optional backend endpoint for cron-run stream: `POST /api/run-all-cron`.
- Backend endpoint for reset/new session init: `POST /api/reset-session`.
- Input step nodes run `process_input(...)`, file nodes build results via `build_step_output(...)` after persistence, chat nodes run `process_chat(...)`, and operation nodes run `process_operation(...)`.
- Operation nodes do not require user text input and should be submitted without an input payload.
- Input nodes should support both plain text entry and optional local file upload.
- For `extData.type == "chat_input"`, treat the step as conversational (`nodeKind='chat'`) and keep plain text input submission behavior.
- For `extData.type == "user_file_input"` / `nodeKind='file'`, treat the step as `WorkflowFileNode`, render multi-file upload UI (allow multiple selection), and submit `input` with `files` (array of `{fileName, fileBytes}`).
- For `nodeKind='service'`, treat the step as a service startup/orchestration step: do not render direct user text or file inputs and auto-submit once unlocked. Show service-oriented status in the card instead of interactive run controls.
- For `extData.type == "skill"` / `nodeKind='skill'`, treat the step as a `WorkflowSkillNode` (skill-library execution): do not render direct user inputs and auto-submit once unlocked. Show skill-execution oriented status in the card instead of interactive run controls.
- If only one file is selected in file-upload steps (`nodeKind='file'`), keep the same `files` array shape with one item.
- Step logic on backend returns `StepRunOutput` with:
  - `summary: str`
  - `card: dict` (commonly includes `rows: [{name, value}, ...]` and may include `actions` to display)
  - `derived: dict`

Event handling requirements:
- Parse SSE chunks from fetch response (`data: ...\n\n`).
- Handle AG-UI lifecycle events:
  - `STEP_STARTED` -> append system message.
  - `STEP_FINISHED` -> mark step as completed and unlock next eligible step.
  - `TEXT_MESSAGE_CONTENT` -> append assistant text deltas in arrival order; these are streamed in multiple chunks for `nodeKind='chat'` responses and must be rendered progressively.
  - `CUSTOM` with `name == "step_card"` -> render/update step card using payload:
    - `stepId`, `title`, `prompt`, `summary`, `card`, `derived`, `unlocked`, `isFinal`.
  - `RUN_ERROR` -> show error message and re-enable step submit.
  - `RUN_FINISHED` -> stop stream state for this submit.

UI behavior requirements:
- Build cards from provided step metadata (id/title/dependencies).
- Render cards progressively: only show the first card initially, and only reveal a card after the immediately previous card has completed (`STEP_FINISHED`).
- Only allow input for currently unlocked step(s) whose dependencies are completed.
- Show a chat area for system/assistant lifecycle text updates.
- Ensure chat text updates are incremental: do not replace prior assistant text when a new `TEXT_MESSAGE_CONTENT` chunk arrives; append to the current assistant message.
- Render each step card summary, `card.rows` key/value table, and `card.actions` list when available.
- Persist `sessionId` in localStorage and display it in the page.
- Include `New Session` and `Reset Session` buttons wired to `/api/reset-session`.
- If `/api/run-all-cron` endpoint is provided, include `Start Cron` and `Stop Cron` controls.
- `Start Cron` must open one SSE stream via `POST /api/run-all-cron` using payload with at least `sessionId` and `resetBeforeEachRun`.
- Reuse the same SSE parsing/event handling pipeline for both `/api/run-step` and `/api/run-all-cron` streams.
- `Stop Cron` must terminate the active cron stream (for example with `AbortController`) and restore UI state.
- Ensure at most one cron stream is active at a time; disable `Start Cron` while cron stream is running.
- Disable/enable submit controls to prevent duplicate submissions while waiting.
- For the currently running step card, show a visible running-circle loading indicator while waiting for result events, and hide the indicator when that step completes or errors.
- For input-required steps, include a file input (`type="file"`) near the text input.
- For steps that do not require direct user input (`inputRequired=false`, `nodeKind='operation'`), auto-submit as soon as they become unlocked/visible; do not require clicking a Run button.
- For those auto-run steps, show non-interactive status text and running-state visuals on the card instead of interactive run controls.
- For file steps (`nodeKind='file'`), submit uploaded files as `{'files':[{'fileName','fileBytes'}, ...]}`.

Structured user-input schema example (must support):
- If a step metadata item contains:
  {
    "id": "LoginInput",
    "nodeKind": "input",
    "extData": {
      "type": "user_input",
      "inputs_format": {
        "email_address": "string",
        "password": "number",
        "remember_me": "boolean"
      }
    }
  }
- Render one form control per field in `inputs_format`:
  - `string` -> text input
  - `number` -> numeric input
  - `boolean` -> checkbox/toggle
- On submit, stringify the collected object and send it as an input string (for example via `JSON.stringify(...)`), e.g.:
  {
    "input": "{\"email_address\":\"user@example.com\",\"password\":123456,\"remember_me\":true}"
  }
- If `extData.inputs_format` is empty/missing, fall back to plain text input behavior.

Node UI fidelity rules:
- Match each step to its node HTML snippet by step id or title (case-insensitive substring match is acceptable).
- When a matching snippet is found: copy its card layout, CSS rules (colors, border-radius, padding, font sizes, transition values), and interactive component markup (keyword-chip grids, pill rows, dependency-context boxes, param-group blocks, tag lists, etc.) directly into the generated step card body.
- Also copy the snippet's JS interaction logic for those components (e.g. click-to-toggle chip selection, add/remove tag handlers) and adapt it to the AG-UI submit flow.
- Do not redesign a component that is already defined in the node snippet; preserve every visual and behavioral detail that does not conflict with the AG-UI event requirements.

Input serialization rules for complex UI controls:
- Before calling the run-step API, **always** serialize the user's collected value into a single string for the `input` field — never send raw JS arrays or objects.
- Multi-select chips / keyword-grid: collect selected labels into an array; submit `JSON.stringify({ <field_name>: selectedArray })` where `<field_name>` matches the node's `inputs_format` key (or `"selected_items"` if unspecified).
- Bullet-point / line-list editors (textarea where each line is one item): split by `\n`, filter blank lines, submit `JSON.stringify({ <field_name>: lines })`.
- Tag / pill lists (dynamic add-remove): collect tag strings into an array; submit `JSON.stringify({ <field_name>: tags })`.
- Checkboxes / boolean toggles not already covered by `inputs_format`: include them in the same JSON object alongside other fields.
- If the node renders multiple complex controls (e.g. a chip grid + a text field), merge all values into one JSON object and submit that as the `input` string.
- Plain single-value text areas with no complex control: submit the `.value` string directly (no JSON wrapping needed unless `inputs_format` dictates otherwise).

Style requirements:
- Keep styling clean and lightweight, but visually polished.
- Make step cards the main visual focus: stronger hierarchy, better spacing, and clearer status affordances.
- Use a modern card treatment with subtle gradients, soft shadows, rounded corners, and crisp borders.
- Distinguish card regions (header/body/input/result) with visual rhythm and consistent padding.
- Add compact status pills and meta chips for step id/dependencies/runtime state.
- Include a clear circular running indicator in the step header while a step is executing.
- Improve readability of summary/rows/actions with deliberate typography contrast and spacing.
- Use smooth, minimal transitions for hover/focus/status changes (avoid heavy motion).
- Keep contrast accessible and preserve responsive behavior on narrow screens.
- No external UI libraries.
- No extra pages. Only a minimal spinner animation for the running-circle loading indicator is allowed.

Preserve the provided reference frontend event semantics and structure while adapting step metadata and titles from the new prompt and context files.
If the reference conflicts with explicit requirements above (especially auto-run for non-input steps), explicit requirements take precedence.

# Workflow Nodes Reference Excerpts (Shortened)

Condensed reference for workflow nodes in `meta_agent/ag_ui_workflow/nodes.py`.
The code below keeps the same behavior/contracts as the full implementation, while
replacing repetitive internals with short comments.

```python
from typing import Any

from pydaograph import CStatus, GNode

from .session import get_bound_workflow_session
from .types import StepRunOutput


class WorkflowStepNode(GNode):
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    INPUT_REQUIRED = True
    NODE_KIND = "input"

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)
        self.setInputPrompt(self.PROMPT)
        self.setInputHandler(self._input_handler)

    def _input_handler(self, user_input: str) -> CStatus:
        # Save raw user input into session.pending_inputs[STEP_ID].
        session = get_bound_workflow_session()
        session.pending_inputs[self.STEP_ID] = user_input
        return CStatus()

    def run(self) -> CStatus:
        # Core flow:
        # 1) set state=running
        # 2) normalize input, enforce required-input check
        # 3) collect dependency StepRunOutput values
        # 4) call process_input(...)
        # 5) ensure returned object is StepRunOutput
        # 6) persist output/card, set completed, trigger callback, clear pending input
        # 7) on error set failed and return CStatus(1001, ...)
        ...

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def process_input(
        self,
        user_input: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        raise NotImplementedError()

    def clone(self):
        return self

    @classmethod
    def step_meta(cls) -> dict[str, Any]:
        return {
            "id": cls.STEP_ID,
            "title": cls.TITLE,
            "prompt": cls.PROMPT,
            "dependencies": list(cls.DEPENDENCIES),
            "inputRequired": cls.INPUT_REQUIRED,
            "nodeKind": cls.NODE_KIND,
        }


class WorkflowFileNode(GNode):
    INPUT_REQUIRED = True
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "file"

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)
        self.setInputPrompt(self.PROMPT)
        self.setInputHandler(self._input_handler)

    def _input_handler(self, user_input: str) -> CStatus:
        session = get_bound_workflow_session()
        session.pending_inputs[self.STEP_ID] = user_input
        return CStatus()

    def run(self) -> CStatus:
        # Core flow:
        # 1) parse multiple uploaded coded-byte files from pending input
        # 2) persist files using original uploaded names (local by default, optional remote)
        # 3) gather dependency outputs
        # 4) call build_step_output(saved_files)
        # 5) require StepRunOutput; persist output/card/state and callback cleanup
        ...

    def save_files(
        self,
        files: list[dict[str, Any]],
        session_state: dict[str, Any],
        storage_override: str | None = None,
    ) -> list[dict[str, Any]]:
        # Default local persistence; can delegate to save_files_remote when configured.
        ...

    def save_files_remote(
        self,
        files: list[dict[str, Any]],
        session_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        # Uses session_state['fileRemoteUploader'] callback for remote persistence.
        ...

    def clone(self):
        return self

    @classmethod
    def step_meta(cls) -> dict[str, Any]:
        return {
            "id": cls.STEP_ID,
            "title": cls.TITLE,
            "prompt": cls.PROMPT,
            "dependencies": list(cls.DEPENDENCIES),
            "inputRequired": cls.INPUT_REQUIRED,
            "nodeKind": cls.NODE_KIND,
        }


class WorkflowOperationNode(GNode):
    INPUT_REQUIRED = False
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "operation"

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)

    def run(self) -> CStatus:
        # Same lifecycle as WorkflowStepNode, but no user-input gate.
        # Calls process_operation(dependency_results, session_state).
        # Requires StepRunOutput; otherwise failed with CStatus(1001, ...).
        ...

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def clone(self):
        return self

    @classmethod
    def step_meta(cls) -> dict[str, Any]:
        return {
            "id": cls.STEP_ID,
            "title": cls.TITLE,
            "prompt": cls.PROMPT,
            "dependencies": list(cls.DEPENDENCIES),
            "inputRequired": cls.INPUT_REQUIRED,
            "nodeKind": cls.NODE_KIND,
        }

    def process_operation(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        raise NotImplementedError()


class WorkflowServiceNode(GNode):
    INPUT_REQUIRED = False
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "service"

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)

    def run(self) -> CStatus:
        # Same non-interactive lifecycle pattern as WorkflowOperationNode,
        # but intended for service startup/probe execution.
        # Calls process_operation(...), which by default:
        # - builds execution spec via build_instance_spec(...)
        # - runs command(s) via run_in_sandbox(...)
        # - formats final StepRunOutput via build_step_output(...)
        ...

    def install_environment(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> bool:
        # Phase 1 – Install / prepare the runtime environment.
        # Implement based on service.md ## 1. Installation section.
        # Run install commands (git clone, uv sync, pip install, etc.) via subprocess.run.
        # Return True if installation succeeded, False otherwise.
        # Should be idempotent: check whether work is already done before repeating it.
        raise NotImplementedError

    def start_service(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> int:
        # Phase 2 – Start the service (runs after install_environment returns True).
        # Implement based on service.md ## 2. Start Service section.
        # Launch the service as a background process using subprocess.Popen.
        # Return the integer PID of the launched process (proc.pid); <= 0 signals failure.
        # Use session_state.get("serviceWorkdir") or self.DEFAULT_WORKDIR as working directory.
        # Do not hardcode absolute paths; define DEFAULT_WORKDIR as a class constant if needed.
        raise NotImplementedError

    def use_service(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        # Phase 3 – Use the running service (runs after start_service returns a valid PID).
        # Implement based on service.md ## 3. Using section.
        # Interact with the service (read output files, send HTTP requests, parse results, etc.)
        # Return StepRunOutput(summary=..., card=..., derived=...) with service results.
        # Keep card JSON-serializable and derived structured for downstream nodes.
        raise NotImplementedError

    # process_operation is NOT meant to be overridden.
    # The base class implementation calls install_environment → start_service → use_service in order.
    # Each phase must succeed before the next is attempted.


class WorkflowSkillNode(GNode):
    INPUT_REQUIRED = False
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "skill"
    # Subclasses MUST set these two class-level constants:
    SKILL_DIR: str = ""          # absolute path to the skill directory
    SKILL_MD_PATH: str = ""      # typically str(Path(SKILL_DIR) / "skill.md")
    INSTALL_TIMEOUT: int = 240   # seconds to wait for background package install

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)
        # Reads SKILL_MD_PATH, populates skill_description / skill_using / skill_examples,
        # and launches background pip install of packages declared in ## Installation.
        ...

    # After __init__, these attributes are available:
    # self.skill_description: str  – text from ## Description
    # self.skill_using: str        – text from ## Using  (authoritative invocation guide)
    # self.skill_examples: str     – text from ## Examples
    # self.skill_install_commands: list[str]  – extracted install commands

    def run(self) -> CStatus:
        # Waits for background package installation (up to INSTALL_TIMEOUT seconds),
        # then calls process_operation(...) – identical non-interactive lifecycle to
        # WorkflowOperationNode.
        ...

    def process_operation(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        # Main customization point for subclasses.
        # Invoke the skill following the ## Using section of skill.md.
        # Use self.skill_using / self.skill_examples for inline reference.
        # Return StepRunOutput(summary=..., card=..., derived=...) with skill results.
        raise NotImplementedError


class WorkflowChatNode(GNode):
    INPUT_REQUIRED = True
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "chat"

    PROVIDER_ENV = "META_AGENT_LLM_PROVIDER"
    MODEL_ENV = "META_AGENT_LLM_MODEL"
    BASE_URL_ENV = "META_AGENT_LLM_BASE_URL"

    DEFAULT_PROVIDER = "openai"
    DEFAULT_MODEL_BY_PROVIDER = {
        "openai": "gpt-4.1-mini",
        "deepseek": "deepseek-chat",
        "qwen": "qwen-plus",
    }

    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    TEMPERATURE = 0.2
    MAX_TOKENS = 8192
    SYSTEM_PROMPT = (
        "You are a helpful workflow assistant. Use dependency outputs and user input to produce a concise, useful answer."
    )

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)
        self.setInputPrompt(self.PROMPT)
        self.setInputHandler(self._input_handler)
        self._provider = self._resolve_provider()
        self._model = self._resolve_model(self._provider)
        self._client = self._build_openai_client(self._provider)

    def _input_handler(self, user_input: str) -> CStatus:
        session = get_bound_workflow_session()
        session.pending_inputs[self.STEP_ID] = user_input
        return CStatus()

    def run(self) -> CStatus:
        # Full flow:
        # - set running + reset streamed_text_deltas[STEP_ID]
        # - read/normalize user input (required unless INPUT_REQUIRED=False)
        # - gather dependency outputs
        # - call process_chat(...)
        #     * must return a non-empty prompt string
        #     * then call _request_llm(prompt), then build_step_output(...)
        # - validate StepRunOutput and persist output/card/state/callback cleanup
        # - on exceptions mark failed and return CStatus(1001, ...)
        ...

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def _serialize_dependency_results(
        self,
        dependency_results: dict[str, StepRunOutput],
    ) -> dict[str, Any]:
        # Converts each dependency output into {summary, card, derived}.
        ...

    def build_user_prompt(
        self,
        user_input: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        # Builds prompt sections:
        # User input, dependency results JSON, session state JSON.
        ...

    def _resolve_provider(self) -> str:
        # Reads env META_AGENT_LLM_PROVIDER, defaults to openai.
        ...

    def _resolve_model(self, provider: str) -> str:
        # META_AGENT_LLM_MODEL override; else provider default.
        ...

    def _build_openai_client(self, provider: str):
        # Initializes OpenAI-compatible client:
        # - deepseek -> DEEPSEEK_API_KEY + deepseek base URL
        # - qwen     -> DASHSCOPE_API_KEY + qwen base URL
        # - openai   -> OPENAI_API_KEY (+ optional custom base URL)
        # Raises clear errors for missing package/keys.
        ...

    def process_chat(
        self,
        user_input: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        # Default: produce a prompt from inputs + context.
        return self.build_user_prompt(user_input, dependency_results, session_state)

    def _request_llm(self, user_prompt: str) -> str:
        # Streams chat.completions, aggregates text deltas, stores deltas in session,
        # returns final content, errors if model response is empty.
        ...

    def build_step_output(self, content: str) -> StepRunOutput:
        # summary/content + card/derived containing provider/model/response.
        ...

    def clone(self):
        return self

    @classmethod
    def step_meta(cls) -> dict[str, Any]:
        return {
            "id": cls.STEP_ID,
            "title": cls.TITLE,
            "prompt": cls.PROMPT,
            "dependencies": list(cls.DEPENDENCIES),
            "inputRequired": cls.INPUT_REQUIRED,
            "nodeKind": cls.NODE_KIND,
        }


```

## What Was Compressed

- Repeated run-lifecycle internals (state transitions, callback/pending-input cleanup).
- Repeated dependency serialization and metadata boilerplate.
- Provider/client plumbing details kept as concise behavioral comments.

## Preserved Semantics

- Same node taxonomy and interfaces: input, operation, service, chat, file, skill.
- Same required override points: `process_input`, `process_operation` (and for service nodes usually `build_instance_spec`), optional `build_step_output` for file nodes, optional chat processors.
- Same `StepRunOutput` contract and error semantics (`1001` for execution/type failures, `1003` for missing required input).
- Same runtime persistence behavior into workflow session maps (`step_outputs`, `step_cards`, `step_states`, `pending_inputs`, callbacks).
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
        # 4) call process_files(saved_files, dependency_results, session_state)
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

    def process_operation(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        spec = self.build_instance_spec(dependency_results, session_state)
        result = self.run_in_sandbox(spec=spec, session_state=session_state)
        # If spec contains "output_location", base class calls parse_output() and merges to result
        output = self.build_step_output(result, dependency_results, session_state)
        # the returned dict into output.derived automatically – no manual wiring needed here.
        return output

    def build_instance_spec(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> dict[str, Any]:
        # Main customization point for subclasses.
        # Return a dict consumed by run_in_sandbox; recognised keys:
        #   command          – shell command to start the service (run as background process)
        #   mode             – "local" (default) or sandbox mode string
        #   workdir          – working directory for local mode
        #   image / domain   – sandbox image / connection domain
        #   sandboxTimeoutSeconds / requestTimeoutSeconds – sandbox lifecycle timeouts
        #   killOnExit       – bool, kill sandbox after command exits
        #   probeCommand     – shell command polled until exit-0 to confirm service readiness
        #   probeDelaySeconds – interval (seconds) between consecutive probe retries (default 2)
        #   probeTimeoutSeconds – total budget (seconds) to wait for probe success (default 30);
        #                         non-zero exit code is returned when the budget is exhausted
        #   stdout / pidLogFile – local-mode output/pid capture paths
        #   output_location  – (optional) absolute file path where the probe/startup command writes
        #                      structured output (e.g. JSON); when present the base class calls
        #                      parse_output() after run_in_sandbox and merges its result into derived
        ...

    def parse_output(self, output_location: str) -> dict[str, Any]:
        # Override this method whenever output_location is set in build_instance_spec.
        # Read the file at output_location, parse it, and return a flat dict.
        # The base-class default reads a JSON file and returns {"parsedOutput": <parsed>}.
        # Subclasses should return domain-specific key-value pairs, e.g.:
        #   with open(output_location) as f:
        #       data = json.load(f)
        #   return {"servicePort": data["port"], "serviceReady": data["ready"]}
        # The returned dict is merged into StepRunOutput.derived by the base class.
        ...


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


class WorkflowImageNode(GNode):
    INPUT_REQUIRED = False
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "image"

    API_KEY_ENV = "ARK_API_KEY"
    MODEL_ENV = "META_AGENT_VLM_MODEL"
    BASE_URL_ENV = "META_AGENT_VLM_BASE_URL"
    DEFAULT_MODEL = "doubao-seed-2-0-pro-260215"
    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

    SYSTEM_PROMPT = (
        "You are a vision-language workflow assistant. Analyze the provided image and combine it "
        "with dependency context to produce concise, actionable results."
    )

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)
        self._model = self._resolve_model()
        self._base_url = self._resolve_base_url()
        # Client init is guarded; failures are stored in _client_init_error.
        self._client = None
        self._client_init_error: Exception | None = None
        try:
            self._client = self._build_openai_client()
        except Exception as exc:
            self._client_init_error = exc

    def run(self) -> CStatus:
        # Full flow for dependency-driven image analysis:
        # - gather dependency outputs
        # - collect image locations from dependency_results
        # - fail when no image locations are available
        # - call process_images_prompts(...)
        #    * must return a non-empty prompt string
        #    * then call _request_vision_model(image_refs, prompt, session_state)
        #    * then call build_step_output(...)
        # - validate StepRunOutput, persist output/card, state updates, callback cleanup
        # - on exceptions set failed and return CStatus(1001, ...)
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
        # Same output-shape serialization as chat node.
        ...

    def _collect_image_locations_from_dependencies(
        self,
        dependency_results: dict[str, StepRunOutput],
    ) -> list[str]:
        # Collects image refs from upstream derived fields, e.g.
        # savedLocations, savedFiles[*].location, imageRefs, imageRef.
        ...

    def _resolve_model(self) -> str:
        # Reads META_AGENT_VLM_MODEL or fallback default.
        ...

    def _resolve_base_url(self) -> str:
        # Reads META_AGENT_VLM_BASE_URL or fallback default.
        ...

    def _build_openai_client(self):
        # Requires openai package + ARK_API_KEY; creates OpenAI client with base URL.
        ...

    def build_user_prompt(
        self,
        request_text: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        # Builds request/dependency/state structured prompt for VLM.
        ...

    def process_images_prompts(
        self,
        image_refs: list[str],
        request_text: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        # Default delegates to process_image_prompts(first_image_ref, ...).
        ...

    def process_image_prompts(
        self,
        image_ref: str,
        request_text: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        return self.build_user_prompt(request_text, dependency_results, session_state)

    def _prepare_image_data(self, image_ref: str, session_state: dict[str, Any]) -> tuple[str, str, int]:
        # Converts path/base64/data-url/bytes-string into data URL + mime + byte size.
        ...

    def _extract_response_text(self, response: Any) -> str:
        # Reads response.output_text or joins text blocks from response.output[].content[].
        ...

    def _request_vision_model(
        self,
        image_refs: list[str],
        user_prompt: str,
        session_state: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        # Sends images + prompt to responses API and returns (text, image_metadata[]).
        ...

    def build_step_output(
        self,
        content: str,
        image_refs: list[str],
        request_text: str,
        image_meta: list[dict[str, Any]],
    ) -> StepRunOutput:
        # Produces summary/card/derived with request, model/baseUrl, and image metadata.
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

- Same node taxonomy and interfaces: input, operation, service, chat, file, image.
- Same required override points: `process_input`, `process_operation` (and for service nodes usually `build_instance_spec`), `process_files`, optional chat/image processors.
- Same `StepRunOutput` contract and error semantics (`1001` for execution/type failures, `1003` for missing required input).
- Same runtime persistence behavior into workflow session maps (`step_outputs`, `step_cards`, `step_states`, `pending_inputs`, callbacks).
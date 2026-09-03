# Workflow Nodes Reference Excerpts (Shortened)

Condensed reference for workflow nodes in `ag_ui_workflow/nodes/*.py`.
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
    SERVICES: list[dict[str, str]] = []
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
            "services": list(cls.SERVICES),
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
    DEFAULT_WORKDIR = str(Path.cwd())

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)

    def run(self) -> CStatus:
        # Same non-interactive lifecycle pattern as WorkflowOperationNode,
        # but process_operation is implemented by the base class.
        # The base class orchestrates install_environment(...) and start_service(...),
        # then registers the service in workflow_service_registry and returns a
        # StepRunOutput describing running status, pid, and installation state.
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

    def process_operation(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        # Do not override in generated subclasses.
        # The base implementation calls install_environment(...) and start_service(...),
        # validates return types, updates workflow_service_registry, and returns a
        # StepRunOutput(card={service/status/pid/...}, derived={service_name/...}).
        ...


class WorkflowSkillNode(GNode):
    INPUT_REQUIRED = True
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
        # gathers normalized user input + dependency outputs, then calls
        # process_operation(...). Subclasses may accept either
        # (user_input, dependency_results, session_state) or
        # (dependency_results, session_state); the base class adapts at runtime.
        ...

    def process_operation(
        self,
        user_input: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        # Main customization point for subclasses.
        # Invoke the skill following the ## Using section of skill.md.
        # Use self.skill_using / self.skill_examples for inline reference.
        # Return StepRunOutput(card=..., derived=...) with skill results.
        raise NotImplementedError


class SpatialTemporalContractNode(GNode):
    INPUT_REQUIRED = False
    STEP_ID = ""
    TITLE = "SpatialTemporal Contract"
    PROMPT = "Generates a spatial-temporal contract from dependency output or session state."
    DEPENDENCIES: list[str] = []
    SERVICES: list[dict[str, str]] = []
    NODE_KIND = "spatial_temporal_contract"
    OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
    OPENAI_MODEL_ENV = "OPENAI_MODEL"
    DEFAULT_OPENAI_MODEL = "deepseek-V4"
    SYSTEM_PROMPT_FILE = "prompts/spatial_temporal_contract_system_prompt.md"

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)

    def run(self) -> CStatus:
        # Non-interactive lifecycle:
        # 1) collect dependency outputs
        # 2) call self.use_service(session_state)
        # 3) call built-in process_operation(dependency_results, session_state)
        # 4) persist output/card/state and trigger callback cleanup
        ...

    def use_service(self, session_state: dict[str, Any]) -> list[dict[str, Any]]:
        # Registers this step's metadata and resolves declared SERVICES usage records.
        ...

    @classmethod
    def step_meta(cls) -> dict[str, Any]:
        return {
            "id": cls.STEP_ID,
            "title": cls.TITLE,
            "prompt": cls.PROMPT,
            "dependencies": list(cls.DEPENDENCIES),
            "services": list(cls.SERVICES),
            "inputRequired": cls.INPUT_REQUIRED,
            "nodeKind": cls.NODE_KIND,
        }

    def process_operation(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        # Built-in implementation (subclasses usually do not override):
        # - resolve description from session_state['spatialTemporalContractDescription']
        #   or upstream outputs/cards/text
        # - call the configured OpenAI-compatible model with the packaged system prompt
        # - normalize the returned JSON contract
        # - return StepRunOutput(card=..., derived={
        #       spatialTemporalContract, spatialTemporalContractJson,
        #       objectCount, relationCount, model, rawResponse, usage?
        #   })
        ...


Use `WorkflowStepNode` for user-entered text inputs, `WorkflowFileNode` for file uploads, and `SpatialTemporalContractNode` for steps that convert upstream descriptions into spatial-temporal contract JSON.


```

## What Was Compressed

- Repeated run-lifecycle internals (state transitions, callback/pending-input cleanup).
- Repeated dependency serialization and metadata boilerplate.
- Provider/client plumbing details kept as concise behavioral comments.

## Preserved Semantics

- Same node taxonomy and interfaces: input, operation, service, file, skill, spatial_temporal_contract.
- Same required override points: `process_input`, `process_operation`, and for service nodes the two-phase `install_environment` / `start_service` pair.
- Same `StepRunOutput` contract and error semantics (`1001` for execution/type failures, `1003` for missing required input).
- Same runtime persistence behavior into workflow session maps (`step_outputs`, `step_cards`, `step_states`, `pending_inputs`, callbacks).
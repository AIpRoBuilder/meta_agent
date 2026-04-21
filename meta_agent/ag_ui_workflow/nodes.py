from pydaograph import GNode, CStatus
import asyncio
import ast
import base64
from datetime import timedelta
import json
import mimetypes
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
import uuid
from typing import Any
from .types import StepRunOutput
from .session import get_bound_workflow_session
from meta_agent.tools.file_tools import parse_skill_md, extract_skill_commands

try:  # Optional dependency for OpenAI-compatible chat providers
    from openai import OpenAI
except Exception:  # pragma: no cover - handled at runtime
    OpenAI = None  # type: ignore


_UPLOAD_DIR = Path(tempfile.gettempdir()) / "meta_agent_uploads"


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _decode_bytes_string(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.startswith("data:") and "base64," in stripped:
        _, _, b64_part = stripped.partition("base64,")
        try:
            return base64.b64decode(b64_part)
        except Exception:
            return None

    try:
        parsed = ast.literal_eval(stripped)
    except Exception:
        return None

    if isinstance(parsed, bytes):
        return parsed
    if isinstance(parsed, bytearray):
        return bytes(parsed)
    return None


def _materialize_upload_to_path(payload: dict[str, Any]) -> str | None:
    file_name = _safe_string(payload.get("fileName") or payload.get("filename") or "uploaded_input")
    content_b64 = payload.get("fileContentBase64") or payload.get("contentBase64")
    content_text = payload.get("fileContent") or payload.get("content")
    content_bytes = payload.get("fileBytes") or payload.get("file_bytes")

    data: bytes | None = None
    if isinstance(content_b64, str) and content_b64.strip():
        try:
            data = base64.b64decode(content_b64)
        except Exception:
            data = None

    if data is None:
        data = _decode_bytes_string(content_bytes)

    if data is None and isinstance(content_text, str):
        data = _decode_bytes_string(content_text)

    if data is None and isinstance(content_text, str):
        data = content_text.encode("utf-8")

    if data is None:
        return None

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix
    target = _UPLOAD_DIR / f"upload_{uuid.uuid4().hex}{suffix}"
    target.write_bytes(data)
    return str(target)


def _normalize_step_input(raw_input: Any) -> str:
    if isinstance(raw_input, str):
        stripped = raw_input.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    else:
        parsed = raw_input

    if isinstance(parsed, dict):
        uploaded_path = _materialize_upload_to_path(parsed)
        if uploaded_path:
            return uploaded_path

        for key in ("filePath", "file_path", "path"):
            if key in parsed:
                return _safe_string(parsed.get(key))

        for key in ("input", "value", "text"):
            if key in parsed:
                return _safe_string(parsed.get(key))

        return json.dumps(parsed, ensure_ascii=False)

    if isinstance(parsed, list):
        return json.dumps(parsed, ensure_ascii=False)

    return _safe_string(parsed)


def _get_step_output_derived_keys(step_id: str) -> list[str]:
    try:
        session = get_bound_workflow_session()
    except RuntimeError:
        return []

    output = session.step_outputs.get(step_id)
    if output is None or not isinstance(output.derived, dict):
        return []
    return list(output.derived.keys())


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
        session = get_bound_workflow_session()
        session.pending_inputs[self.STEP_ID] = user_input
        return CStatus()

    def run(self) -> CStatus:
        session = get_bound_workflow_session()
        self._set_state("running")
        raw_input = _normalize_step_input(session.pending_inputs.get(self.STEP_ID, ""))
        if not raw_input:
            self._set_state("awaiting_input")
            return CStatus(1003, f"input required for step {self.STEP_ID}")

        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }
        try:
            output = self.process_input(
                raw_input,
                dependency_results,
                session.state,
            )
            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: process_input must return StepRunOutput")
        except Exception as exc:  # pragma: no cover
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

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

    STORAGE_BACKEND_ENV = "META_AGENT_FILE_STORAGE_BACKEND"
    STORAGE_DIR_ENV = "META_AGENT_FILE_STORAGE_DIR"
    DEFAULT_STORAGE_BACKEND = "local"
    DEFAULT_STORAGE_DIR = Path(tempfile.gettempdir()) / "meta_agent_file_storage"

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
        session = get_bound_workflow_session()
        self._set_state("running")

        files, storage_override = self._parse_file_input(session.pending_inputs.get(self.STEP_ID, ""))
        if self.INPUT_REQUIRED and not files:
            self._set_state("awaiting_input")
            return CStatus(1003, f"input required for step {self.STEP_ID}")

        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }

        try:
            saved_files = self.save_files(files, session.state, storage_override)
            output = self.process_files(
                saved_files,
                dependency_results,
                session.state,
            )
            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: process_files must return StepRunOutput")
        except Exception as exc:  # pragma: no cover
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

    def _parse_file_input(self, raw_input: Any) -> tuple[list[dict[str, Any]], str | None]:
        parsed: Any = raw_input
        if isinstance(raw_input, str):
            stripped = raw_input.strip()
            if not stripped:
                return [], None
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = stripped

        files: list[dict[str, Any]] = []
        storage_override: str | None = None

        def _append_file(candidate: Any) -> None:
            file_item = self._extract_file_item(candidate)
            if file_item is not None:
                files.append(file_item)

        if isinstance(parsed, dict):
            storage_override = _safe_string(
                parsed.get("storagePath")
                or parsed.get("storage_path")
                or parsed.get("targetDir")
                or parsed.get("target_dir")
                or parsed.get("saveDir")
                or parsed.get("save_dir")
                or parsed.get("location")
            ) or None

            for key in ("files", "fileList", "uploads", "items"):
                values = parsed.get(key)
                if isinstance(values, list):
                    for item in values:
                        _append_file(item)

            if not files:
                _append_file(parsed)

        elif isinstance(parsed, list):
            for item in parsed:
                _append_file(item)
        else:
            _append_file(parsed)

        return files, storage_override

    def _extract_file_item(self, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None

        if isinstance(value, dict):
            file_name = _safe_string(
                value.get("fileName")
                or value.get("filename")
                or value.get("name")
                or value.get("originalName")
                or "uploaded_file"
            )

            data: bytes | None = None

            content_b64 = value.get("fileContentBase64") or value.get("contentBase64")
            if isinstance(content_b64, str) and content_b64.strip():
                try:
                    data = base64.b64decode(content_b64)
                except Exception:
                    data = None

            if data is None:
                data = _decode_bytes_string(value.get("fileBytes") or value.get("file_bytes"))

            if data is None:
                content_text = value.get("fileContent") or value.get("content")
                data = _decode_bytes_string(content_text)

            if data is None and isinstance(value.get("path"), str):
                candidate = Pathv(_safe_string(value.get("path")))
                if candidate.exists() and candidate.is_file():
                    data = candidate.read_bytes()
                    if not file_name or file_name == "uploaded_file":
                        file_name = candidate.name

            if data is None:
                return None

            return {
                "fileName": Path(file_name).name or "uploaded_file",
                "bytes": data,
            }

        if isinstance(value, bytes):
            return {"fileName": "uploaded_file", "bytes": value}

        if isinstance(value, bytearray):
            return {"fileName": "uploaded_file", "bytes": bytes(value)}

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None

            parsed_data = _decode_bytes_string(raw)
            if parsed_data is not None:
                return {"fileName": "uploaded_file", "bytes": parsed_data}

            try:
                decoded_b64 = base64.b64decode(raw, validate=True)
                return {"fileName": "uploaded_file", "bytes": decoded_b64}
            except Exception:
                return None

        return None

    def _resolve_storage_backend(self, session_state: dict[str, Any]) -> str:
        state_backend = _safe_string(session_state.get("fileStorageBackend") or session_state.get("storageBackend"))
        env_backend = _safe_string(os.getenv(self.STORAGE_BACKEND_ENV, self.DEFAULT_STORAGE_BACKEND))
        backend = (state_backend or env_backend or self.DEFAULT_STORAGE_BACKEND).lower()
        return backend if backend in {"local", "remote"} else self.DEFAULT_STORAGE_BACKEND

    def _resolve_storage_dir(self, session_state: dict[str, Any], storage_override: str | None) -> Path:
        if storage_override:
            return Path(storage_override).expanduser().resolve()

        state_dir = _safe_string(session_state.get("fileStorageDir") or session_state.get("storageDir"))
        if state_dir:
            return Path(state_dir).expanduser().resolve()

        env_dir = _safe_string(os.getenv(self.STORAGE_DIR_ENV, ""))
        if env_dir:
            return Path(env_dir).expanduser().resolve()

        return self.DEFAULT_STORAGE_DIR.resolve()

    def save_files(
        self,
        files: list[dict[str, Any]],
        session_state: dict[str, Any],
        storage_override: str | None = None,
    ) -> list[dict[str, Any]]:
        if storage_override:
            session_state["_workflow_file_storage_override"] = storage_override
        else:
            session_state.pop("_workflow_file_storage_override", None)
        try:
            return self.save_files_remote(files, session_state)
        finally:
            session_state.pop("_workflow_file_storage_override", None)

    def save_files_remote(
        self,
        files: list[dict[str, Any]],
        session_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        backend = self._resolve_storage_backend(session_state)
        storage_override = _safe_string(session_state.get("_workflow_file_storage_override")) or None
        if backend != "remote":
            storage_dir = self._resolve_storage_dir(session_state, storage_override)
            storage_dir.mkdir(parents=True, exist_ok=True)

            saved: list[dict[str, Any]] = []
            for item in files:
                file_name = Path(_safe_string(item.get("fileName")) or "uploaded_file").name or "uploaded_file"
                data = item.get("bytes")
                if not isinstance(data, bytes):
                    continue

                target_path = storage_dir / file_name
                target_path.write_bytes(data)
                saved.append(
                    {
                        "fileName": file_name,
                        "storage": "local",
                        "location": str(target_path),
                        "byteSize": len(data),
                    }
                )

            return saved

        remote_uploader = session_state.get("fileRemoteUploader")
        if not callable(remote_uploader):
            raise ValueError(
                "remote file storage requested but session_state['fileRemoteUploader'] is not callable"
            )

        saved: list[dict[str, Any]] = []
        for item in files:
            file_name = Path(_safe_string(item.get("fileName")) or "uploaded_file").name or "uploaded_file"
            data = item.get("bytes")
            if not isinstance(data, bytes):
                continue

            location = _safe_string(remote_uploader(file_name, data, session_state))
            if not location:
                raise ValueError(f"remote uploader returned empty location for file {file_name}")

            saved.append(
                {
                    "fileName": file_name,
                    "storage": "remote",
                    "location": location,
                    "byteSize": len(data),
                }
            )

        return saved

    def process_files(
        self,
        saved_files: list[dict[str, Any]],
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        return self.build_step_output(saved_files)

    def build_step_output(self, saved_files: list[dict[str, Any]]) -> StepRunOutput:
        locations = [
            _safe_string(item.get("location"))
            for item in saved_files
            if _safe_string(item.get("location"))
        ]
        summary = f"Saved {len(saved_files)} file(s)."
        card = {
            "fileCount": len(saved_files),
            "files": saved_files,
            "locations": locations,
        }
        derived = {
            "savedFiles": saved_files,
            "savedLocations": locations,
            "fileCount": len(saved_files),
        }
        return StepRunOutput(summary=summary, card=card, derived=derived)

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


class WorkflowSkillNode(GNode):
    """A workflow node backed by a skill defined in a skill.md file.

    Subclasses set ``SKILL_DIR`` to the directory containing ``skill.md`` (or
    ``SKILL_MD_PATH`` to point directly at the file).  On instantiation the
    skill's ``## Installation`` block is executed so that the required packages
    are available.  Subclasses must override :meth:`implement_skill` to call the
    skill and return a :class:`StepRunOutput`.

    Parsed sections from the skill document are exposed as:
      - ``self.skill_description`` – text under ``## Description``
      - ``self.skill_install_commands`` – list of shell command strings
      - ``self.skill_using`` – text under ``## Using``
      - ``self.skill_examples`` – text under ``## Examples``
    """

    STEP_ID: str = ""
    TITLE: str = ""
    PROMPT: str = ""
    DEPENDENCIES: list[str] = []
    INPUT_REQUIRED: bool = True
    NODE_KIND: str = "skill"

    # Path to the directory that contains skill.md, or to skill.md itself.
    # Subclasses should set one of these.
    SKILL_DIR: str = ""
    SKILL_MD_PATH: str = ""

    # ---------------------------------------------------------------------------
    # Initialisation
    # ---------------------------------------------------------------------------

    INSTALL_TIMEOUT: int = 240  # seconds to wait for background installation

    def __init__(self) -> None:
        import threading
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)

        # Resolve the path to skill.md
        skill_md_path = self._resolve_skill_md_path()

        # Parse the document
        skill_md_text = Path(skill_md_path).read_text(encoding="utf-8")
        sections = parse_skill_md(skill_md_text)

        self.skill_description: str = sections.get("Description", "")
        self.skill_install_commands: list[str] = extract_skill_commands(
            sections.get("Installation", "")
        )
        self.skill_using: str = sections.get("Using", "")
        self.skill_examples: str = sections.get("Examples", "")
        self._install_errors: list[str] = []

        # Run installation commands in a background thread so __init__ is non-blocking.
        self._install_thread: threading.Thread = threading.Thread(
            target=self._install_packages,
            daemon=True,
            name=f"skill-install-{self.STEP_ID}",
        )
        self._install_thread.start()

    # ---------------------------------------------------------------------------
    # Path resolution
    # ---------------------------------------------------------------------------

    def _resolve_skill_md_path(self) -> str:
        """Return the absolute path to skill.md for this node."""
        if self.SKILL_MD_PATH:
            p = Path(self.SKILL_MD_PATH)
            if not p.is_absolute():
                p = Path(__file__).parent.parent.parent / p
            if not p.exists():
                raise FileNotFoundError(f"skill.md not found at {p}")
            return str(p)

        if self.SKILL_DIR:
            p = Path(self.SKILL_DIR)
            if not p.is_absolute():
                p = Path(__file__).parent.parent.parent / p
            candidate = p / "skill.md"
            if not candidate.exists():
                raise FileNotFoundError(f"skill.md not found in {p}")
            return str(candidate)

        raise ValueError(
            f"{self.__class__.__name__} must set SKILL_DIR or SKILL_MD_PATH"
        )

    # ---------------------------------------------------------------------------
    # Package installation
    # ---------------------------------------------------------------------------

    def _install_packages(self) -> None:
        """Run each installation command captured from ## Installation (runs in background thread)."""
        import subprocess
        import warnings

        for cmd in self.skill_install_commands:
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    msg = (
                        f"WorkflowSkillNode installation command returned "
                        f"non-zero exit code {result.returncode}: {cmd!r}\n"
                        f"stderr: {result.stderr.strip()}"
                    )
                    self._install_errors.append(msg)
                    warnings.warn(msg, stacklevel=2)
            except Exception as exc:
                msg = f"WorkflowSkillNode installation command failed: {cmd!r}: {exc}"
                self._install_errors.append(msg)
                warnings.warn(msg, stacklevel=2)

    def _wait_for_installation(self) -> CStatus:
        """Block until the background install thread finishes or INSTALL_TIMEOUT elapses."""
        self._install_thread.join(timeout=self.INSTALL_TIMEOUT)
        if self._install_thread.is_alive():
            return CStatus(
                1001,
                f"step {self.STEP_ID} failed: package installation timed out after {self.INSTALL_TIMEOUT}s",
            )
        if self._install_errors:
            return CStatus(
                1001,
                f"step {self.STEP_ID} failed: package installation errors: {'; '.join(self._install_errors)}",
            )
        return CStatus()

    def run(self) -> CStatus:
        session = get_bound_workflow_session()
        self._set_state("running")

        # Wait for background package installation before executing the skill.
        install_status = self._wait_for_installation()
        if install_status.isErr():
            self._set_state("failed")
            return install_status

        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }
        try:
            output = self.process_operation(
                dependency_results,
                session.state,
            )
            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(
                    1001,
                    f"step {self.STEP_ID} failed: implement_skill must return StepRunOutput",
                )
        except Exception as exc:
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

    def process_operation(
        self,
        dependency_results: dict[str, "StepRunOutput"],
        session_state: dict[str, Any],
    ) -> "StepRunOutput":
        """Execute the skill and return a :class:`StepRunOutput`.

        Subclasses must implement this method.  Use ``self.skill_using`` and
        ``self.skill_examples`` as reference for how to call the underlying
        library installed from ``skill.md``.

        Args:
            user_input: Normalised string input provided by the user for this
                step.
            dependency_results: Outputs of upstream steps keyed by step ID.
            session_state: Mutable shared workflow session state dict.

        Returns:
            A :class:`StepRunOutput` containing the skill result.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.implement_skill() must be implemented by the user.\n"
            f"Refer to self.skill_using and self.skill_examples for usage guidance.\n"
            f"skill_using:\n{self.skill_using}\n\nskill_examples:\n{self.skill_examples}"
        )

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
        session = get_bound_workflow_session()
        self._set_state("running")
        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }
        try:
            output = self.process_operation(
                dependency_results,
                session.state,
            )
            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: process_operation must return StepRunOutput")
        except Exception as exc:  # pragma: no cover
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

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
    DEFAULT_WORKDIR = str(Path.cwd())
    INPUT_REQUIRED = False
    STEP_ID = ""
    TITLE = ""
    PROMPT = ""
    DEPENDENCIES: list[str] = []
    NODE_KIND = "service"

    SANDBOX_DOMAIN_ENV = "SANDBOX_DOMAIN"
    SANDBOX_IMAGE_ENV = "SANDBOX_IMAGE"

    DEFAULT_SANDBOX_DOMAIN = "localhost:8120"
    DEFAULT_SANDBOX_IMAGE = "ubuntu:22.04"

    DEFAULT_SANDBOX_TIMEOUT_SECONDS = 600
    DEFAULT_REQUEST_TIMEOUT_SECONDS = 60
    DEFAULT_KILL_ON_EXIT = True

    def __init__(self) -> None:
        super().__init__()
        self.setName(self.STEP_ID)
        self.setWaitForInput(False)
        self._service_running = False
        self._pid: int | None = None

    def run(self) -> CStatus:
        session = get_bound_workflow_session()
        self._set_state("running")
        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }
        try:
            output = self.process_operation(
                dependency_results,
                session.state,
            )
            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: process_operation must return StepRunOutput")
        except Exception as exc:  # pragma: no cover
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

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

    def _is_local_process_alive(self) -> bool:
        # Return True if the tracked local PID is still running.
        if self._pid is None:
            return False
        import os
        try:
            os.kill(self._pid, 0)
            return True
        except (ProcessLookupError, OSError):
            return False

    def process_operation(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        if self._service_running:
            # For local-mode services, verify the process is still alive.
            if self._pid is not None and not self._is_local_process_alive():
                self._service_running = False
                self._pid = None
            else:
                return StepRunOutput(
                    summary="service is running",
                    card={
                        "serviceRunning": True,
                        "skipped": True,
                        "message": "service is running",
                        "pid": self._pid,
                    },
                    derived={
                        "serviceRunning": True,
                        "serviceSkipped": True,
                        "pid": self._pid,
                    },
                )

        spec = self.build_instance_spec(dependency_results, session_state)
        result = self.run_in_sandbox(spec=spec, session_state=session_state)
        self._service_running = bool(result.get("ok", False))
        if self._service_running and result.get("pid") is not None:
            self._pid = int(result["pid"])
        output_location = spec.get("output_location")
        if output_location:
            parsed = self.parse_output(_safe_string(output_location))
            if parsed:
                result.update(parsed)
        output = self.build_step_output(result, dependency_results, session_state)
        return output

    def build_instance_spec(
        self,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> dict[str, Any]:
        command = session_state.get("instanceCommand")

        return {
            "command": command,
            "image": session_state.get("sandboxImage"),
            "domain": session_state.get("sandboxDomain"),
            "sandboxTimeoutSeconds": session_state.get("sandboxTimeoutSeconds"),
            "requestTimeoutSeconds": session_state.get("sandboxRequestTimeoutSeconds"),
            "killOnExit": session_state.get("sandboxKillOnExit"),
            "probeCommand": session_state.get("instanceProbeCommand"),
            "probeDelaySeconds": session_state.get("instanceProbeDelaySeconds"),
            "probeTimeoutSeconds": session_state.get("instanceProbeTimeoutSeconds"),
        }

    def run_in_sandbox(self, *, spec: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
        return self._run_async(self._run_in_sandbox_async(spec=spec, session_state=session_state))

    def _run_async(self, coroutine: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        raise RuntimeError(
            "WorkflowInstanceNode cannot run sync sandbox execution inside an active event loop. "
            "Use the async sandbox path directly."
        )

    async def _run_in_sandbox_async(self, *, spec: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
        mode = _safe_string(spec.get("mode") or "local").lower() or "local"
        if mode == "local":
            # Run a local Python module or script
            import subprocess
            import shlex
            import os
            command = self._resolve_command(spec)
            if not command:
                return {
                    "mode": "local",
                    "command": command,
                    "exitCode": 1,
                    "stdout": "",
                    "stderr": "No command specified for local mode.",
                    "ok": False,
                }
            try:
                user_stdout = spec.get("stdout")
                pid_log_file = spec.get("pidLogFile")
                workdir = spec.get("workdir") or self.DEFAULT_WORKDIR
                # Run as detached background process and log PID
                out = open(user_stdout, "ab") if user_stdout else subprocess.DEVNULL
                proc = subprocess.Popen(
                    shlex.split(command),
                    cwd=workdir,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
                if pid_log_file:
                    with open(pid_log_file, "a") as pidf:
                        pidf.write(f"{proc.pid}\n")
                result = {
                    "mode": "local-service",
                    "command": command,
                    "pid": proc.pid,
                    "stdout": None,
                    "stderr": None,
                    "exitCode": None,
                    "ok": True,
                }
                session_state["lastSandboxExecution"] = result
                return result
            except Exception as exc:
                return {
                    "mode": "local",
                    "command": command,
                    "exitCode": 1,
                    "stdout": "",
                    "stderr": str(exc),
                    "ok": False,
                }
        else:
            # Default: run in sandbox as before
            sandbox_module = self._import_sandbox()
            Sandbox = sandbox_module["Sandbox"]
            ConnectionConfig = sandbox_module["ConnectionConfig"]

            domain = self._resolve_domain(spec)
            image = self._resolve_image(spec)
            request_timeout = self._resolve_seconds(spec.get("requestTimeoutSeconds"), self.DEFAULT_REQUEST_TIMEOUT_SECONDS)
            sandbox_timeout = self._resolve_seconds(spec.get("sandboxTimeoutSeconds"), self.DEFAULT_SANDBOX_TIMEOUT_SECONDS)
            kill_on_exit = self._resolve_bool(spec.get("killOnExit"), self.DEFAULT_KILL_ON_EXIT)

            config = ConnectionConfig(
                domain=domain,
                request_timeout=timedelta(seconds=request_timeout),
            )

            sandbox = await Sandbox.create(
                image,
                connection_config=config,
                timeout=timedelta(seconds=sandbox_timeout),
            )

            async with sandbox:
                execution = await self._run_service_mode(sandbox=sandbox, spec=spec)

                stdout = self._extract_logs_text(execution, "stdout")
                stderr = self._extract_logs_text(execution, "stderr")
                exit_code = self._extract_exit_code(execution)

                if kill_on_exit:
                    await sandbox.kill()

                result = {
                    "mode": mode,
                    "command": self._resolve_command(spec),
                    "image": image,
                    "domain": domain,
                    "exitCode": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "ok": (exit_code == 0),
                }
                session_state["lastSandboxExecution"] = result
                return result

    async def _run_service_mode(self, *, sandbox: Any, spec: dict[str, Any]) -> Any:
        service_command = self._resolve_command(spec)
        probe_command = _safe_string(spec.get("probeCommand"))
        probe_interval = self._resolve_seconds(spec.get("probeDelaySeconds"), 2)
        probe_timeout = self._resolve_seconds(spec.get("probeTimeoutSeconds"), 300)

        start_cmd = f"{service_command} >/tmp/workflow_instance_service.log 2>&1 &"

        if probe_command:
            # Poll probe_command in a loop until it exits 0 or the timeout elapses.
            wait_script = (
                f"_pd=$(($(date +%s)+{probe_timeout})); "
                f"_ok=0; "
                f"while [ $(date +%s) -lt $_pd ]; do "
                f"{probe_command} && _ok=1 && break; "
                f"sleep {probe_interval}; "
                f"done; "
                f"[ $_ok -eq 1 ] || {{ echo 'service probe timed out after {probe_timeout}s' >&2; exit 1; }}"
            )
            bootstrap = f"{start_cmd} {wait_script}"
        else:
            bootstrap = f"{start_cmd} sleep {probe_interval}; echo service_started"

        return await sandbox.commands.run(bootstrap)

    def _import_sandbox(self) -> dict[str, Any]:
        try:
            from opensandbox import Sandbox
            from opensandbox.config import ConnectionConfig
        except Exception as exc:  # pragma: no cover
            raise ImportError("opensandbox is required for WorkflowInstanceNode") from exc

        return {
            "Sandbox": Sandbox,
            "ConnectionConfig": ConnectionConfig,
        }

    def _resolve_domain(self, spec: dict[str, Any]) -> str:
        domain = _safe_string(spec.get("domain"))
        if domain:
            return domain
        env_domain = _safe_string(os.getenv(self.SANDBOX_DOMAIN_ENV))
        if env_domain:
            return env_domain
        return self.DEFAULT_SANDBOX_DOMAIN

    def _resolve_image(self, spec: dict[str, Any]) -> str:
        image = _safe_string(spec.get("image"))
        if image:
            return image
        env_image = _safe_string(os.getenv(self.SANDBOX_IMAGE_ENV))
        if env_image:
            return env_image
        return self.DEFAULT_SANDBOX_IMAGE

    def _resolve_command(self, spec: dict[str, Any]) -> str:
        command = spec.get("command")
        if isinstance(command, list):
            return " ".join(_safe_string(part) for part in command if _safe_string(part))
        command_text = _safe_string(command)
        return command_text

    def _resolve_seconds(self, value: Any, default_value: int) -> int:
        try:
            number = int(value)
        except Exception:
            return default_value
        return number if number > 0 else default_value

    def _resolve_bool(self, value: Any, default_value: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return default_value

    def _extract_logs_text(self, execution: Any, stream: str) -> str:
        logs = getattr(execution, "logs", None)
        if logs is None:
            return ""
        items = getattr(logs, stream, None)
        if not isinstance(items, list):
            return ""

        chunks: list[str] = []
        for item in items:
            text = _safe_string(getattr(item, "text", ""))
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()

    def _extract_exit_code(self, execution: Any) -> int:
        for attr in ("exit_code", "exitCode", "code"):
            value = getattr(execution, attr, None)
            try:
                return int(value)
            except Exception:
                continue
        return 0

    def parse_output(self, output_location: str) -> dict[str, Any]:
        """Parse output from ``output_location`` after the service runs.

        The default implementation reads a JSON file at that path and returns
        its contents under the ``parsedOutput`` key.  Subclasses may override
        this method to support other formats or locations (e.g. a URL, a binary
        file, or a structured directory).

        Args:
            output_location: The value of the ``output_location`` key returned
                by :meth:`build_instance_spec`.

        Returns:
            A dict whose entries are merged into the step's ``derived`` dict.
        """
        try:
            path = Path(output_location)
            if path.exists():
                content = path.read_text("utf-8")
                return {"parsedOutput": json.loads(content)}
        except Exception:  # pragma: no cover
            pass
        return {}

    def build_step_output(
        self,
        result: dict[str, Any],
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> StepRunOutput:
        command = _safe_string(result.get("command"))
        mode = _safe_string(result.get("mode") or "command")
        image = _safe_string(result.get("image"))
        exit_code = result.get("exitCode", 0)
        ok = bool(result.get("ok", True))

        summary = f"{self.STEP_ID} ran in sandbox ({mode}) with exit code {exit_code}."
        if command:
            summary = f"{summary} command: {command}"

        card = {
            "mode": mode,
            "image": image,
            "domain": result.get("domain"),
            "summary": summary,
            "command": command,
            "exitCode": exit_code,
            "ok": ok,
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
        }

        derived = {
            "instanceResult": result,
            "sandboxCommand": command,
            "sandboxImage": image,
            "sandboxOk": ok,
            "sandboxExitCode": exit_code,
            "sandboxStdout": result.get("stdout", ""),
            "sandboxStderr": result.get("stderr", ""),
        }
        return StepRunOutput(summary=summary, card=card, derived=derived)


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

    DEFAULT_PROVIDER = "deepseek"
    DEFAULT_MODEL_BY_PROVIDER = {
        "openai": "gpt-4.1-mini",
        "deepseek": "deepseek-chat",
        "qwen": "qwen-plus",
    }

    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    TEMPERATURE = 0.2
    MAX_TOKENS = 20000
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
        session = get_bound_workflow_session()
        self._set_state("running")
        session.streamed_text_deltas.pop(self.STEP_ID, None)
        raw_input = _normalize_step_input(session.pending_inputs.get(self.STEP_ID, ""))
        if self.INPUT_REQUIRED and not raw_input:
            self._set_state("awaiting_input")
            return CStatus(1003, f"input required for step {self.STEP_ID}")

        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }
        try:
            prompt_or_output = self.process_chat(
                raw_input,
                dependency_results,
                session.state,
            )
            if isinstance(prompt_or_output, StepRunOutput):
                output = prompt_or_output
                session.streamed_text_deltas.pop(self.STEP_ID, None)
            else:
                user_prompt = _safe_string(prompt_or_output)
                if not user_prompt:
                    self._set_state("failed")
                    return CStatus(1001, f"step {self.STEP_ID} failed: process_chat must return a non-empty prompt string")

                response_text = self._request_llm(user_prompt)
                output = self.build_step_output(response_text)

            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: run must produce StepRunOutput")
        except Exception as exc:  # pragma: no cover
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

    def _serialize_dependency_results(
        self,
        dependency_results: dict[str, StepRunOutput],
    ) -> dict[str, Any]:
        return {
            dep: {
                "summary": output.summary,
                "card": output.card,
                "derived": output.derived,
            }
            for dep, output in dependency_results.items()
        }

    def build_user_prompt(
        self,
        user_input: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        dependency_payload = self._serialize_dependency_results(dependency_results)
        sections = [
            "User input:",
            user_input,
            "",
            "Dependency results (JSON):",
            json.dumps(dependency_payload, ensure_ascii=False, indent=2),
            "",
            "Session state (JSON):",
            json.dumps(session_state, ensure_ascii=False, indent=2),
        ]
        return "\n".join(sections).strip()

    def _resolve_provider(self) -> str:
        provider = os.getenv(self.PROVIDER_ENV, self.DEFAULT_PROVIDER)
        return _safe_string(provider).lower() or self.DEFAULT_PROVIDER

    def _resolve_model(self, provider: str) -> str:
        model = os.getenv(self.MODEL_ENV)
        if model and model.strip():
            return model.strip()
        return self.DEFAULT_MODEL_BY_PROVIDER.get(provider, self.DEFAULT_MODEL_BY_PROVIDER["openai"])

    def _build_openai_client(self, provider: str):
        if OpenAI is None:
            raise ImportError(
                "openai is not installed. Install `openai` to use WorkflowChatNode with OpenAI-compatible providers."
            )

        custom_base_url = os.getenv(self.BASE_URL_ENV, "").strip()
        if provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
            if not api_key:
                raise ValueError("Missing DEEPSEEK_API_KEY for WorkflowChatNode")
            return OpenAI(api_key=api_key, base_url=custom_base_url or self.DEEPSEEK_BASE_URL)

        if provider == "qwen":
            api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
            if not api_key:
                raise ValueError("Missing DASHSCOPE_API_KEY for WorkflowChatNode")
            return OpenAI(api_key=api_key, base_url=custom_base_url or self.QWEN_BASE_URL)

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY for WorkflowChatNode")
        if custom_base_url:
            return OpenAI(api_key=api_key, base_url=custom_base_url)
        return OpenAI(api_key=api_key)

    def process_chat(
        self,
        user_input: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        return self.build_user_prompt(user_input, dependency_results, session_state)

    def _request_llm(self, user_prompt: str) -> str:
        response_stream = self._client.chat.completions.create(
            model=self._model,
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
            stream=True,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        deltas: list[str] = []
        for chunk in response_stream:
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            delta_obj = getattr(choice, "delta", None)
            delta = getattr(delta_obj, "content", "") if delta_obj is not None else ""
            if isinstance(delta, str) and delta:
                deltas.append(delta)
            elif isinstance(delta, list):
                for item in delta:
                    text = getattr(item, "text", "") if item is not None else ""
                    if isinstance(text, str) and text:
                        deltas.append(text)

        content = _safe_string("".join(deltas))
        if not content:
            raise RuntimeError("WorkflowChatNode received empty LLM response")

        session = get_bound_workflow_session()
        session.streamed_text_deltas[self.STEP_ID] = deltas
        return content

    def build_step_output(self, content: str) -> StepRunOutput:
        card = {
            "provider": self._provider,
            "model": self._model,
            "response": content,
        }
        derived = {
            "response": content,
            "provider": self._provider,
            "model": self._model,
        }
        return StepRunOutput(summary=content, card=card, derived=derived)

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
        self._client = None
        self._client_init_error: Exception | None = None
        try:
            self._client = self._build_openai_client()
        except Exception as exc:
            self._client_init_error = exc
    
    def run(self) -> CStatus:
        session = get_bound_workflow_session()
        self._set_state("running")

        dependency_results = {
            dep: session.step_outputs[dep]
            for dep in self.DEPENDENCIES
            if dep in session.step_outputs
        }
        image_refs = self._collect_image_locations_from_dependencies(dependency_results)
        if not image_refs:
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: no image locations found in dependency_results")

        try:
            prompt_or_output = self.process_images_prompts(
                image_refs,
                "",
                dependency_results,
                session.state,
            )
            if not isinstance(prompt_or_output, str):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: process_images_prompts must return a string prompt")

            user_prompt = _safe_string(prompt_or_output)
            if not user_prompt:
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: process_images_prompts must return a non-empty prompt string")

            response_text, image_meta = self._request_vision_model(image_refs, user_prompt, session.state)
            output = self.build_step_output(response_text, image_refs, "", image_meta)

            if not isinstance(output, StepRunOutput):
                self._set_state("failed")
                return CStatus(1001, f"step {self.STEP_ID} failed: run must produce StepRunOutput")
        except Exception as exc:  # pragma: no cover
            self._set_state("failed")
            return CStatus(1001, f"step {self.STEP_ID} failed: {exc}")

        session.step_outputs[self.STEP_ID] = output
        session.step_cards[self.STEP_ID] = self.card_payload(output)
        self._set_state("completed")
        callback = session.submit_callbacks.pop(self.STEP_ID, None)
        if callback is not None:
            callback(output)
        session.pending_inputs.pop(self.STEP_ID, None)
        return CStatus()

    def _set_state(self, state: str) -> None:
        session = get_bound_workflow_session()
        session.step_states[self.STEP_ID] = state

    def card_payload(self, output: StepRunOutput) -> dict[str, Any]:
        return output.card

    def get_derived_keys(self) -> list[str]:
        return _get_step_output_derived_keys(self.STEP_ID)

    def _serialize_dependency_results(
        self,
        dependency_results: dict[str, StepRunOutput],
    ) -> dict[str, Any]:
        return {
            dep: {
                "summary": output.summary,
                "card": output.card,
                "derived": output.derived,
            }
            for dep, output in dependency_results.items()
        }

    def _collect_image_locations_from_dependencies(
        self,
        dependency_results: dict[str, StepRunOutput],
    ) -> list[str]:
        refs: list[str] = []

        def _append_ref(value: Any) -> None:
            if isinstance(value, str):
                ref = value.strip()
                if ref:
                    refs.append(ref)
                return

            if isinstance(value, dict):
                location = _safe_string(value.get("location") or value.get("path") or value.get("filePath"))
                if location:
                    refs.append(location)
                for nested in value.values():
                    if isinstance(nested, (dict, list)):
                        _append_ref(nested)
                return

            if isinstance(value, list):
                for item in value:
                    _append_ref(item)

        for output in dependency_results.values():
            derived = output.derived if isinstance(output.derived, dict) else {}
            if "savedLocations" in derived:
                _append_ref(derived.get("savedLocations"))
            if "imageRefs" in derived:
                _append_ref(derived.get("imageRefs"))
            if "savedFiles" in derived:
                _append_ref(derived.get("savedFiles"))
            if "images" in derived:
                _append_ref(derived.get("images"))
            if "imageRef" in derived:
                _append_ref(derived.get("imageRef"))
            if "image" in derived:
                _append_ref(derived.get("image"))

        unique_refs = [ref for ref in dict.fromkeys(refs) if ref]
        return unique_refs

    def _resolve_model(self) -> str:
        model = os.getenv(self.MODEL_ENV)
        if model and model.strip():
            return model.strip()
        return self.DEFAULT_MODEL

    def _resolve_base_url(self) -> str:
        base_url = os.getenv(self.BASE_URL_ENV)
        if base_url and base_url.strip():
            return base_url.strip()
        return self.DEFAULT_BASE_URL

    def _build_openai_client(self):
        if OpenAI is None:
            raise ImportError(
                "openai is not installed. Install `openai` to use WorkflowImageNode with OpenAI-compatible providers."
            )

        api_key = os.getenv(self.API_KEY_ENV, "").strip()
        if not api_key:
            raise ValueError(f"Missing {self.API_KEY_ENV} for WorkflowImageNode")
        return OpenAI(api_key=api_key, base_url=self._base_url)

    def build_user_prompt(
        self,
        request_text: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        dependency_payload = self._serialize_dependency_results(dependency_results)
        effective_request = request_text.strip() if request_text else "Please analyze this image in detail."
        sections = [
            "User request:",
            effective_request,
            "",
            "Dependency results (JSON):",
            json.dumps(dependency_payload, ensure_ascii=False, indent=2),
            "",
            "Session state (JSON):",
            json.dumps(session_state, ensure_ascii=False, indent=2),
        ]
        return "\n".join(sections).strip()

    def process_images_prompts(
        self,
        image_refs: list[str],
        request_text: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        primary_image_ref = image_refs[0] if image_refs else ""
        return self.process_image_prompts(primary_image_ref, request_text, dependency_results, session_state)

    def process_image_prompts(
        self,
        image_ref: str,
        request_text: str,
        dependency_results: dict[str, StepRunOutput],
        session_state: dict[str, Any],
    ) -> str:
        return self.build_user_prompt(request_text, dependency_results, session_state)

    def _load_remote_image_bytes(
        self,
        image_ref: str,
        session_state: dict[str, Any],
    ) -> tuple[bytes | None, str | None]:
        remote_loader = session_state.get("imageRemoteLoader")
        if callable(remote_loader):
            loaded = remote_loader(image_ref, session_state)
            if isinstance(loaded, bytes):
                return loaded, None
            if isinstance(loaded, tuple) and len(loaded) == 2 and isinstance(loaded[0], bytes):
                mime = _safe_string(loaded[1]) if loaded[1] is not None else ""
                return loaded[0], mime or None

        if image_ref.startswith("http://") or image_ref.startswith("https://"):
            request = Request(image_ref, headers={"User-Agent": "meta-agent-workflow-image-node"})
            with urlopen(request, timeout=30) as response:
                image_bytes = response.read()
                content_type = _safe_string(response.headers.get("Content-Type", ""))
                mime_type = content_type.split(";")[0].strip() if content_type else ""
                return image_bytes, mime_type or None

        return None, None

    def _prepare_image_data(self, image_ref: str, session_state: dict[str, Any]) -> tuple[str, str, int]:
        ref = _safe_string(image_ref)
        if not ref:
            raise ValueError("image_ref is empty")

        if ref.startswith("data:image/") and "base64," in ref:
            header, _, b64_part = ref.partition("base64,")
            mime_type = header.replace("data:", "").replace(";", "").replace("base64", "").strip() or "image/png"
            image_bytes = base64.b64decode(b64_part)
            return ref, mime_type, len(image_bytes)

        image_bytes: bytes | None = None
        mime_type = mimetypes.guess_type(ref)[0] or "image/png"

        path = Path(ref)
        if path.exists() and path.is_file():
            image_bytes = path.read_bytes()
            guessed = mimetypes.guess_type(path.name)[0]
            if guessed:
                mime_type = guessed

        if image_bytes is None:
            remote_bytes, remote_mime = self._load_remote_image_bytes(ref, session_state)
            if remote_bytes is not None:
                image_bytes = remote_bytes
                if remote_mime:
                    mime_type = remote_mime

        if image_bytes is None:
            decoded = _decode_bytes_string(ref)
            if decoded is not None:
                image_bytes = decoded

        if image_bytes is None:
            try:
                image_bytes = base64.b64decode(ref, validate=True)
            except Exception as exc:
                raise ValueError("Unsupported image input. Provide file path, bytes string, or base64/data-url image.") from exc

        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
        return data_url, mime_type, len(image_bytes)

    def _extract_response_text(self, response: Any) -> str:
        output_text = _safe_string(getattr(response, "output_text", ""))
        if output_text:
            return output_text

        output_items = getattr(response, "output", None)
        if isinstance(output_items, list):
            chunks: list[str] = []
            for item in output_items:
                content_list = getattr(item, "content", None)
                if not isinstance(content_list, list):
                    continue
                for content_item in content_list:
                    text_value = _safe_string(getattr(content_item, "text", ""))
                    if text_value:
                        chunks.append(text_value)
            if chunks:
                return "\n".join(chunks).strip()

        return ""

    def _request_vision_model(
        self,
        image_refs: list[str],
        user_prompt: str,
        session_state: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        if not image_refs:
            raise ValueError("image_refs is empty")
        if self._client is None:
            reason = str(self._client_init_error) if self._client_init_error is not None else "client is unavailable"
            raise ValueError(f"WorkflowImageNode client initialization failed: {reason}")

        user_content: list[dict[str, Any]] = []
        image_metas: list[dict[str, Any]] = []
        for image_ref in image_refs:
            image_url, mime_type, image_bytes = self._prepare_image_data(image_ref, session_state)
            user_content.append({"type": "input_image", "image_url": image_url})
            image_metas.append(
                {
                    "mimeType": mime_type,
                    "byteSize": image_bytes,
                    "source": image_ref,
                }
            )
        user_content.append({"type": "input_text", "text": user_prompt})

        response = self._client.responses.create(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": self.SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        )
        content = _safe_string(self._extract_response_text(response))
        if not content:
            raise RuntimeError("WorkflowImageNode received empty VLM response")

        return content, image_metas

    def build_step_output(
        self,
        content: str,
        image_refs: list[str],
        request_text: str,
        image_meta: list[dict[str, Any]],
    ) -> StepRunOutput:
        primary_image_ref = image_refs[0] if image_refs else ""
        primary_image_meta = image_meta[0] if image_meta else {}
        summary = content
        card = {
            "provider": "ark",
            "model": self._model,
            "baseUrl": self._base_url,
            "request": request_text,
            "response": content,
            "image": primary_image_meta,
            "images": image_meta,
            "imageCount": len(image_meta),
        }
        derived = {
            "analysis": content,
            "request": request_text,
            "imageRef": primary_image_ref,
            "imageRefs": image_refs,
            "image": primary_image_meta,
            "images": image_meta,
            "model": self._model,
            "baseUrl": self._base_url,
        }
        return StepRunOutput(summary=summary, card=card, derived=derived)

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


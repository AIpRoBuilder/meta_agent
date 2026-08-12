"""LLM-backed coder utility.

The `Coder` class wraps a chat model call and writes the generated code
to disk. By default it uses the `openai` Python client but you can supply
any drop-in client exposing a `chat.completions.create` method that
returns a response with `choices[0].message.content` or a streaming iterator
of chunk objects.

For OpenAI-compatible gateways such as D-API, set ``openai_base_url`` or
the ``OPENAI_BASE_URL`` environment variable.
"""

from __future__ import annotations

import os
from inspect import Parameter, signature
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from meta_agent.logging_utils import get_logger

try:  # Optional dependency for OpenAI-compatible clients (OpenAI + DeepSeek)
    from openai import OpenAI
except Exception:  # pragma: no cover - handled at runtime
    OpenAI = None  # type: ignore

try:  # Optional dependency for Zhipu
    from zai import ZhipuAiClient
except Exception:  # pragma: no cover - handled at runtime
    ZhipuAiClient = None  # type: ignore


class LLMGenerationError(RuntimeError):
    """Raised when the language model fails to return usable content."""


def _resolve_max_tokens() -> int:
    raw_value = os.getenv("MAX_TOKENS", "8192").strip()
    try:
        value = int(raw_value)
    except ValueError:
        return 8192
    return value if value > 0 else 8192


MAX_TOKENS = _resolve_max_tokens()
LOGGER = get_logger(__name__)


def _resolve_timeout(provider: str) -> Optional[float]:
    provider_env_names = {
        "openai": "OPENAI_TIMEOUT",
        "zhipu": "ZHIPU_TIMEOUT",
        "deepseek": "DEEPSEEK_TIMEOUT",
        "qwen": "QWEN_TIMEOUT",
        "111api": "ONEONEONEAPI_TIMEOUT",
    }
    raw_value = os.getenv(provider_env_names.get(provider, ""), "").strip()
    if not raw_value:
        raw_value = str(os.getenv("LLM_TIMEOUT", 200000)).strip()
    if not raw_value:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None


def _accepts_keyword(callable_obj: object, keyword: str) -> bool:
    try:
        parameters = signature(callable_obj).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind == Parameter.VAR_KEYWORD or parameter.name == keyword
        for parameter in parameters
    )


def _strip_code_fence(text: str) -> str:
    """Remove any Markdown fence lines (```lang) from the text."""

    lines = text.splitlines()
    cleaned = [line for line in lines if not line.lstrip().startswith("```")]
    return "\n".join(cleaned)


def _coerce_text_fragments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        fragments: list[str] = []
        for item in value:
            fragments.extend(_coerce_text_fragments(item))
        return fragments
    if isinstance(value, dict):
        fragments = []
        for key in ("text", "content", "value", "delta"):
            if key in value:
                fragments.extend(_coerce_text_fragments(value[key]))
        return fragments

    fragments = []
    for attr in ("text", "content", "value", "delta"):
        attr_value = getattr(value, attr, None)
        if attr_value is not None:
            fragments.extend(_coerce_text_fragments(attr_value))
    return fragments


class _StreamingCodeFenceStripper:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        emitted: list[str] = []
        while True:
            newline_index = self._buffer.find("\n")
            if newline_index == -1:
                break
            line = self._buffer[: newline_index + 1]
            self._buffer = self._buffer[newline_index + 1 :]
            if line.lstrip().startswith("```"):
                continue
            emitted.append(line)
        return "".join(emitted)

    def finish(self) -> str:
        trailing = self._buffer
        self._buffer = ""
        if trailing and not trailing.lstrip().startswith("```"):
            return trailing
        return ""


@dataclass
class Coder:
    """Use a language model to generate code and write it to a file."""

    provider: str = "openai"  # "openai", "zhipu", "deepseek", "qwen", or "111api"
    model: str = "gpt-4.1-mini"
    api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    system_prompt: str = (
        "You are a careful software engineer. Return only runnable code "
        "without extra commentary."
    )
    zhipu_thinking: Optional[dict] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    oneoneoneapi_base_url: str = "https://111api.chat/v1"
    timeout: Optional[float] = None
    client: Optional[object] = None
    use_streaming: bool = True

    def __post_init__(self) -> None:
        self.timeout = self.timeout if self.timeout is not None else _resolve_timeout(self.provider)

        # Allow dependency injection of a preconfigured client for tests.
        if self.client is None:
            if self.provider == "openai":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` or pass a compatible client instance."
                    )
                resolved_key = self.api_key or os.getenv("OPENAI_API_KEY")
                resolved_base_url = self.openai_base_url or os.getenv("OPENAI_BASE_URL")
                if not resolved_key:
                    raise ValueError(
                        "Missing OpenAI API key; set OPENAI_API_KEY or pass api_key."
                    )
                client_kwargs = {"api_key": resolved_key}
                if resolved_base_url:
                    client_kwargs["base_url"] = resolved_base_url
                if self.timeout is not None and _accepts_keyword(OpenAI, "timeout"):
                    client_kwargs["timeout"] = self.timeout
                self.client = OpenAI(**client_kwargs)
            elif self.provider == "zhipu":
                if ZhipuAiClient is None:
                    raise ImportError(
                        "zai is not installed and no client was provided. "
                        "Install `zai` or pass a compatible Zhipu client."
                    )
                resolved_key = self.api_key or os.getenv("ZHIPU_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing ZHIPU_API_KEY; set env or pass api_key.")
                client_kwargs = {"api_key": resolved_key}
                if self.timeout is not None and _accepts_keyword(ZhipuAiClient, "timeout"):
                    client_kwargs["timeout"] = self.timeout
                self.client = ZhipuAiClient(**client_kwargs)
            elif self.provider == "deepseek":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` to use deepseek provider."
                    )
                resolved_key = self.api_key or os.getenv("DEEPSEEK_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing DEEPSEEK_API_KEY; set env or pass api_key.")
                client_kwargs = {"api_key": resolved_key, "base_url": self.deepseek_base_url}
                if self.timeout is not None and _accepts_keyword(OpenAI, "timeout"):
                    client_kwargs["timeout"] = self.timeout
                self.client = OpenAI(**client_kwargs)
            elif self.provider == "qwen":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` to use qwen provider."
                    )
                resolved_key = self.api_key or os.getenv("DASHSCOPE_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing DASHSCOPE_API_KEY; set env or pass api_key.")
                client_kwargs = {"api_key": resolved_key, "base_url": self.qwen_base_url}
                if self.timeout is not None and _accepts_keyword(OpenAI, "timeout"):
                    client_kwargs["timeout"] = self.timeout
                self.client = OpenAI(**client_kwargs)
            elif self.provider == "111api":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` to use 111api provider."
                    )
                resolved_key = self.api_key or os.getenv("ONEONEONEAPI_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing ONEONEONEAPI_API_KEY; set env or pass api_key.")
                client_kwargs = {"api_key": resolved_key, "base_url": self.oneoneoneapi_base_url}
                if self.timeout is not None and _accepts_keyword(OpenAI, "timeout"):
                    client_kwargs["timeout"] = self.timeout
                self.client = OpenAI(**client_kwargs)
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")

    def generate_code(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
    ) -> str:
        """Call the LLM and return the generated code as plain text."""

        content = "".join(
            self.iter_code_chunks(
                user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        return _strip_code_fence(content)

    def _build_completion_kwargs(
        self,
        user_prompt: str,
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("LLM client is not configured.")

        extra_kwargs: dict[str, Any] = {}
        if self.provider == "zhipu":
            extra_kwargs["thinking"] = self.zhipu_thinking or {"type": "enabled"}
        if self.timeout is not None and _accepts_keyword(self.client.chat.completions.create, "timeout"):
            extra_kwargs["timeout"] = self.timeout
        if stream and _accepts_keyword(self.client.chat.completions.create, "stream"):
            extra_kwargs["stream"] = True

        return {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **extra_kwargs,
        }

    def _extract_choice_text(self, choice: Any) -> str:
        if choice is None:
            return ""
        for attr in ("delta", "message"):
            value = getattr(choice, attr, None)
            if value is None:
                continue
            fragments = _coerce_text_fragments(value)
            if fragments:
                return "".join(fragments)
        return ""

    def _iter_response_text_chunks(self, response: Any) -> Iterator[str]:
        choices = getattr(response, "choices", None)
        if choices is not None:
            for choice in choices:
                text = self._extract_choice_text(choice)
                if text:
                    yield text
            return

        if hasattr(response, "__iter__"):
            for event in response:
                event_choices = getattr(event, "choices", None) or []
                for choice in event_choices:
                    text = self._extract_choice_text(choice)
                    if text:
                        yield text

    def _request_completion(self, request_kwargs: dict[str, Any]) -> tuple[Any, bool]:
        stream_requested = bool(request_kwargs.get("stream"))
        try:
            return self.client.chat.completions.create(**request_kwargs), stream_requested
        except Exception as exc:
            if not stream_requested:
                raise exc

            fallback_kwargs = dict(request_kwargs)
            fallback_kwargs.pop("stream", None)
            LOGGER.warning(
                "Streaming LLM request failed for provider=%s model=%s; retrying without stream: %s",
                self.provider,
                self.model,
                exc,
            )
            return self.client.chat.completions.create(**fallback_kwargs), False

    def iter_code_chunks(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
    ) -> Iterator[str]:
        """Yield generated text chunks from the LLM, using streaming when available."""

        if self.client is None:
            raise RuntimeError("LLM client is not configured.")

        request_kwargs = self._build_completion_kwargs(
            user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=self.use_streaming,
        )

        LOGGER.debug(
            "Submitting LLM request provider=%s model=%s temperature=%s max_tokens=%s prompt_chars=%s stream=%s",
            self.provider,
            self.model,
            temperature,
            max_tokens,
            len(user_prompt),
            bool(request_kwargs.get("stream")),
        )

        try:
            response, used_stream = self._request_completion(request_kwargs)
        except Exception as exc:  # pragma: no cover - runtime failures
            LOGGER.error(
                "LLM call failed provider=%s model=%s: %s",
                self.provider,
                self.model,
                exc,
                exc_info=True,
            )
            raise LLMGenerationError(f"LLM call failed: {exc}") from exc

        saw_content = False
        total_chars = 0
        for chunk in self._iter_response_text_chunks(response):
            if not chunk:
                continue
            saw_content = True
            total_chars += len(chunk)
            yield chunk

        if not saw_content:
            LOGGER.error(
                "LLM returned empty content provider=%s model=%s response=%r",
                self.provider,
                self.model,
                response,
            )
            raise LLMGenerationError("LLM returned empty content.")

        LOGGER.debug(
            "Completed LLM response provider=%s model=%s chars=%s streamed=%s",
            self.provider,
            self.model,
            total_chars,
            used_stream,
        )

    def write_code_to_file(self, code: str, file_path: str, *, overwrite: bool = True) -> Path:
        """Write code to the target file, creating parent directories as needed."""

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and not overwrite:
            raise FileExistsError(f"File already exists and overwrite is False: {path}")

        LOGGER.debug("Writing generated code to %s overwrite=%s", path, overwrite)
        path.write_text(code, encoding="utf-8")
        return path

    def write_code_chunks_to_file(
        self,
        code_chunks: Iterator[str],
        file_path: str,
        *,
        overwrite: bool = True,
    ) -> Path:
        """Write generated code chunks to disk as they arrive from the model."""

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and not overwrite:
            raise FileExistsError(f"File already exists and overwrite is False: {path}")

        stripper = _StreamingCodeFenceStripper()
        wrote_output = False
        try:
            with path.open("w", encoding="utf-8") as handle:
                for chunk in code_chunks:
                    sanitized = stripper.feed(chunk)
                    if not sanitized:
                        continue
                    handle.write(sanitized)
                    handle.flush()
                    wrote_output = True

                trailing = stripper.finish()
                if trailing:
                    handle.write(trailing)
                    handle.flush()
                    wrote_output = True
        except Exception:
            if not wrote_output and path.exists():
                path.unlink(missing_ok=True)
            raise

        LOGGER.debug("Progressively wrote generated code to %s overwrite=%s", path, overwrite)
        return path

    def code_to_file(
        self,
        user_prompt: str,
        file_path: str,
        *,
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = MAX_TOKENS,
    ) -> Path:
        """Generate code from the prompt and persist it to `file_path`."""

        return self.write_code_chunks_to_file(
            self.iter_code_chunks(user_prompt, temperature=temperature, max_tokens=max_tokens),
            file_path,
            overwrite=overwrite,
        )



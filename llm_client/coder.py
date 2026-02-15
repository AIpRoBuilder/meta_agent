"""LLM-backed coder utility.

The `Coder` class wraps a chat model call and writes the generated code
to disk. By default it uses the `openai` Python client but you can supply
any drop-in client exposing a `chat.completions.create` method that
returns a response with `choices[0].message.content`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


def _strip_code_fence(text: str) -> str:
    """Remove any Markdown fence lines (```lang) from the text."""

    lines = text.splitlines()
    cleaned = [line for line in lines if not line.lstrip().startswith("```")]
    return "\n".join(cleaned)


@dataclass
class Coder:
    """Use a language model to generate code and write it to a file."""

    provider: str = "openai"  # "openai", "zhipu", "deepseek", or "qwen"
    model: str = "gpt-4.1-mini"
    api_key: Optional[str] = None
    system_prompt: str = (
        "You are a careful software engineer. Return only runnable code "
        "without extra commentary."
    )
    zhipu_thinking: Optional[dict] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    client: Optional[object] = None

    def __post_init__(self) -> None:
        # Allow dependency injection of a preconfigured client for tests.
        if self.client is None:
            if self.provider == "openai":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` or pass a compatible client instance."
                    )
                resolved_key = self.api_key or os.getenv("OPENAI_API_KEY")
                if not resolved_key:
                    raise ValueError(
                        "Missing OpenAI API key; set OPENAI_API_KEY or pass api_key."
                    )
                self.client = OpenAI(api_key=resolved_key)
            elif self.provider == "zhipu":
                if ZhipuAiClient is None:
                    raise ImportError(
                        "zai is not installed and no client was provided. "
                        "Install `zai` or pass a compatible Zhipu client."
                    )
                resolved_key = self.api_key or os.getenv("ZHIPU_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing ZHIPU_API_KEY; set env or pass api_key.")
                self.client = ZhipuAiClient(api_key=resolved_key)
            elif self.provider == "deepseek":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` to use deepseek provider."
                    )
                resolved_key = self.api_key or os.getenv("DEEPSEEK_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing DEEPSEEK_API_KEY; set env or pass api_key.")
                self.client = OpenAI(api_key=resolved_key, base_url=self.deepseek_base_url)
            elif self.provider == "qwen":
                if OpenAI is None:
                    raise ImportError(
                        "openai is not installed and no client was provided. "
                        "Install `openai` to use qwen provider."
                    )
                resolved_key = self.api_key or os.getenv("DASHSCOPE_API_KEY")
                if not resolved_key:
                    raise ValueError("Missing DASHSCOPE_API_KEY; set env or pass api_key.")
                self.client = OpenAI(api_key=resolved_key, base_url=self.qwen_base_url)
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")

    def generate_code(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        """Call the LLM and return the generated code as plain text."""

        if self.client is None:
            raise RuntimeError("LLM client is not configured.")

        extra_kwargs = {}
        if self.provider == "zhipu":
            extra_kwargs["thinking"] = self.zhipu_thinking or {"type": "enabled"}

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                **extra_kwargs,
            )
        except Exception as exc:  # pragma: no cover - runtime failures
            raise LLMGenerationError(f"LLM call failed: {exc}") from exc

        content = ""
        if getattr(response, "choices", None):
            choice = response.choices[0]
            content = getattr(getattr(choice, "message", None), "content", "") or ""

        if not content:
            raise LLMGenerationError("LLM returned empty content.")

        return _strip_code_fence(content)

    def write_code_to_file(self, code: str, file_path: str, *, overwrite: bool = True) -> Path:
        """Write code to the target file, creating parent directories as needed."""

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and not overwrite:
            raise FileExistsError(f"File already exists and overwrite is False: {path}")

        path.write_text(code, encoding="utf-8")
        return path

    def code_to_file(
        self,
        user_prompt: str,
        file_path: str,
        *,
        overwrite: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> Path:
        """Generate code from the prompt and persist it to `file_path`."""

        code = self.generate_code(user_prompt, temperature=temperature, max_tokens=max_tokens)
        return self.write_code_to_file(code, file_path, overwrite=overwrite)



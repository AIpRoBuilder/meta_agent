from pathlib import Path
from types import SimpleNamespace

from meta_agent.llm_client.coder import Coder


class _FakeStreamChunk:
    def __init__(self, content: str):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]


class _FakeStreamingCompletions:
    def __init__(self, responses, *, probe_path: Path | None = None, expected_partial: str | None = None):
        self._responses = list(responses)
        self.probe_path = probe_path
        self.expected_partial = expected_partial
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self._responses.pop(0)

        def _iter_chunks():
            for index, chunk in enumerate(chunks):
                if index == 1 and self.probe_path is not None and self.expected_partial is not None:
                    assert self.probe_path.read_text(encoding="utf-8") == self.expected_partial
                yield _FakeStreamChunk(chunk)

        return _iter_chunks()


class _FakeStreamingClient:
    def __init__(self, responses, *, probe_path: Path | None = None, expected_partial: str | None = None):
        self.chat = SimpleNamespace(
            completions=_FakeStreamingCompletions(
                responses,
                probe_path=probe_path,
                expected_partial=expected_partial,
            )
        )


class _FallbackStreamingCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            raise RuntimeError("stream unsupported")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback = True\n"))]
        )


class _FallbackStreamingClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FallbackStreamingCompletions())


def test_generate_code_aggregates_streamed_chunks_and_requests_streaming() -> None:
    client = _FakeStreamingClient([["```python\n", "value = 1\n", "print(value)\n", "```"]])
    coder = Coder(client=client)

    generated = coder.generate_code("write code")

    assert generated == "value = 1\nprint(value)"
    assert client.chat.completions.calls[0]["stream"] is True


def test_code_to_file_writes_stream_progressively(tmp_path: Path) -> None:
    target_path = tmp_path / "generated.py"
    client = _FakeStreamingClient(
        [["```python\nalpha = 1\n", "beta = 2\n", "```"]],
        probe_path=target_path,
        expected_partial="alpha = 1\n",
    )
    coder = Coder(client=client)

    written_path = coder.code_to_file("write code", str(target_path))

    assert written_path == target_path
    assert target_path.read_text(encoding="utf-8") == "alpha = 1\nbeta = 2\n"


def test_generate_code_falls_back_to_non_stream_when_stream_fails() -> None:
    client = _FallbackStreamingClient()
    coder = Coder(client=client)

    generated = coder.generate_code("write code")

    assert generated == "fallback = True"
    assert client.chat.completions.calls[0]["stream"] is True
    assert "stream" not in client.chat.completions.calls[1]
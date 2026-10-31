from __future__ import annotations

import pytest

from geoagent.llm.client import LLMClient, LLMResult


class _ScriptedClient(LLMClient):
    """LLMClient with ``chat`` replaced by a script of canned results."""

    def __init__(self, *results: LLMResult) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, int | None]] = []

    def chat(self, messages, *, tag="llm", max_tokens=None, **kwargs):  # type: ignore[override]
        self.calls.append((tag, max_tokens))
        return self.results.pop(0)


def _result(text: str, finish_reason: str) -> LLMResult:
    return LLMResult(text=text, message=None, finish_reason=finish_reason)


def test_truncated_json_is_retried_with_a_wider_budget() -> None:
    client = _ScriptedClient(
        _result('{"assessment_score": 0.9', "length"),
        _result('{"assessment_score": 0.91, "verdict": "ok"}', "stop"),
    )
    report = client.complete_json("system", "user", max_tokens=4096)
    assert report["assessment_score"] == 0.91
    assert [call[1] for call in client.calls] == [4096, 8192]
    assert client.calls[1][0].endswith(":length_retry")


def test_truncation_after_retry_raises_instead_of_returning_partial_json() -> None:
    client = _ScriptedClient(
        _result('{"assessment_score": 0.9', "length"),
        _result('{"assessment_score": 0.9', "length"),
    )
    with pytest.raises(ValueError, match="truncated"):
        client.complete_json("system", "user", max_tokens=4096)

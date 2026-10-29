from __future__ import annotations

import json
from types import SimpleNamespace

from geoagent.agents.geometry_agent import GeometryAgent, merge_geometry_submission
from geoagent.llm.client import LLMResult
from geoagent.state.schemas import GeometricEvidenceState

SUBMISSION = {
    "summary": "point A on a segment",
    "objects": [
        {"id": "point_A", "type": "point", "label": "A", "coords": {"px": [10, 20]}, "status": "confirmed"},
        {"id": "seg_AB", "type": "segment", "coords": {"a_px": [10, 20], "b_px": [50, 20]}},
        {"id": "bogus", "type": "blob", "coords": {}},
    ],
    "relations": [{"subject": "point_A", "relation": "on_segment", "object": "seg_AB"}],
    "conflicts": [],
    "unresolved": ["narrow gap may be dashed"],
}


def _state(tmp_path) -> GeometricEvidenceState:
    return GeometricEvidenceState(image_path=str(tmp_path / "img.png"), image_size={"width": 100, "height": 100})


def test_merge_validates_types_and_relations(tmp_path) -> None:
    state = _state(tmp_path)
    merged = merge_geometry_submission(state, SUBMISSION)
    assert merged["objects"] == 2
    assert merged["relations"] == 1
    assert len(merged["rejected"]) == 1
    assert state.objects["point_A"].label == "A"
    assert state.unresolved_issues


class _FakeClient:
    """First reply is length-truncated; the second submits geometry via a tool call."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    def build_content(self, text, image_paths=None):
        return text

    def chat(self, messages, **kwargs):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.calls == 1:
            text = '{"summary": "partial", "objects": []} trailing prose that got cut'
            message = SimpleNamespace(content=text, tool_calls=[])
            return LLMResult(text=text, message=message, tool_calls=[], finish_reason="length", usage={})
        function = SimpleNamespace(name="submit_geometry", arguments=json.dumps({"json": json.dumps(SUBMISSION)}))
        call = SimpleNamespace(id="call_1", function=function)
        message = SimpleNamespace(content=None, tool_calls=[call])
        return LLMResult(text="", message=message, tool_calls=[call], finish_reason="tool_calls", usage={})


def test_truncated_prefix_is_not_accepted_as_submission(tmp_path) -> None:
    state = _state(tmp_path)
    client = _FakeClient()
    agent = GeometryAgent(client, state, tmp_path / "out")
    result = agent.run("consolidate evidence", cv_calls_left=0)

    assert client.calls == 2
    assert result["ok"] is True
    assert result["merged"]["objects"] == 2
    # The truncated reply parsed as {"summary": ..., "objects": []}; it must not be merged.
    assert "point_A" in state.objects
    assert any(
        message.get("role") == "user" and "cut off" in str(message.get("content", ""))
        for message in client.seen_messages[1]
    )

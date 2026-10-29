from __future__ import annotations

import importlib

import pytest

MODULES = [
    "geoagent.config",
    "geoagent.llm.client",
    "geoagent.state.schemas",
    "geoagent.state.evidence_store",
    "geoagent.datasets.trigeobench",
    "geoagent.cv_tools.registry",
    "geoagent.cv_tools.line_detection",
    "geoagent.cv_tools.circle_detection",
    "geoagent.cv_tools.label_detection",
    "geoagent.cv_tools.right_angle",
    "geoagent.cv_tools.text_line_separation",
    "geoagent.tools.compiler",
    "geoagent.tools.renderer",
    "geoagent.tools.verifier",
    "geoagent.agents.schemas",
    "geoagent.agents.prompts",
    "geoagent.agents.geometry_agent",
    "geoagent.agents.tikz_agent",
    "geoagent.agents.critic_agent",
    "geoagent.agents.supervisor",
    "geoagent.orchestration.ingest",
    "geoagent.orchestration.runner",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name) is not None


def test_supervisor_tools_are_complete() -> None:
    from geoagent.agents.schemas import SUPERVISOR_TOOLS

    names = {tool["function"]["name"] for tool in SUPERVISOR_TOOLS}
    assert {"call_cv_tool", "inspect_image", "run_geometry_agent", "run_tikz_agent", "run_critic", "finish"} <= names


def test_model_defaults_to_haiku_5_5(settings) -> None:
    assert settings.model.model == "claude-haiku-5-5"

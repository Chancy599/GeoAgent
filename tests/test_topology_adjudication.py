from types import SimpleNamespace
from PIL import Image, ImageDraw

from geoagent.agents.critic_agent import CriticAgent
from geoagent.orchestration.runner import GeoAgentRunner, _finish_gate_problem
from geoagent.state.schemas import GeometricEvidenceState, GeometryObject
from geoagent.state.topology import build_topology_plan, check_topology


def test_critic_confirms_current_cv_candidate_and_rechecks_the_render(tmp_path):
    state = GeometricEvidenceState(image_path="source.png", image_size={"width": 400, "height": 300})
    for label, point in {"G": [80, 100], "N": [180, 100]}.items():
        state.add_object(GeometryObject(id=label, type="point", label=label, coords={"px": point},
                                        source="cv:bind_point_labels"))
        state.label_bindings[label] = label
    state.add_object(GeometryObject(id="dash", type="segment", source="cv:detect_lines",
                                    coords={"a_px": [68, 100], "b_px": [193, 100]},
                                    style={"line": "dashed"}))

    plan = build_topology_plan(state)
    case, = plan["pending"]
    assert plan["required_edges"] == []
    assert case["options"] == [["G", "N"]]

    class Client:
        edge = ["G", "X"]

        def complete_json(self, system, user, **kwargs):
            assert "PENDING ENDPOINT CASES" in user and case["id"] in user
            return {"verdict": "Looks close", "assessment_score": 0.95, "topology_decisions": [
                {"case_id": case["id"], "edge": self.edge, "reason": "Visible endpoint"}
            ]}

    client = Client()
    png = tmp_path / "render.png"
    png.write_bytes(b"render")
    version = state.add_tikz_version(r"\draw (0,0)--(1,0);", png_path=str(png))
    version.ok = True
    runner = object.__new__(GeoAgentRunner)
    runner.state = state
    runner._visual_left = lambda: 1
    runner._critic_cache = {}
    runner.ctx = SimpleNamespace(original=lambda: "source.png")
    runner.critic_agent = CriticAgent(client, state)

    assert runner._do_critic({})["topology_decisions"] == []
    assert build_topology_plan(state) == plan
    client.edge = ["N", "G"]
    report = runner._do_critic({})
    assert report["topology_decisions"][0]["edge"] == ["G", "N"]
    assert report["topology_check"]["missing_edges"] == [["G", "N"]]
    assert report["must_repair"]
    assert build_topology_plan(state)["required_edges"] == [["G", "N"]]
    assert state.objects["G"].coords["px"] == [80, 100]

    state.objects["dash"].coords["a_px"] = [69, 100]
    revised = build_topology_plan(state)
    assert revised["required_edges"] == []
    assert revised["pending"][0]["id"] != case["id"]


def test_wrong_shared_vertex_cannot_win_over_a_verified_version():
    definitions = r"""
\coordinate (A) at (0,0);
\coordinate (E) at (1,1.1);
\coordinate (C) at (2,2);
\coordinate (B) at (2,0);
"""
    plan = {"required_edges": [["A", "E"], ["B", "E"], ["C", "E"]]}
    bad = definitions + r"\draw (A)--(C); \draw (B)--(1,1.1);"
    good = definitions + r"\draw (A)--(E)--(C); \draw (B)--(E);"
    state = GeometricEvidenceState(image_path="source.png")
    for tex, score in [(bad, 0.99), (good, 0.8)]:
        version = state.add_tikz_version(tex)
        version.topology_check = check_topology(tex, plan)
        version.ok = True
        version.png_path = "render.png"
        state.attach_critic(version.version, {}, score)
        state.update_best()
        if tex == bad:
            assert version.topology_check["missing_edges"] == plan["required_edges"]
            assert _finish_gate_problem(state, visual_left=0, tool_left=1)[0] == "unverified_topology"
    assert state.best_version == 2


def test_collinear_named_subdivision_can_satisfy_a_straight_edge():
    plan = {"required_edges": [["A", "B"]]}
    tex = r"""
\coordinate (A) at (0,0);
\coordinate (E) at (1,0);
\coordinate (B) at (2,0);
\draw (A)--(E);
\draw (E)--(B);
"""
    assert check_topology(tex, plan)["passed"]
    assert not check_topology(tex.replace("(1,0)", "(1,0.1)"), plan)["passed"]


def test_continuous_source_ink_certifies_overshooting_solid_stroke(tmp_path):
    image_path = tmp_path / "source.png"
    state = GeometricEvidenceState(image_path=str(image_path), image_size={"width": 400, "height": 300})
    for label, point in {"C": [180, 100], "F": [80, 100]}.items():
        state.add_object(GeometryObject(id=label, type="point", label=label, coords={"px": point},
                                        source="cv:bind_point_labels"))
        state.label_bindings[label] = label
    state.add_object(GeometryObject(id="stroke", type="segment", source="cv:detect_lines",
                                    coords={"a_px": [78, 100], "b_px": [192, 100]}, style={"line": "solid"}))
    image = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(image).line((80, 100, 155, 100), fill=0, width=3)
    image.save(image_path)
    assert build_topology_plan(state)["ink_confirmed_edges"] == []
    ImageDraw.Draw(image).line((155, 100, 180, 100), fill=0, width=3)
    image.save(image_path)
    plan = build_topology_plan(state)
    assert plan["ink_confirmed_edges"] == [["C", "F"]]
    assert plan["required_edges"] == [["C", "F"]]

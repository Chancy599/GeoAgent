from types import SimpleNamespace
from PIL import Image, ImageDraw

from geoagent.agents.critic_agent import CriticAgent
from geoagent.orchestration.runner import GeoAgentRunner, _finish_gate_problem
from geoagent.state.construction import add_construction_candidates, merge_construction_plan
from geoagent.state.coordinate_contract import apply_coordinate_contract, build_coordinate_contract
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
    duplicated = check_topology(tex + r'\draw (A)--(B);', plan)
    assert duplicated['overlapping_strokes'] == [[['A', 'B'], ['A', 'E']], [['A', 'B'], ['B', 'E']]]
    assert not duplicated['passed']


def test_source_square_orientation_at_a_clipped_dashed_foot(tmp_path):
    source = tmp_path / 'source.png'
    image = Image.new('L', (400, 300), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(50, 100), (350, 100)], fill=0, width=2)
    draw.line([(212, 100), (212, 112), (200, 112)], fill=0, width=2)
    for y in range(122, 239, 15):
        draw.line([(200, y), (200, min(y + 8, 240))], fill=0, width=2)
    image.save(source)
    state = GeometricEvidenceState(image_path=str(source), image_size={'width': 400, 'height': 300})
    for label, point in {'A': [50, 100], 'B': [350, 100], 'F': [200, 240]}.items():
        state.add_object(GeometryObject(id=label, type='point', label=label, coords={'px': point},
                                        source='cv:bind_point_labels'))
        state.label_bindings[label] = label
    for key, a, b, style in [('base', [50, 100], [350, 100], 'solid'),
                              ('dash', [201, 122], [201, 240], 'dashed')]:
        state.add_object(GeometryObject(id=key, type='segment', source='cv:detect_lines',
                                        coords={'a_px': a, 'b_px': b}, style={'line': style}))
    add_construction_candidates(state)
    merge_construction_plan(state, {
        'bindings': [{'label': 'N', 'point_id': 'junction_base_dash', 'reason': 'Foot on AB'}],
        'strokes': [{'edge': ['F', 'N'], 'style': 'dashed'}],
        'feet': [['F', 'N', 'A', 'B']],
        'angle_marks': [['F', 'N', 'A']],
    })
    plan = build_topology_plan(state)
    assert plan['required_marks']['N']['arms'] == ['B', 'F']
    points = build_coordinate_contract(state)['points']
    assert points['N']['px'] == [201, 100]
    assert points['N']['tikz'] == [points['F']['tikz'][0], points['A']['tikz'][1]]
    tex = r'''
\coordinate (A) at (0,0); \coordinate (B) at (3,0);
\coordinate (N) at (1,0); \coordinate (F) at (1,-1);
\draw (A)--(N)--(B);
\draw[dashed] (F)--(N);
\draw pic[draw] {right angle=F--N--B};
'''
    assert check_topology(tex, plan)['passed']
    assert check_topology(tex.replace('F--N--B', 'F--N--A'), plan)['unverified_marks'] == ['N']
    assert check_topology(tex.replace('[dashed]', ''), plan)['unverified_styles'] == [
        {'edge': ['F', 'N'], 'style': 'dashed'}]


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


def test_solid_extension_needs_ink_past_the_labelled_junction(tmp_path):
    path = tmp_path / 'source.png'
    state = GeometricEvidenceState(image_path=str(path), image_size={'width': 200, 'height': 180})
    for label, point in {'A': [50, 150], 'D': [50, 100], 'G': [50, 60], 'B': [130, 60]}.items():
        state.add_object(GeometryObject(id=label, type='point', label=label, coords={'px': point},
                                        source='cv:bind_point_labels'))
        state.label_bindings[label] = label
    state.add_object(GeometryObject(id='vertical', type='segment', source='cv:detect_lines',
                                    coords={'a_px': [50, 25], 'b_px': [50, 150]}, style={'line': 'solid'}))
    state.add_object(GeometryObject(id='truncated', type='segment', source='cv:detect_lines',
                                    coords={'a_px': [50, 60], 'b_px': [50, 130]}, style={'line': 'solid'}))
    state.add_object(GeometryObject(id='C', type='point', label='C', coords={'px': [130, 100]},
                                    source='cv:bind_point_labels'))
    state.label_bindings['C'] = 'C'
    image = Image.new('L', (200, 180), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(50, 60), (50, 150)], fill=0, width=2)
    draw.line([(50, 60), (130, 60)], fill=0, width=2)
    draw.line([(50, 100), (130, 100)], fill=0, width=2)
    image.save(path)
    merge_construction_plan(state, {'strokes': [{'edge': list(edge), 'style': 'solid'} for edge in ('AD', 'DG', 'GB', 'DC')]})
    assert state.meta['source_construction']['extensions'] == {}
    draw.line([(50, 25), (50, 60)], fill=0, width=2)
    image.save(path)
    merge_construction_plan(state, {})
    plan = build_topology_plan(state)
    contract = build_coordinate_contract(state)
    assert contract['points']['GeoTailG']['px'] == [50, 25]
    partial = r'\begin{tikzpicture}\draw (A)--(D)--(G);\draw (G)--(B);\draw (D)--(C);\end{tikzpicture}'
    without_tail, _ = apply_coordinate_contract(partial, contract)
    assert ['G', 'GeoTailG'] in check_topology(without_tail, plan)['missing_edges']
    with_tail, _ = apply_coordinate_contract(partial.replace('(D)--(G);', '(D)--(G)--(GeoTailG);'), contract)
    assert check_topology(with_tail, plan)['passed']

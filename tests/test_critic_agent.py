from __future__ import annotations

from pathlib import Path

from PIL import Image

from geoagent.agents.critic_agent import CriticAgent, build_comparison_image
from geoagent.state.schemas import GeometricEvidenceState


def _solid(path: Path, size: tuple[int, int], colour: tuple[int, int, int]) -> Path:
    Image.new("RGB", size, colour).save(path)
    return path


def test_comparison_panels_have_equal_size_and_original_on_the_left(tmp_path: Path) -> None:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (100, 200), (0, 0, 255))

    out = build_comparison_image(original, render, tmp_path / "compare.png", panel_px=100, gap_px=10)
    with Image.open(out) as im:
        assert im.size == (210, 100)
        assert im.getpixel((50, 50)) == (255, 0, 0)      # left panel, centred original
        assert im.getpixel((160, 50)) == (0, 0, 255)     # right panel, centred render
        assert im.getpixel((105, 50)) == (225, 225, 225)  # separator
        assert im.getpixel((50, 5)) == (255, 255, 255)   # letterbox padding


class _RecordingClient:
    def __init__(self, report: dict) -> None:
        self.report = report
        self.images: list[str] = []
        self.user = ""

    def complete_json(self, system, user, *, images, tag, max_tokens):
        self.user = user
        self.images = [str(p) for p in images]
        return dict(self.report)


def _state(image: Path) -> GeometricEvidenceState:
    return GeometricEvidenceState(
        image_path=str(image),
        image_size={"width": 200, "height": 100},
    )


def test_critic_sends_one_equal_size_comparison_image(tmp_path: Path) -> None:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (100, 200), (0, 0, 255))
    client = _RecordingClient({"assessment_score": 0.9, "verdict": "close"})

    agent = CriticAgent(client, _state(original), out_dir=tmp_path / "run")
    report = agent.run(original, render, version=3, focus="labels")

    assert len(client.images) == 1
    assert Path(client.images[0]).name == "compare_v3.png"
    assert Path(client.images[0]).is_file()
    assert "LEFT panel is the ORIGINAL" in client.user
    assert "RIGHT panel is the RENDERED" in client.user
    assert report["version"] == 3
    assert report["assessment_score"] == 0.9


def test_critic_falls_back_to_two_images_without_out_dir(tmp_path: Path) -> None:
    original = _solid(tmp_path / "original.png", (200, 100), (255, 0, 0))
    render = _solid(tmp_path / "render.png", (100, 200), (0, 0, 255))
    client = _RecordingClient({"assessment_score": 0.8, "verdict": "ok"})

    agent = CriticAgent(client, _state(original), out_dir=None)
    agent.run(original, render, version=1)

    assert client.images == [str(original), str(render)]
    assert "first image" in client.user

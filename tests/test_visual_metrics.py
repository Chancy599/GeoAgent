from __future__ import annotations

import numpy as np
from PIL import Image

from geoagent.evaluation.visual_metrics import _cosine, load_rgb, ssim_pair


def _save(path, array):
    Image.fromarray(np.asarray(array, dtype=np.uint8)).save(path)
    return path


def test_ssim_identical_images_is_one(tmp_path) -> None:
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 256, size=(120, 160, 3), dtype=np.uint8)
    a = _save(tmp_path / "a.png", pixels)
    b = _save(tmp_path / "b.png", pixels.copy())
    assert ssim_pair(a, b) > 0.999


def test_ssim_is_size_agnostic_and_penalises_difference(tmp_path) -> None:
    rng = np.random.default_rng(1)
    pixels = rng.integers(0, 256, size=(200, 300, 3), dtype=np.uint8)
    a = _save(tmp_path / "a.png", pixels)
    bigger = _save(tmp_path / "bigger.png", np.array(Image.fromarray(pixels).resize((600, 400))))
    assert ssim_pair(a, bigger) > 0.95  # resampling costs a little structure
    inverted = _save(tmp_path / "inv.png", 255 - pixels)
    assert ssim_pair(a, inverted) < 0.5


def test_load_rgb_composites_transparency_on_white(tmp_path) -> None:
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    path = tmp_path / "alpha.png"
    image.save(path)
    assert load_rgb(path).getpixel((5, 5)) == (255, 255, 255)


def test_cosine_similarity_is_scale_invariant() -> None:
    a = np.array([[3.0, 4.0], [1.0, 0.0]])
    b = np.array([[30.0, 40.0], [0.0, 1.0]])
    similarity = _cosine(a, b)
    assert similarity[0] > 0.999
    assert abs(similarity[1]) < 1e-9

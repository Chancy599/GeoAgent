"""Visual similarity metrics from TriGeoBench Appendix C.2.

The preprocessing and aggregation follow the fixed whole-image protocol used by
the TriGeoBench experiment code (``geom2code/scripts/whole_visual_protocol.py``),
so numbers are comparable with that project:

* **SSIM** (Eq. 2): opaque white background, longest side scaled to 1000 and
  centred on a 1000x1000 white canvas (LANCZOS), grayscale, no crop or
  registration; ``skimage`` SSIM with Gaussian weights, sigma=1.5, win=11.
* **CLIP / DINO** (Eq. 3): cosine similarity of projected CLIP ViT-L/14 visual
  features (official OpenAI preprocessing) and DINOv2-base CLS features
  (official slow processor: short edge 256, centre crop 224).

Weights are local only (``~/.cache/clip/ViT-L-14.pt``) and are SHA-256 verified
before use, so evaluation never silently substitutes a different checkpoint.

Reporting convention: SSIM/CLIP/DINO x10^2 (higher is better).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from ..datasets.trigeobench import normalise_stem

CANVAS_SIZE = 1000
SSIM_KWARGS = {
    "data_range": 1.0,
    "gaussian_weights": True,
    "sigma": 1.5,
    "win_size": 11,
    "use_sample_covariance": False,
    "K1": 0.01,
    "K2": 0.03,
}
CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "visual-encoders"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _encoder_config(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing encoder config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_weights(path: str | Path, expected: str | None, label: str) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"missing {label} weights: {resolved}")
    if expected and _sha256(resolved) != expected:
        raise ValueError(f"{label} weights do not match the recorded SHA-256: {resolved}")
    return resolved


def load_rgb(path: str | Path) -> Image.Image:
    """Open an image on an opaque white background (renders often have alpha)."""
    with Image.open(path) as im:
        if im.mode == "RGB":
            return im.copy()
        rgba = im.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")


def canvas(image: Image.Image, *, size: int = CANVAS_SIZE) -> np.ndarray:
    """Fit the whole image by its longest side, centred on a white square."""
    scale = size / max(image.size)
    fitted = tuple(max(1, round(value * scale)) for value in image.size)
    offset = tuple((size - value) // 2 for value in fitted)
    out = Image.new("RGB", (size, size), "white")
    out.paste(image.resize(fitted, Image.Resampling.LANCZOS), offset)
    return np.asarray(out.convert("L"))


def ssim_pair(pred: str | Path, ref: str | Path) -> float:
    """SSIM (Eq. 2) on the fixed 1000px whole-image canvas."""
    from skimage.metrics import structural_similarity

    a = canvas(load_rgb(pred)).astype(np.float64) / 255.0
    b = canvas(load_rgb(ref)).astype(np.float64) / 255.0
    return float(structural_similarity(a, b, **SSIM_KWARGS))


def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-12, None)
    b_norm = b / np.clip(np.linalg.norm(b, axis=1, keepdims=True), 1e-12, None)
    return np.sum(a_norm * b_norm, axis=1)


def clip_embeddings(paths: Sequence[str | Path], *, batch_size: int = 4) -> np.ndarray:
    """Projected CLIP ViT-L/14 visual features (official preprocessing)."""
    import clip
    import torch

    config = _encoder_config("clip-model")
    weights = _verify_weights(config["weights_path"], config.get("weights_sha256"), "CLIP")
    torch.set_num_threads(4)
    model, preprocess = clip.load(str(weights), device="cpu", jit=False)
    visual = model.visual.eval()
    vectors: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(paths), batch_size):
            batch = torch.stack([preprocess(load_rgb(path)) for path in paths[start : start + batch_size]])
            vectors.append(visual(batch).float().numpy())
    return np.concatenate(vectors, axis=0)


def dino_embeddings(paths: Sequence[str | Path], *, batch_size: int = 8) -> np.ndarray:
    """DINOv2-base CLS features with the official slow processor."""
    import torch
    from transformers import AutoImageProcessor, Dinov2Model

    config = _encoder_config("dino-model")
    snapshot = Path(str(config["snapshot_path"]))
    for name, spec in (config.get("files") or {}).items():
        _verify_weights(snapshot / name, spec.get("sha256"), f"DINOv2 {name}")
    processor = AutoImageProcessor.from_pretrained(snapshot, local_files_only=True, use_fast=False)
    # Dinov2Model directly: AutoModel eagerly imports unrelated integrations
    # (timm) whose installed API may not match this transformers version.
    model = Dinov2Model.from_pretrained(
        snapshot, local_files_only=True, use_safetensors=True, attn_implementation="eager"
    ).float().eval()
    torch.set_num_threads(4)
    vectors: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(paths), batch_size):
            batch = processor(
                images=[load_rgb(path) for path in paths[start : start + batch_size]],
                return_tensors="pt",
            )
            vectors.append(model(**batch).last_hidden_state[:, 0, :].cpu().numpy())
    return np.concatenate(vectors, axis=0)


def evaluate(
    pred_dir: str | Path,
    ref_dir: str | Path,
    *,
    limit: int | None = None,
    stems: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Score every ``<stem>.png`` present in both directories.

    ``stems`` restricts scoring to an explicit subset (used to compare
    cohorts on the same shared valid images).
    """
    pred_root = Path(pred_dir)
    ref_root = Path(ref_dir)

    refs_by_stem: dict[str, Path] = {}
    for path in sorted(ref_root.iterdir()):
        if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            refs_by_stem.setdefault(normalise_stem(path.stem), path)
    all_stems = sorted(refs_by_stem)
    if stems is not None:
        wanted = set(stems)
        all_stems = [stem for stem in all_stems if stem in wanted]
    elif limit is not None:
        all_stems = all_stems[:limit]

    selected = [stem for stem in all_stems if (pred_root / f"{stem}.png").is_file()]
    missing = [stem for stem in all_stems if not (pred_root / f"{stem}.png").is_file()]
    if not selected:
        raise FileNotFoundError(f"no predicted PNGs in {pred_root} match {ref_root}")

    preds = [pred_root / f"{stem}.png" for stem in selected]
    refs = [refs_by_stem[stem] for stem in selected]

    ssims = np.array([ssim_pair(pred, ref) for pred, ref in zip(preds, refs)])
    clip = _cosine(clip_embeddings(preds), clip_embeddings(refs))
    dino = _cosine(dino_embeddings(preds), dino_embeddings(refs))

    per_image = [
        {
            "stem": stem,
            "ssim": round(float(ssims[index]), 6),
            "clip": round(float(clip[index]), 6),
            "dino": round(float(dino[index]), 6),
        }
        for index, stem in enumerate(selected)
    ]
    return {
        "schema": "visual-metrics.v1",
        "pred_dir": str(pred_root),
        "ref_dir": str(ref_root),
        "protocol": {
            "ssim": (
                f"whole image on white, longest side {CANVAS_SIZE}, centred in "
                f"{CANVAS_SIZE} square, LANCZOS, grayscale; skimage SSIM "
                "gaussian_weights=True, sigma=1.5, win_size=11, use_sample_covariance=False"
            ),
            "clip": "OpenAI CLIP ViT-L/14@224 visual projection, official preprocessing, cosine",
            "dino": "facebook/dinov2-base CLS, slow processor (short edge 256, crop 224), cosine",
            "reporting": "SSIM/CLIP/DINO x100 (higher better)",
            "only_common_images": len(missing) == 0,
        },
        "count": len(selected),
        "missing": missing,
        "per_image": per_image,
        "aggregate": {
            "ssim": round(float(ssims.mean()), 6),
            "clip": round(float(clip.mean()), 6),
            "dino": round(float(dino.mean()), 6),
        },
    }

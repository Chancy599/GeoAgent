"""TriGeoBench adapter (image + reference LaTeX pairs).

The dataset ships ``image/<stem>.png`` and ``latex/<stem>.tex``.  The reference
LaTeX is *never* passed to any agent during a run: it is only loaded by the
evaluation helper for offline comparison, and the demo UI can reveal it after
the fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
LATEX_SUFFIXES = (".tex", ".latex")


@dataclass(frozen=True)
class BenchItem:
    stem: str
    image_path: Path
    latex_path: Path | None
    width: int | None
    height: int | None

    def public(self, include_reference: bool = False) -> dict[str, Any]:
        data = {
            "stem": self.stem,
            "image_path": str(self.image_path),
            "width": self.width,
            "height": self.height,
            "has_reference": self.latex_path is not None,
        }
        if include_reference and self.latex_path is not None:
            data["reference_tex"] = self.latex_path.read_text(encoding="utf-8")
        return data


def _size_of(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None, None


def _find(base: Path, stem: str, suffixes: tuple[str, ...]) -> Path | None:
    for suffix in suffixes:
        candidate = base / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def scan_dataset(
    image_dir: str | Path,
    latex_dir: str | Path | None = None,
    *,
    limit: int | None = None,
) -> list[BenchItem]:
    """Pair every image with its reference TeX (if present), sorted by name."""
    images = Path(image_dir)
    if not images.exists():
        return []
    latex_root = Path(latex_dir) if latex_dir else None
    items: list[BenchItem] = []
    for path in sorted(images.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        stem = path.stem
        latex_path = _find(latex_root, stem, LATEX_SUFFIXES) if latex_root else None
        width, height = _size_of(path)
        items.append(BenchItem(stem=stem, image_path=path, latex_path=latex_path, width=width, height=height))
        if limit is not None and len(items) >= limit:
            break
    return items


def find_item(stem_or_path: str | Path, items: list[BenchItem]) -> BenchItem | None:
    needle = Path(stem_or_path).stem
    for item in items:
        if item.stem == needle:
            return item
    return None


def load_reference(stem_or_path: str | Path, items: list[BenchItem]) -> str | None:
    item = find_item(stem_or_path, items)
    if item is None or item.latex_path is None:
        return None
    return item.latex_path.read_text(encoding="utf-8")

"""Visual Context Manager.

Owns every image that may be sent to a model: the original figure, cached
region crops, and rendered TikZ previews.  Crops are produced on demand so the
Supervisor never has to re-send the full image every step.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..cv_tools.common import parse_roi


@dataclass
class CropRecord:
    region_id: str
    path: str
    box_px: list[int]
    box_norm: list[float]
    purpose: str = ""


@dataclass
class VisualContextManager:
    run_dir: Path
    image_path: str
    crops_dir: Path = field(init=False)
    renders_dir: Path = field(init=False)
    crops: dict[str, CropRecord] = field(default_factory=dict)
    visual_calls: int = 0
    _cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.crops_dir = self.run_dir / "crops"
        self.renders_dir = self.run_dir / "renders"
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(self.image_path) as im:
            self.image_size = im.size

    @property
    def width(self) -> int:
        return int(self.image_size[0])

    @property
    def height(self) -> int:
        return int(self.image_size[1])

    def original(self) -> str:
        return self.image_path

    def note_visual_call(self, agent: str) -> None:
        self.visual_calls += 1

    def crop(
        self,
        box: list[float] | tuple[float, ...] | dict,
        *,
        purpose: str = "",
        padding: float = 0.03,
    ) -> CropRecord:
        roi = parse_roi(box, self.width, self.height)
        pad_x = int(round((roi.x1 - roi.x0) * padding))
        pad_y = int(round((roi.y1 - roi.y0) * padding))
        x0 = max(0, roi.x0 - pad_x)
        y0 = max(0, roi.y0 - pad_y)
        x1 = min(self.width, roi.x1 + pad_x)
        y1 = min(self.height, roi.y1 + pad_y)
        box_px = [x0, y0, x1, y1]
        key = hashlib.sha1(f"{box_px}-{purpose}".encode("utf-8")).hexdigest()[:10]
        if key in self._cache:
            return self.crops[self._cache[key]]

        with Image.open(self.image_path) as im:
            im = im.convert("RGB")
            crop = im.crop((x0, y0, x1, y1))
            # Upscale tiny crops so the model can actually read small glyphs.
            if max(crop.size) < 320:
                scale = 320 / max(1, max(crop.size))
                crop = crop.resize(
                    (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            path = self.crops_dir / f"crop_{len(self.crops) + 1:03d}_{key}.png"
            crop.save(path)

        region_id = f"region_{len(self.crops) + 1:03d}"
        record = CropRecord(
            region_id=region_id,
            path=str(path),
            box_px=box_px,
            box_norm=[
                round(x0 / self.width, 4),
                round(y0 / self.height, 4),
                round(x1 / self.width, 4),
                round(y1 / self.height, 4),
            ],
            purpose=purpose,
        )
        self.crops[region_id] = record
        self._cache[key] = region_id
        return record

    def register_render(self, version: int, png_path: str | Path) -> str:
        return str(Path(png_path))

    def resolve(self, region_id: str | None) -> str:
        if not region_id:
            return self.image_path
        record = self.crops.get(region_id)
        if record is None:
            return self.image_path
        return record.path

    def context_text(self) -> str:
        if not self.crops:
            return "REGIONS: none"
        lines = ["REGIONS (cropped, ready for sub-agents):"]
        for record in self.crops.values():
            lines.append(
                f"  {record.region_id}: box_px={record.box_px} "
                f"box_norm={record.box_norm} purpose={record.purpose[:60]}"
            )
        return "\n".join(lines)

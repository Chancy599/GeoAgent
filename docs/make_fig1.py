# Compose the triptych for Fig. 1 (case 32_q_fig1):
# (a) original raster figure, (b) end-to-end baseline render, (c) GeoConstruct render.
from PIL import Image, ImageDraw, ImageFont
import matplotlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = [
    (ROOT / "data/test/image/32_q_fig1.png", "(a) Original figure"),
    (ROOT / "outputs/baseline/haiku-5.5/image/32_q_fig1.png", "(b) End-to-end baseline"),
    (ROOT / "outputs/ours/image/32_q_fig1.png", "(c) GeoConstruct (ours)"),
]
OUT = ROOT / "docs/fig1_case_32_q_fig1.png"

H = 600          # common panel height in pixels
GAP = 40         # horizontal gap between panels
LABEL_BAND = 70  # space below panels for subcaptions
FONT_SIZE = 30

def load_white(path: Path) -> Image.Image:
    im = Image.open(path)
    if im.mode in ("LA", "RGBA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    w, h = im.size
    return im.resize((round(w * H / h), H), Image.LANCZOS)

panels = [load_white(p) for p, _ in SRC]

font_path = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
font = ImageFont.truetype(str(font_path), FONT_SIZE)

width = sum(im.width for im in panels) + GAP * (len(panels) - 1)
canvas = Image.new("RGB", (width, H + LABEL_BAND), (255, 255, 255))
draw = ImageDraw.Draw(canvas)

x = 0
for im, (_, label) in zip(panels, SRC):
    canvas.paste(im, (x, 0))
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x + (im.width - tw) / 2, H + (LABEL_BAND - FONT_SIZE) / 2 - 6),
              label, fill=(0, 0, 0), font=font)
    x += im.width + GAP

canvas.save(OUT, dpi=(300, 300))
print("saved", OUT, canvas.size)

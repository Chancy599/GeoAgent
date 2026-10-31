"""Build presentation-ready per-stage assets for selected GeoAgent cases.

Run from the repo root:  python outputs/case_studies/build.py
All outputs land in outputs/case_studies/<stem>/.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geoagent.cv_tools.circle_detection import detect_circles
from geoagent.cv_tools.label_detection import bind_point_labels
from geoagent.cv_tools.line_detection import analyze_line_style, detect_lines
from geoagent.cv_tools.right_angle import detect_right_angle_marker
from geoagent.tools.compiler import compile_tikz
from geoagent.tools.renderer import frame_like_original, render_pdf

ROOT = Path.cwd()
OUT = ROOT / "outputs" / "case_studies"
ARCH = ROOT / "outputs" / "ours100" / "stem"
DATA = ROOT / "data" / "test"

FONT_PATH = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD_PATH = Path("C:/Windows/Fonts/arialbd.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold and FONT_BOLD_PATH.exists() else FONT_PATH
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def load_state(stem: str) -> dict:
    return json.loads((ARCH / stem / "state.json").read_text(encoding="utf-8"))


def load_result(stem: str) -> dict:
    return json.loads((ARCH / stem / "result.json").read_text(encoding="utf-8"))


def metrics_by_stem() -> dict[str, dict]:
    path = ROOT / "outputs" / "metrics" / "ours100.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["stem"]: row for row in data.get("per_image", [])}


def annotate(image: Image.Image, lines: list[str], *, color=(20, 20, 20)) -> Image.Image:
    """Add a small caption box at the top-left (used for zero-result stages)."""
    im = image.convert("RGB").copy()
    draw = ImageDraw.Draw(im)
    f = font(20, bold=True)
    pad = 10
    heights = [draw.textbbox((0, 0), t, font=f)[3] for t in lines]
    box_h = sum(heights) + pad * 2 + 4 * (len(lines) - 1)
    draw.rectangle([8, 8, 8 + 420, 8 + box_h], fill=(255, 255, 255), outline=(180, 180, 180))
    y = 8 + pad
    for t, h in zip(lines, heights):
        draw.text((16, y), t, font=f, fill=color)
        y += h + 4
    return im


def cv_stage(stem: str, stage_dir: Path, spec: dict) -> dict:
    name = spec["name"]
    params = spec.get("params") or {}
    tool = spec["tool"]
    funcs = {
        "detect_lines": detect_lines,
        "detect_circles": detect_circles,
        "detect_right_angle_marker": detect_right_angle_marker,
        "bind_point_labels": bind_point_labels,
        "analyze_line_style": analyze_line_style,
    }
    res = funcs[tool](str(DATA / "image" / f"{stem}.png"), visualize=True, out_dir=stage_dir, **params)
    viz = res.get("visualization")
    out_png = stage_dir / f"{name}.png"
    if viz and Path(viz).exists():
        shutil.copyfile(viz, out_png)
    else:
        base = Image.open(DATA / "image" / f"{stem}.png")
        out_png_img = annotate(base, [spec.get("caption", name), "0 results in this run"])
        out_png_img.save(out_png)
    count = (res.get("results") or {}).get("count")
    return {
        "name": name,
        "tool": tool,
        "params": params,
        "count": count,
        "image": out_png.name,
        "caption": spec.get("caption", name),
        "result": res,
    }


def compile_versions(stem: str, case_dir: Path, state: dict, original: Path) -> list[dict]:
    versions = []
    for v in state.get("tikz_versions") or []:
        n = int(v["version"])
        tex = v.get("tex") or ""
        if not tex:
            continue
        vdir = case_dir / "tikz" / f"v{n}"
        comp = compile_tikz(tex, out_dir=vdir, stem=f"v{n}")
        png = None
        framed = None
        if comp.get("ok") and comp.get("pdf_path"):
            png_path = vdir / f"v{n}.png"
            rendered = render_pdf(comp["pdf_path"], png_path, dpi=200)
            if rendered.get("ok"):
                framed = frame_like_original(png_path, original)
                png = png_path
        target = case_dir / f"v{n}.png"
        if png and Path(png).exists():
            shutil.copyfile(png, target)
        versions.append(
            {
                "version": n,
                "mode": v.get("mode"),
                "tex_path": str(Path(vdir) / f"v{n}.tex"),
                "image": target.name if target.exists() else None,
                "compiled": bool(comp.get("ok")),
                "compile_errors": comp.get("errors") or [],
                "framed": framed,
                "notes": v.get("notes"),
            }
        )
    return versions


def side_by_side(original: Path, render: Path, out_path: Path, left_label: str, right_label: str) -> None:
    a = Image.open(original).convert("RGB")
    b = Image.open(render).convert("RGB")
    if b.size != a.size:
        b = ImageOps.pad(b, a.size, color="white")
    margin, header = 24, 54
    w, h = a.size
    canvas = Image.new("RGB", (w * 2 + margin * 3, h + header + margin * 2), "white")
    canvas.paste(a, (margin, header + margin))
    canvas.paste(b, (margin * 2 + w, header + margin))
    draw = ImageDraw.Draw(canvas)
    f = font(26, bold=True)
    draw.text((margin, 16), left_label, font=f, fill=(20, 20, 20))
    draw.text((margin * 2 + w, 16), right_label, font=f, fill=(20, 20, 20))
    draw.line([(margin, header), (w * 2 + margin * 2, header)], fill=(210, 210, 210), width=2)
    canvas.save(out_path)


def canonical_segment(obj: dict) -> tuple[tuple[float, float], tuple[float, float]] | None:
    coords = obj.get("coords") or {}
    a, b = coords.get("a_px"), coords.get("b_px")
    if not (isinstance(a, list) and isinstance(b, list) and len(a) == 2 and len(b) == 2):
        return None
    a = (round(float(a[0]), 1), round(float(a[1]), 1))
    b = (round(float(b[0]), 1), round(float(b[1]), 1))
    return tuple(sorted([a, b]))  # type: ignore[return-value]


def draw_ges_overlay(stem: str, state: dict, case_dir: Path) -> Path:
    src = Image.open(DATA / "image" / f"{stem}.png").convert("RGBA")
    overlay = Image.new("RGBA", src.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    objects = state.get("objects") or {}
    bindings = state.get("label_bindings") or {}
    arc_notes: list[str] = []

    seen_segments = set()
    for obj in objects.values():
        typ = obj.get("type")
        status = obj.get("status", "candidate")
        if typ == "segment":
            key = canonical_segment(obj)
            if not key or key in seen_segments:
                continue
            seen_segments.add(key)
            a, b = key
            if math.dist(a, b) < 12:
                continue
            dashed = (obj.get("style") or {}).get("line") == "dashed"
            if dashed:
                color = (230, 140, 0, 190 if status == "confirmed" else 120)
                # manually dashed line
                length = math.dist(a, b)
                n = max(1, int(length / 8))
                for i in range(n):
                    if i % 2:
                        continue
                    p0 = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                    p1 = (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)
                    draw.line([p0, p1], fill=color, width=3)
            else:
                color = (30, 90, 200, 190 if status == "confirmed" else 130)
                draw.line([a, b], fill=color, width=3)
        elif typ in ("arc", "circle"):
            coords = obj.get("coords") or {}
            center = coords.get("center_px")
            radius = coords.get("radius_px")
            if not center or not radius:
                continue
            ranges = coords.get("visible_ranges_deg") or [[0, 360]]
            color = (200, 30, 30, 210 if status == "confirmed" else 150)
            for lo, hi in ranges:
                pts = []
                steps = max(2, int((hi - lo) / 2))
                for i in range(steps + 1):
                    ang = math.radians(lo + (hi - lo) * i / steps)
                    pts.append((center[0] + radius * math.cos(ang), center[1] + radius * math.sin(ang)))
                if len(pts) > 1:
                    draw.line(pts, fill=color, width=3)
            cx, cy = center
            draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=color, width=2)
            coverage = (obj.get("attributes") or {}).get("ink_coverage")
            if coverage is not None and float(coverage) < 0.6:
                arc_notes.append(
                    f"{obj.get('id')}: CV candidate, ink coverage {float(coverage):.2f} (low-confidence arc)"
                )
        elif typ == "right_angle":
            pts = (obj.get("coords") or {}).get("mark_points_px")
            if pts and len(pts) >= 3:
                draw.line([tuple(p) for p in pts], fill=(160, 30, 160, 220), width=3)
        elif typ == "point":
            px = (obj.get("coords") or {}).get("px")
            if not px:
                continue
            labeled = obj.get("id") in bindings.values()
            r = 4 if labeled else 2
            fill = (20, 140, 70, 230) if labeled else (120, 120, 120, 110)
            draw.ellipse([px[0] - r, px[1] - r, px[0] + r, px[1] + r], fill=fill)

    composed = Image.alpha_composite(src, overlay).convert("RGB")

    legend = [
        ("segment (solid)", (30, 90, 200)),
        ("segment (dashed)", (230, 140, 0)),
        ("arc / circle", (200, 30, 30)),
        ("right angle", (160, 30, 160)),
        ("bound point", (20, 140, 70)),
    ]
    width, height = composed.size
    cols = 2 if width < 520 else (3 if width < 760 else 5)
    rows = math.ceil(len(legend) / cols)
    strip_h = 12 + rows * 20 + len(arc_notes) * 20
    canvas = Image.new("RGB", (width, height + strip_h), "white")
    canvas.paste(composed, (0, 0))
    draw2 = ImageDraw.Draw(canvas)
    draw2.line([(0, height), (width, height)], fill=(210, 210, 210), width=1)
    slot_w = (width - 16) // cols
    for idx, (text, color) in enumerate(legend):
        r, c = divmod(idx, cols)
        x = 8 + c * slot_w
        y = height + 6 + r * 20
        draw2.line([(x, y + 8), (x + 26, y + 8)], fill=color, width=4)
        draw2.text((x + 32, y - 1), text, font=font(14), fill=(30, 30, 30))
    note_y = height + 6 + rows * 20
    for note in arc_notes:
        draw2.text((8, note_y), note, font=font(13, True), fill=(190, 30, 30))
        note_y += 20
    path = case_dir / "ges.png"
    canvas.save(path)
    return path


def storyboard(case_dir: Path, title: str, cells: list[tuple[Path, str, str]]) -> Path:
    cols = 4
    rows = math.ceil(len(cells) / cols)
    cw, ch = 580, 500
    margin, title_h = 30, 70
    canvas = Image.new("RGB", (cols * cw + margin * 2, rows * ch + title_h + margin), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 20), title, font=font(34, bold=True), fill=(20, 20, 20))
    for idx, (path, caption, sub) in enumerate(cells):
        r, c = divmod(idx, cols)
        x0 = margin + c * cw
        y0 = title_h + r * ch
        draw.rectangle([x0 + 8, y0 + 8, x0 + cw - 8, y0 + ch - 8], outline=(210, 210, 210), width=2)
        if path.exists():
            im = Image.open(path).convert("RGB")
            im.thumbnail((cw - 40, ch - 100), Image.Resampling.LANCZOS)
            canvas.paste(im, (x0 + (cw - im.width) // 2, y0 + 20 + (ch - 100 - im.height) // 2))
        draw.text((x0 + 24, y0 + ch - 72), caption, font=font(20, bold=True), fill=(20, 20, 20))
        draw.text((x0 + 24, y0 + ch - 44), sub, font=font(17), fill=(90, 90, 90))
    path = OUT / f"storyboard_{case_dir.name}.png"
    canvas.save(path)
    return path


CASES = [
    {
        "stem": "6984_q_fig1",
        "title": "6984_q_fig1 | circle + diameter + chords | critic style repair",
        "stages": [
            {"name": "lines", "tool": "detect_lines", "params": {"roi": [0, 0, 1, 1]}, "caption": "Line detection (4 segments)"},
            {"name": "circles", "tool": "detect_circles", "params": {"roi": [0, 0, 1, 1]}, "caption": "Circle detection (1 full circle)"},
            {"name": "right_angle", "tool": "detect_right_angle_marker", "params": {"roi": [0, 0, 1, 1]}, "caption": "Right-angle mark at F (1 verified)"},
            {"name": "labels", "tool": "bind_point_labels", "params": {}, "caption": "Label binding (8/8 letters)"},
        ],
    },
    {
        "stem": "403_q_fig1",
        "title": "403_q_fig1 | critic removes a spurious CV arc (0.45 -> 0.88 -> 0.90)",
        "stages": [
            {"name": "lines", "tool": "detect_lines", "params": {}, "caption": "Line detection (8 raw segments)"},
            {"name": "circles", "tool": "detect_circles", "params": {}, "caption": "Circle detection: 1 FALSE POSITIVE arc"},
            {"name": "right_angle", "tool": "detect_right_angle_marker", "params": {}, "caption": "Right-angle mark at A (1 verified)"},
            {"name": "labels", "tool": "bind_point_labels", "params": {}, "caption": "Label binding (A-E)"},
        ],
    },
    {
        "stem": "1260_q_fig2",
        "title": "1260_q_fig2 | critic restores the missing F->G dashed line (0.85 -> 0.93)",
        "stages": [
            {"name": "lines", "tool": "detect_lines", "params": {}, "caption": "Line detection (8 segments)"},
            {"name": "labels", "tool": "bind_point_labels", "params": {}, "caption": "Label binding (G left unbound)"},
            {"name": "right_angle", "tool": "detect_right_angle_marker", "params": {"roi": [0, 0, 1, 1]}, "caption": "Right-angle check (0 marks)"},
            {
                "name": "line_style",
                "tool": "analyze_line_style",
                "params": {
                    "segments": [
                        {"a": [68.5, 59.6], "b": [68.5, 257.4]},
                        {"a": [66.6, 254], "b": [200.4, 254]},
                        {"a": [148, 254], "b": [643, 254]},
                    ]
                },
                "caption": "Dashed/solid classification",
            },
        ],
    },
]


def write_case_markdown(stem: str, case_dir: Path, state: dict, result: dict, metrics: dict | None, stages: list[dict], versions: list[dict], overlay: Path) -> str:
    critics = state.get("critic_reports") or []
    score_by_version = {}
    for i, r in enumerate(critics, start=1):
        score_by_version[i] = r.get("assessment_score")

    lines = []
    lines.append(f"# {stem} 处理流程\n")
    lines.append("## 概览\n")
    lines.append(f"- 图：`data/test/image/{stem}.png`（{state['image_size']['width']}×{state['image_size']['height']}）")
    lines.append(f"- 最终版本：v{result.get('best_version')}，critic 分数 {result.get('best_score')}")
    if metrics:
        lines.append(
            f"- 整图指标：SSIM {metrics['ssim']*100:.2f} / CLIP {metrics['clip']*100:.2f} / DINO {metrics['dino']*100:.2f}"
        )
    lines.append(f"- 统计：{result.get('counts')}")
    lines.append("")
    lines.append("## 阶段图片\n")
    lines.append("| 文件 | 阶段 | 说明 | 工具结果 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| `00_input.png` | 输入 | 原始题图 | — |")
    for st in stages:
        lines.append(f"| `{st['image']}` | {st['name']} | {st['caption']} | count={st['count']} |")
    lines.append(f"| `ges.png` | GES | 几何证据状态叠加图 | {len(state.get('objects') or {})} objects / {len(state.get('relations') or {})} relations |")
    for v in versions:
        score = score_by_version.get(v["version"])
        lines.append(f"| `{v['image']}` | v{v['version']} | {v['mode']} | critic={score} |")
    lines.append("| `final.png` | 最终 | 归档 best.png | — |")
    lines.append("")
    lines.append("## 动作序列\n")
    lines.append("| step | action | purpose | status | result |")
    lines.append("| ---: | --- | --- | --- | --- |")
    for ev in state.get("action_history") or []:
        result = ev.get("result_summary") or ev.get("error") or ""
        lines.append(
            f"| {ev.get('step')} | {ev.get('action')} | {str(ev.get('purpose') or '')[:120]} | "
            f"{ev.get('status') or ''} | {str(result)[:90]} |"
        )
    lines.append("")
    lines.append("## Critic 轮次\n")
    for i, r in enumerate(critics, start=1):
        lines.append(f"### v{i} — score {r.get('assessment_score')}\n")
        lines.append(f"{r.get('verdict')}\n")
        issues = r.get("issues") or []
        if issues:
            lines.append("| type | severity | description |")
            lines.append("| --- | --- | --- |")
            for x in issues:
                lines.append(f"| {x.get('type')} | {x.get('severity')} | {str(x.get('description'))[:220]} |")
            lines.append("")
    lines.append("## 建议 PPT 页\n")
    lines.append("1. 标题页：原图 + 一句话说明本图的几何结构。")
    lines.append("2. 证据页：依次放 `s02` 线检测、`s03` 圆/弧检测（如有）、`s04` 直角、`s05` 标签。")
    lines.append("3. 状态页：`ges.png` + 右侧列 objects/relations 数量。")
    lines.append("4. 迭代页：v1 → … → final，并在每张下标注 critic 分数。")
    lines.append("5. 结论页：final 与 input 并排，写最终 SSIM/CLIP/DINO。")
    lines.append("")
    lines.append(f"总览图：`storyboard_{stem}.png`。")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metrics = metrics_by_stem()
    index_rows = []

    for case in CASES:
        stem = case["stem"]
        state = load_state(stem)
        result = load_result(stem)
        case_dir = OUT / stem
        stage_dir = case_dir / "cv"
        stage_dir.mkdir(parents=True, exist_ok=True)
        original = DATA / "image" / f"{stem}.png"
        shutil.copyfile(original, case_dir / "00_input.png")

        stages = []
        for spec in case["stages"]:
            st = cv_stage(stem, stage_dir, spec)
            # numbered alias for stable ordering
            staged_name = f"s{len(stages)+2:02d}_{spec['name']}.png"
            shutil.copyfile(stage_dir / f"{spec['name']}.png", case_dir / staged_name)
            st["image"] = staged_name
            stages.append(st)

        versions = compile_versions(stem, case_dir, state, original)
        critics = state.get("critic_reports") or []
        for v in versions:
            n = v["version"]
            score = critics[n - 1].get("assessment_score") if n - 1 < len(critics) else None
            v["score"] = score
            if v["image"]:
                side_by_side(
                    original,
                    case_dir / v["image"],
                    case_dir / f"compare_v{n}.png",
                    "Original",
                    f"v{n} | critic {score}",
                )
                v["compare_image"] = f"compare_v{n}.png"

        shutil.copyfile(ARCH / stem / "best.png", case_dir / "final.png")
        best_n = int(result.get("best_version") or len(versions))
        best_score = result.get("best_score")
        if (case_dir / f"v{best_n}.png").exists():
            side_by_side(
                original,
                case_dir / f"v{best_n}.png",
                case_dir / "compare_final.png",
                "Original",
                f"final (v{best_n}) | critic {best_score}",
            )

        overlay = draw_ges_overlay(stem, state, case_dir)

        payload = {
            "schema": "geoagent.case-study.v1",
            "stem": stem,
            "title": case["title"],
            "input": str(Path("data/test/image") / f"{stem}.png"),
            "reference_latex": str(Path("data/test/latex") / f"{stem}.tex"),
            "best_version": best_n,
            "best_score": best_score,
            "metrics": metrics.get(stem),
            "counts": result.get("counts"),
            "stages": [
                {
                    "name": st["name"],
                    "tool": st["tool"],
                    "params": st["params"],
                    "count": st["count"],
                    "image": st["image"],
                    "caption": st["caption"],
                }
                for st in stages
            ],
            "versions": [
                {
                    "version": v["version"],
                    "mode": v["mode"],
                    "score": v["score"],
                    "image": v["image"],
                    "compare_image": v.get("compare_image"),
                    "tex_path": v["tex_path"],
                    "compiled": v["compiled"],
                    "notes": v["notes"],
                }
                for v in versions
            ],
            "actions": state.get("action_history") or [],
            "critics": critics,
            "objects": list((state.get("objects") or {}).values()),
            "relations": list((state.get("relations") or {}).values()),
            "conflicts": state.get("conflicts"),
            "unresolved": state.get("unresolved_issues"),
        }
        (case_dir / "case.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        timeline = write_case_markdown(stem, case_dir, state, result, metrics.get(stem), stages, versions, overlay)
        (case_dir / "timeline.md").write_text(timeline, encoding="utf-8")

        cells: list[tuple[Path, str, str]] = [(case_dir / "00_input.png", "Input", f"{state['image_size']['width']}x{state['image_size']['height']}")]
        for st in stages:
            cells.append((case_dir / st["image"], st["name"], st["caption"]))
        for v in versions:
            cells.append(
                (
                    case_dir / v["image"],
                    f"v{v['version']}",
                    f"critic {v['score']}" + (" (final)" if v["version"] == best_n else ""),
                )
            )
        if not any(v["version"] == best_n for v in versions):
            cells.append((case_dir / "final.png", f"v{best_n}", f"critic {best_score} (final)"))
        storyboard(case_dir, case["title"], cells)

        index_rows.append(
            {
                "stem": stem,
                "title": case["title"],
                "best_version": best_n,
                "best_score": best_score,
                "metrics": metrics.get(stem),
                "versions": len(versions),
                "critic_rounds": len(critics),
            }
        )

    lines = ["# GeoAgent 案例素材（PPT 用）\n"]
    lines.append("每个案例一个目录，包含输入、CV 阶段图、GES 叠加图、每个 TikZ 版本、并排对比图、时间线与 `case.json`。\n")
    lines.append("## 案例一览\n")
    lines.append("| 案例 | 版本数 | best | SSIM | CLIP | DINO | 用途 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in index_rows:
        m = row["metrics"] or {}
        lines.append(
            f"| {row['stem']} | {row['versions']} | {row['best_score']} | "
            f"{m.get('ssim', 0)*100:.2f} | {m.get('clip', 0)*100:.2f} | {m.get('dino', 0)*100:.2f} | {row['title'].split('|')[-1].strip()} |"
        )
    lines.append("")
    lines.append("## 建议讲法\n")
    lines.append("1. **主流程页**：用 `6984_q_fig1`。输入 → 线/圆/直角/标签 → GES → v1/v2/v3，critic 从 0.90 到 0.95。")
    lines.append("2. **Critic 实质作用页**：用 `403_q_fig1`。展示 v1（多出的假弧、CD 未到 D，0.45）→ v2（删弧补线，0.88）→ v5（0.90）。")
    lines.append("3. **缺失元素修复页**：用 `1260_q_fig2`。v1 漏掉 F→G 虚线和 G 标签（0.85）→ v2 补上（0.93）。")
    lines.append("")
    lines.append("## 注意事项\n")
    lines.append("- 中间版本由 `state.json.tikz_versions[].tex` 重新编译，并做了与原图一致的取景（`frame_like_original`）；重编译的 best 与归档 `best.png` 逐像素一致。")
    lines.append("- `403_q_fig1` 的圆检测阶段图是**假阳性**，正好用于说明 CV 会犯错、Critic 负责纠错。")
    lines.append("- 原始 `s05_labels.png` 是 CV 工具的调试叠加图（含 point/label id），信息较密；如果幻灯片上显得杂乱，可用同目录的 `ges.png` 代替。")
    lines.append("- 指标来自 `outputs/metrics/ours100.json`，均为整图指标（×100 展示）。")
    lines.append("- 生成脚本：`outputs/case_studies/build.py`。")
    (OUT / "index.md").write_text("\n".join(lines), encoding="utf-8")
    print("built:", OUT)
    for row in index_rows:
        print(row["stem"], "versions", row["versions"], "best", row["best_score"])


if __name__ == "__main__":
    main()

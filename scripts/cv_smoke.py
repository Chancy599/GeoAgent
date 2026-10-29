"""Quick CV smoke test on one image: circles, lines, right angles, labels."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent.cv_tools.circle_detection import detect_circles
from geoagent.cv_tools.label_detection import (
    bind_point_labels,
    extract_label_candidates,
    match_label_templates,
)
from geoagent.cv_tools.line_detection import detect_lines
from geoagent.cv_tools.right_angle import detect_right_angle_marker

OUT = ROOT / "outputs" / "cv_smoke"
OUT.mkdir(parents=True, exist_ok=True)


def main(image: str) -> None:
    path = ROOT / image
    print("IMAGE:", path)

    circles = detect_circles(image_path=str(path), out_dir=str(OUT))
    print("\n== CIRCLES ==", circles.get("ok"), "|", circles.get("results", {}).get("count"))
    for c in circles.get("results", {}).get("circles", []):
        print(
            f"  center={c.get('center_px')} r={c.get('radius_px')} "
            f"span={c.get('visible_span_deg')} cov={c.get('ink_coverage')} "
            f"full={c.get('full_circle')} method={c.get('method')}"
        )

    lines = detect_lines(image_path=str(path), out_dir=str(OUT))
    segs = lines.get("results", {}).get("segments", [])
    print("\n== LINES ==", lines.get("ok"), "count=", len(segs))
    for s in sorted(segs, key=lambda d: -d["length_px"])[:15]:
        p = s["a_px"] + s["b_px"]
        print(
            f"  len={s['length_px']:.1f} ang={s['angle_deg']:.1f} "
            f"style={s['style']} ({s.get('detection_kind')}) "
            f"[{p[0]:.0f},{p[1]:.0f}]->[{p[2]:.0f},{p[3]:.0f}]"
        )

    ra = detect_right_angle_marker(image_path=str(path), out_dir=str(OUT))
    print("\n== RIGHT ANGLES ==", json.dumps(ra.get("results", {}), ensure_ascii=False)[:600])

    cands = extract_label_candidates(image_path=str(path), out_dir=str(OUT))
    cand_list = cands.get("results", {}).get("labels", [])
    print("\n== LABEL CANDIDATES ==", len(cand_list))
    matched = match_label_templates(str(path), cand_list, out_dir=str(OUT))
    matches = matched.get("results", {}).get("matches", [])
    print("== MATCHED ==", len(matches))
    for m in matches:
        print(
            f"  id={m.get('id')} chosen={m.get('chosen')} "
            f"ncc={m.get('ncc')} bbox={m.get('box_px')} amb={m.get('ambiguous')}"
        )
    bound = bind_point_labels(str(path), labels=matches, out_dir=str(OUT))
    print("== BINDINGS ==", json.dumps(bound.get("results", {}), ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/test/image/1035_q_fig1.png")

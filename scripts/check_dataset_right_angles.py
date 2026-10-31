"""Fresh local-CV measurement on dataset images, without LLM calls."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geoagent.cv_tools.line_detection import detect_lines
from geoagent.cv_tools.right_angle import detect_right_angle_marker
from geoagent.orchestration.ingest import ingest_cv_result
from geoagent.state.rectify import rectify_right_angles
from geoagent.state.schemas import GeometricEvidenceState

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "right_angle_dataset_check"


def angle(state, ids):
    vectors = []
    for oid in ids:
        c = state.objects[oid].coords
        vectors.append(np.subtract(c["b_px"], c["a_px"]))
    a, b = vectors
    cosine = abs(float(a @ b)) / float(np.linalg.norm(a) * np.linalg.norm(b))
    return math.degrees(math.acos(float(np.clip(cosine, 0, 1))))


def check(image):
    with Image.open(image) as im:
        width, height = im.size
    state = GeometricEvidenceState(image_path=str(image), image_size={"width": width, "height": height})
    lines = detect_lines(image, visualize=False)
    ingest_cv_result(state, "detect_lines", {}, lines)
    marks = detect_right_angle_marker(image, visualize=False)
    ingest_cv_result(state, "detect_right_angle_marker", {}, marks)
    before = state.model_copy(deep=True)
    report = rectify_right_angles(state)
    rows = []
    for item in report["right_angles"]:
        if "segments" not in item:
            continue
        initial = angle(before, item["segments"])
        final = angle(state, item["segments"])
        rows.append({"image": image.name, "marker": item["object_id"],
                     "topology": "+".join(item["kinds"]),
                     "before_deg": initial, "after_deg": final,
                     "before_error_deg": 90-initial, "after_error_deg": 90-final,
                     "max_shift_px": item["max_shift_px"], "applied": report["applied"],
                     "segments": item["segments"]})
    if report["right_angles"]:
        dest = OUT / image.stem
        dest.mkdir(parents=True, exist_ok=True)
        before.save(dest / "before.json")
        state.save(dest / "after.json")
    return {"image": image.name, "markers": len(marks.get("results", {}).get("markers", [])),
            "reason": report["reason"], "ok": report["ok"], "rows": rows,
            "rejected": report["rejected"]}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    images = sorted((ROOT / "data/test/image").glob("*.png"))
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(check, image): image for image in images}
        for future in as_completed(futures):
            image = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"image": image.name, "error": repr(exc), "rows": []})
            if len(results) % 10 == 0:
                print(f"processed {len(results)}/{len(images)}", flush=True)
    results.sort(key=lambda r: r["image"])
    rows = [row for result in results for row in result["rows"]]
    summary = {"images_tested": len(images), "images_with_markers": sum(r.get("markers", 0)>0 for r in results),
               "angles_measured": len(rows), "applied_angles": sum(r["applied"] for r in rows),
               "errors": [r for r in results if "error" in r],
               "max_before_error_deg": max((r["before_error_deg"] for r in rows), default=0),
               "max_after_error_deg": max((r["after_error_deg"] for r in rows), default=0)}
    (OUT / "report.json").write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        with (OUT / "angles.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(json.dumps(sorted(rows, key=lambda r: -r["before_error_deg"])[:10], ensure_ascii=False), flush=True)

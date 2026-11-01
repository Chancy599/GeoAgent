from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import main
from main import build_parser


class _Item:
    def __init__(self, stem: str):
        self.stem = stem
        self.image_path = Path(f"{stem}.png")


def _fake_result(stem: str, status: str = "success") -> dict:
    return {
        "status": status,
        "best_version": None,
        "best_score": 0.9,
        "usage": {"totals": {"total_tokens": 1}},
        "elapsed_s": int(stem[1:]),
    }


def _args(tmp_path: Path, *extra: str):
    return build_parser().parse_args(
        [
            "batch",
            "--limit",
            "4",
            "--out-dir",
            str(tmp_path / "runs"),
            "--archive-dir",
            str(tmp_path / "archive"),
            "--report",
            str(tmp_path / "report.json"),
            *extra,
        ]
    )


def test_batch_workers_keep_dataset_order(tmp_path, monkeypatch) -> None:
    items = [_Item(f"s{i}") for i in range(4)]
    seen: list[str] = []

    class FakeRunner:
        def __init__(self, image_path, settings, run_dir, on_event):
            self.stem = Path(image_path).stem

        def run(self):
            seen.append(self.stem)
            return _fake_result(self.stem)

    monkeypatch.setattr(main, "load_settings", lambda: SimpleNamespace(paths=SimpleNamespace(image_dir="x", latex_dir="y")))
    monkeypatch.setattr(main, "scan_dataset", lambda *args, **kwargs: items)
    monkeypatch.setattr(main, "_settings", lambda args: None)
    monkeypatch.setattr(main, "GeoAgentRunner", FakeRunner)

    assert main.cmd_batch(_args(tmp_path, "--workers", "3")) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert sorted(seen) == [item.stem for item in items]
    assert [row["elapsed_s"] for row in report] == [0, 1, 2, 3]


def test_batch_skip_existing_reuses_archived_results(tmp_path, monkeypatch) -> None:
    items = [_Item(f"s{i}") for i in range(4)]
    archived = tmp_path / "archive" / "stem" / "s0" / "result.json"
    archived.parent.mkdir(parents=True)
    archived.write_text(json.dumps({"status": "archived"}), encoding="utf-8")
    seen: list[str] = []

    class FakeRunner:
        def __init__(self, image_path, settings, run_dir, on_event):
            self.stem = Path(image_path).stem

        def run(self):
            seen.append(self.stem)
            return _fake_result(self.stem)

    monkeypatch.setattr(main, "load_settings", lambda: SimpleNamespace(paths=SimpleNamespace(image_dir="x", latex_dir="y")))
    monkeypatch.setattr(main, "scan_dataset", lambda *args, **kwargs: items)
    monkeypatch.setattr(main, "_settings", lambda args: None)
    monkeypatch.setattr(main, "GeoAgentRunner", FakeRunner)

    assert main.cmd_batch(_args(tmp_path, "--workers", "2", "--skip-existing")) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert seen == ["s1", "s2", "s3"]
    assert [row["status"] for row in report] == ["archived", "success", "success", "success"]


def test_batch_isolates_worker_errors(tmp_path, monkeypatch) -> None:
    items = [_Item("s0"), _Item("s1")]

    class FakeRunner:
        def __init__(self, image_path, settings, run_dir, on_event):
            self.stem = Path(image_path).stem

        def run(self):
            if self.stem == "s1":
                raise RuntimeError("boom")
            return _fake_result(self.stem)

    monkeypatch.setattr(main, "load_settings", lambda: SimpleNamespace(paths=SimpleNamespace(image_dir="x", latex_dir="y")))
    monkeypatch.setattr(main, "scan_dataset", lambda *args, **kwargs: items)
    monkeypatch.setattr(main, "_settings", lambda args: None)
    monkeypatch.setattr(main, "GeoAgentRunner", FakeRunner)

    assert main.cmd_batch(_args(tmp_path, "--workers", "2")) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["status"] for row in report] == ["success", "error"]
    assert "RuntimeError" in report[1]["error"]

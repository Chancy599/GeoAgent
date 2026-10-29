from __future__ import annotations

from geoagent.datasets import find_item, load_reference


def test_dataset_pairs_images_with_references(bench_items) -> None:
    assert len(bench_items) >= 100
    assert all(item.image_path.exists() for item in bench_items)
    paired = [item for item in bench_items if item.latex_path is not None]
    assert len(paired) >= 100
    assert len({item.stem for item in bench_items}) == len(bench_items)


def test_public_payload_hides_reference_by_default(bench_items) -> None:
    item = find_item("1035_q_fig1", bench_items)
    assert item is not None
    assert item.width and item.height
    public = item.public()
    assert "reference_tex" not in public
    assert public["has_reference"] is True


def test_reference_is_only_loaded_offline(bench_items) -> None:
    tex = load_reference("1035_q_fig1", bench_items)
    assert tex is not None
    assert "tikzpicture" in tex

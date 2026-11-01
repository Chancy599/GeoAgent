"""Check metric weighting and missing-item handling independently of real scores."""
from copy import deepcopy

import pytest

from scripts.merge_evaluation_results import build_ablation


def example():
    result = {'shared_stems': ['small', 'large'], 'groups': {}}
    for name, errors in [('raw', [[9.], [1., 1., None]]), ('post', [[3.], [0., 2., 0.]])]:
        rows = {}
        for stem, values in zip(result['shared_stems'], errors):
            checks = [{'labels': [str(i)], 'target': float(i), 'error': v} for i, v in enumerate(values)]
            rows[stem] = {'compiled': True, 'angle_checks': checks, 'ratio_checks': deepcopy(checks)}
        result['groups'][name] = {'per_stem': rows}
    return result


def test_pooling_weights_items_and_keeps_worsened_items():
    result, _ = build_ablation(example())
    for metric in ('angle', 'ratio'):
        stats = result['metrics'][metric]
        assert stats['n_items'] == 3  # Missing raw item excluded from both sides.
        assert stats['n_images'] == 2
        assert stats['groups']['raw']['mean'] == pytest.approx(11/3)
        assert stats['groups']['post']['mean'] == pytest.approx(5/3)
        assert stats['groups']['post']['median'] == 2
        assert (stats['improved'], stats['worsened'], stats['unchanged']) == (2, 1, 0)
        assert stats['relative_reduction']['mean'] == pytest.approx(6/11)


def test_pairing_rejects_different_labels_even_with_same_target():
    structure = example()
    structure['groups']['post']['per_stem']['small']['angle_checks'][0]['labels'] = ['other']
    with pytest.raises(AssertionError, match='Item identity mismatch'):
        build_ablation(structure)

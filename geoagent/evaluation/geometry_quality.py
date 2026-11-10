"""Connectivity and shape metrics for the frozen reference cohort."""
from __future__ import annotations

import numpy as np

from .structure import reference_items


POINT_ERROR_CAP = 1.0
NONCOLLINEAR_TOLERANCE = 1e-6
QUALITY_POLICY = {
    'schema': 'edge-shape-v2',
    'f1': 'supported unordered labelled straight edges',
    'aggregation': 'equal weight per image',
    'point_alignment': 'least squares on common labels; translation, rotation and uniform scale; no reflection',
    'point_normalizer': 'maximum reference distance between labelled points',
    'point_missing_error': POINT_ERROR_CAP,
    'point_error_cap': POINT_ERROR_CAP,
    'point_min_second_singular_ratio': NONCOLLINEAR_TOLERANCE,
}


def _set_scores(reference, prediction):
    matched = len(reference & prediction)
    reference_count, prediction_count = len(reference), len(prediction)
    total = reference_count + prediction_count
    return {
        'precision': matched / prediction_count if prediction_count else float(not reference_count),
        'recall': matched / reference_count if reference_count else 1.,
        'f1': 2 * matched / total if total else 1.,
        'matched': matched,
        'reference': reference_count,
        'predicted': prediction_count,
    }


def _edges_by_label(names, edges):
    return {tuple(sorted((names[a], names[b]))) for a, b in edges}


def _noncollinear(points):
    if len(points) < 3:
        return False
    singular = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
    return bool(singular[1] > NONCOLLINEAR_TOLERANCE * singular[0])


def _point_error(reference, prediction, names):
    common = sorted(set(names) & prediction.keys())
    result = {'mean': None, 'matched': len(common), 'reference': len(names), 'aligned': False}
    if not _noncollinear(reference):
        return {**result, 'reason': 'reference_has_no_noncollinear_triple'}

    indices = {name: i for i, name in enumerate(names)}
    target = reference[[indices[name] for name in common]]
    source = np.asarray([prediction[name] for name in common])
    if not (_noncollinear(target) and _noncollinear(source)):
        return {**result, 'mean': POINT_ERROR_CAP, 'reason': 'insufficient_nondegenerate_matches'}

    # Multiplying by a complex number fits a rotation and a uniform scale.
    # Centering fits the translation without introducing a reflection.
    source = source[:, 0] + 1j * source[:, 1]
    target = target[:, 0] + 1j * target[:, 1]
    source -= source.mean()
    target -= target.mean()
    cross = np.vdot(source, target)
    if abs(cross) <= 1e-12 * np.linalg.norm(source) * np.linalg.norm(target):
        return {**result, 'mean': POINT_ERROR_CAP, 'reason': 'fit_would_collapse'}
    scale_rotation = cross / np.vdot(source, source).real
    diameter = np.linalg.norm(reference[:, None] - reference, axis=-1).max()
    residuals = np.abs(source * scale_rotation - target) / diameter
    errors = {name: float(min(error, POINT_ERROR_CAP)) for name, error in zip(common, residuals)}
    mean = sum(errors.get(name, POINT_ERROR_CAP) for name in names) / len(names)
    return {**result, 'mean': mean, 'aligned': True, 'errors': errors}


def score_geometry_quality(reference, reference_edges, prediction):
    names = reference.label_names
    predicted_names = prediction.label_names if prediction is not None else []
    predicted_edges = reference_items(prediction)['edges'] if prediction is not None else []
    coordinates = dict(zip(predicted_names, prediction.points)) if prediction is not None else {}
    return {
        'edges': _set_scores(_edges_by_label(names, reference_edges), _edges_by_label(predicted_names, predicted_edges)),
        'points': _point_error(reference.points, coordinates, names),
    }


def summarize_geometry_quality(rows):
    scores = [row['geometry_quality'] for row in rows.values()]
    points = [score['points']['mean'] for score in scores if score['points']['mean'] is not None]
    return {
        'n_images': len(scores),
        'point_images': len(points),
        'point_aligned_images': sum(score['points']['aligned'] for score in scores),
        'edge_precision': float(np.mean([score['edges']['precision'] for score in scores])),
        'edge_recall': float(np.mean([score['edges']['recall'] for score in scores])),
        'edge_f1': float(np.mean([score['edges']['f1'] for score in scores])),
        'point_error': float(np.mean(points)) if points else None,
    }

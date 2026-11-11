"""Verify the two arms of a drawn chain against the original raster."""
from collections import defaultdict
from itertools import combinations
import math

import cv2
import numpy as np

from ..cv_tools.common import load_ink


def _fit_arm(mask, start, end, radius):
    vector = end - start
    length = float(np.linalg.norm(vector))
    if length < 25:
        return None
    axis = vector / length
    normal = np.array([-axis[1], axis[0]])
    offsets = np.arange(-radius, radius + 1)
    along = np.linspace(.12, .88, min(120, round(length)))
    coords = start + along[None, :, None] * vector + offsets[:, None, None] * normal
    x, y = (c.astype(np.float32) for c in coords.transpose(2, 0, 1))
    strip = cv2.remap(mask, x, y, cv2.INTER_NEAREST)
    # Search for the axis covering the most longitudinal samples. This works
    # with disconnected dash runs and excludes the junction and the label ends.
    dilated = cv2.dilate(strip, np.ones((3, 1), np.uint8))
    left, right = np.meshgrid(offsets[::2], offsets[::2])
    profile = left.ravel()[:, None]*(1-along) + right.ravel()[:, None]*along
    rows = np.rint(profile + radius).astype(int)
    hit = dilated[rows, np.arange(len(along))]
    scores = hit.mean(axis=1) - .002 * np.mean(np.abs(profile), axis=1)
    best = int(scores.argmax())
    if hit[best].mean() < .35 or min(part.mean() for part in np.array_split(hit[best], 3)) < .20:
        return None

    samples = []
    for col, target in enumerate(profile[best]):
        ink = offsets[strip[:, col] != 0]
        runs = np.split(ink, np.flatnonzero(np.diff(ink) != 1) + 1)
        centers = [run.mean() for run in runs if 0 < len(run) <= 9]
        if centers:
            center = min(centers, key=lambda value: abs(value - target))
            if abs(center - target) <= 2.5:
                samples.append((along[col] * length, center))
    if len(samples) < .25 * len(along):
        return None
    positions, lateral = np.asarray(samples).T
    if np.ptp(positions) < .55*length:
        return None
    slope, intercept = np.polyfit(positions, lateral, 1)
    if np.median(np.abs(lateral - (slope * positions + intercept))) > 1.1:
        return None
    direction = axis + slope * normal
    return start + intercept * normal, direction / np.linalg.norm(direction)


def source_collinear_candidates(geometry, image_path, coordinates, max_turn_deg):
    if not image_path or not coordinates or max_turn_deg <= 0:
        return []
    origin = np.asarray(coordinates['origin_px'], dtype=float)
    scale = float(coordinates['scale'])
    pixels = {name: origin + np.array([xy[0], -xy[1]]) / scale for name, xy in geometry['points'].items()}
    neighbors = defaultdict(list)
    for key, (a, b) in geometry['segments'].items():
        neighbors[a].append((b, key))
        neighbors[b].append((a, key))
    triples = []
    for vertex, arms in neighbors.items():
        for (a, first), (b, second) in combinations(arms, 2):
            u, v = pixels[a]-pixels[vertex], pixels[b]-pixels[vertex]
            cross = u[0]*v[1]-u[1]*v[0]
            turn = math.degrees(math.atan2(abs(cross), -float(u@v)))
            if .07 < turn <= max_turn_deg:
                triples.append((a, vertex, b, first, second))
    if not triples:
        return []
    mask, _ = load_ink(image_path)
    radius = int(np.clip(.02*math.hypot(*mask.shape), 6, 18))
    fits = {}
    candidates = []
    for a, vertex, b, first, second in triples:
        for key in (first, second):
            if key not in fits:
                left, right = geometry['segments'][key]
                fits[key] = _fit_arm(mask, pixels[left], pixels[right], radius)
        if fits[first] is None or fits[second] is None:
            continue
        (p, u), (q, v) = fits[first], fits[second]
        angle = math.degrees(math.acos(float(np.clip(abs(u@v), 0., 1.))))
        if angle > .65:
            continue
        center = pixels[vertex]
        on_first = p + float((center-p)@u)*u
        on_second = q + float((center-q)@v)*v
        if np.linalg.norm(on_first-on_second) > 2.0:
            continue
        candidates.append({'type': 'collinear', 'segments': [first, second], 'labels': [a, vertex, b],
                           'source_turn_deg': round(angle, 4)})
    return candidates

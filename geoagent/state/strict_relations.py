"""Preservation checks on the compiler's integer coordinates."""
from itertools import combinations
from math import hypot, radians, tan

from .exact_layout import cross, vector


def dot(u, v):
    return sum(int(a) * int(b) for a, b in zip(u, v))


def protected_directions(points, edges):
    """Exact directions already present in the input, independent of candidate selection."""
    vectors = {name: vector(points, edge) for name, edge in edges.items()}
    for first, second in combinations(vectors, 2):
        u, v = vectors[first], vectors[second]
        if not any(u) or not any(v):
            continue
        if cross(u, v) == 0:
            yield {"type": "parallel", "segments": [first, second]}
        elif dot(u, v) == 0:
            yield {"type": "perpendicular", "segments": [first, second]}


def validate_relations(before, after, edges, targets, incidence_tol):
    """Preserve exact relations, near direction classes, incidences and proper crossings."""
    target_pairs = {tuple(sorted(relation["segments"])) for relation in targets}
    directions = {name: (vector(before, edge), vector(after, edge)) for name, edge in edges.items()}
    span = hypot(*(max(axis) - min(axis) for axis in zip(*before.values())))
    near_angle = tan(radians(.1))

    for a, b in combinations(before, 2):
        if (before[a] == before[b]) != (after[a] == after[b]):
            raise ValueError(f"point coincidence changed: {a}, {b}")

    def offset(points, edge, point):
        return cross(vector(points, edge), vector(points, (edge[0], point)))

    for name, edge in edges.items():
        u, v = directions[name]
        old_order, new_order = [], []
        for point in before.keys() - set(edge):
            old = offset(before, edge, point)
            new = offset(after, edge, point)
            if old == 0:
                if new != 0:
                    raise ValueError(f"existing collinearity lost: {point}, {name}")
                t = dot(vector(before, (edge[0], point)), u)
                new_t = dot(vector(after, (edge[0], point)), v)
                if (t <= 0, t >= dot(u, u)) != (new_t <= 0, new_t >= dot(v, v)):
                    raise ValueError(f"point order changed: {point}, {name}")
                old_order.append((t, point))
                new_order.append((new_t, point))
            elif 0 < dot(vector(before, (edge[0], point)), u) < dot(u, u):
                if abs(old) <= incidence_tol * span * hypot(*u) and abs(new) > incidence_tol * span * hypot(*v):
                    raise ValueError(f"existing incidence moved off segment: {point}, {name}")
            if all(2 * before[point][i] == before[edge[0]][i] + before[edge[1]][i] for i in range(2)):
                if any(2 * after[point][i] != after[edge[0]][i] + after[edge[1]][i] for i in range(2)):
                    raise ValueError(f"midpoint changed: {point}, {name}")
        if [p for _, p in sorted(old_order)] != [p for _, p in sorted(new_order)]:
            raise ValueError(f"collinear point order changed: {name}")

    for first, second in combinations(edges, 2):
        (u, v), (s, t) = directions[first], directions[second]
        old_cross, new_cross = cross(u, s), cross(v, t)
        old_dot, new_dot = dot(u, s), dot(v, t)
        if (old_cross == 0 and new_cross != 0) or (old_dot == 0 and new_dot != 0):
            raise ValueError(f"exact direction lost: {first}, {second}")
        if dot(u, u) == dot(s, s) and dot(v, v) != dot(t, t):
            raise ValueError(f"equal lengths lost: {first}, {second}")
        if tuple(sorted((first, second))) not in target_pairs:
            if ((abs(old_cross) <= near_angle * abs(old_dot) and abs(new_cross) > near_angle * abs(new_dot))
                    or (abs(old_dot) <= near_angle * abs(old_cross) and abs(new_dot) > near_angle * abs(new_cross))):
                raise ValueError(f"near direction lost: {first}, {second}")
        a, b = edges[first], edges[second]
        if set(a).intersection(b):
            continue
        if old_cross == 0 and offset(before, a, b[0]) != 0 and offset(after, a, b[0]) == 0:
            raise ValueError(f"distinct parallel lines merged: {first}, {second}")

        def crosses(points):
            return (offset(points, a, b[0]) * offset(points, a, b[1]) < 0
                    and offset(points, b, a[0]) * offset(points, b, a[1]) < 0)

        if crosses(before) != crosses(after):
            raise ValueError(f"proper crossing changed: {first}, {second}")

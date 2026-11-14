"""Rank the small SIA result table, without downloading exposure FITS files."""
import math
import numpy as np


def footprint_margin(row, ra, dec):
    """Signed angular margin in degrees for convex ICRS spherical polygons.

    Unsupported/missing footprints return None, never a false coverage verdict.
    WCS and finite pixel checks on the cutout remain authoritative.
    """
    try:
        tokens = str(row.get("s_region", "")).split()
        if tokens[:2] != ["POLYGON", "ICRS"]:
            return None
        coords = np.asarray([float(x) for x in tokens[2:]]).reshape(-1, 2)
        if not np.isfinite(coords).all() or np.any(np.abs(coords[:, 1]) > 90):
            return None
        lon, lat = np.deg2rad(coords).T
        vertices = np.column_stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)))
        if len(vertices) > 3 and np.allclose(vertices[0], vertices[-1], rtol=0, atol=1e-12):
            vertices = vertices[:-1]
        if len(vertices) < 3:
            return None
        normals = np.cross(vertices, np.roll(vertices, -1, axis=0))
        lengths = np.linalg.norm(normals, axis=1)
        if np.any(lengths < 1e-12):
            return None
        normals /= lengths[:, None]
        centre = vertices.sum(axis=0)
        normals *= np.where(normals @ centre >= 0, 1, -1)[:, None]
        # Limit this simple test to convex polygons in one hemisphere.
        if np.any(normals @ vertices.T < -1e-10) or np.any(vertices @ centre <= 0):
            return None
        lon, lat = np.deg2rad([ra, dec])
        target = [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]
        return float(np.rad2deg(np.arcsin(np.clip(normals @ target, -1, 1))).min())
    except (ValueError, TypeError, IndexError):
        return None


def rank_candidates(rows, ra, dec):
    def score(item):
        index, row, margin = item
        # Interior first, missing metadata next, known outside last. Unknown
        # footprints remain eligible; all groups still undergo the WCS check.
        category = 1 if margin is None else (0 if margin >= 0 else 2)
        try:
            r1, d1, r2, d2 = np.deg2rad([ra, dec, float(row["s_ra"]), float(row["s_dec"])])
            separation = math.acos(float(np.clip(np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(r1 - r2), -1, 1)))
            if not math.isfinite(separation):
                separation = math.inf
        except (KeyError, TypeError, ValueError):
            separation = math.inf
        return category, -(margin if margin is not None else 0), separation, index

    return sorted([(i, row, footprint_margin(row, ra, dec)) for i, row in enumerate(rows)], key=score)

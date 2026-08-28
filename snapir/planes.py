"""Best-fit planes through surveyed points.

The Design X move: rather than average a set of readings into one number,
fit a real plane to them and use that plane as the surface. A ceiling that
runs 269.77 to 273.99 across a room is not noise, it is the building. The
fitted plane keeps it, exactly, and still gives the kernel a true planar face.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Plane:
    """A plane as a point on it plus a unit normal."""
    px: float
    py: float
    pz: float
    nx: float
    ny: float
    nz: float
    rms: float = 0.0          # fit residual, cm
    max_dev: float = 0.0      # worst point, cm

    def z_at(self, x: float, y: float) -> float:
        """Height of the plane above a plan position.

        Only valid for planes that are not vertical, which every floor and
        ceiling in this data is.
        """
        if abs(self.nz) < 1e-9:
            raise ValueError("plane is vertical; no single Z above (x, y)")
        return self.pz - (self.nx * (x - self.px) + self.ny * (y - self.py)) / self.nz

    @property
    def tilt_deg(self) -> float:
        """Angle away from horizontal."""
        return float(np.degrees(np.arccos(min(1.0, abs(self.nz)))))


def fit_plane(pts: list[tuple[float, float, float]]) -> Plane:
    """Least-squares plane through three or more points, via SVD.

    Two points cannot define a plane, so a short list falls back to a level
    plane at the mean height. That is the honest answer, not a guess.
    """
    a = np.asarray(pts, dtype=float)
    centroid = a.mean(axis=0)

    if len(a) < 3:
        return Plane(*centroid, 0.0, 0.0, 1.0)

    # Smallest singular vector of the centred cloud is the plane normal.
    _u, _s, vt = np.linalg.svd(a - centroid)
    normal = vt[2]
    if normal[2] < 0:
        normal = -normal                      # keep normals pointing up

    dev = (a - centroid) @ normal
    return Plane(
        *centroid, *normal,
        rms=float(np.sqrt((dev ** 2).mean())),
        max_dev=float(np.abs(dev).max()),
    )


def level_plane(z: float) -> Plane:
    return Plane(0.0, 0.0, z, 0.0, 0.0, 1.0)


def fit_or_level(pts: list[tuple[float, float, float]], max_tilt_deg: float = 3.0) -> Plane:
    """Fit a plane, but fall back to level if the result is implausible.

    A ceiling tilted more than a few degrees means the shots picked up a
    bulkhead or a beam rather than the ceiling itself. Better to level it and
    let the operator look than to ship a visibly skewed body.
    """
    p = fit_plane(pts)
    if p.tilt_deg > max_tilt_deg:
        return level_plane(float(np.asarray(pts, dtype=float)[:, 2].mean()))
    return p

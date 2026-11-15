"""Preview-only angular presets and bounded, distortion-aware field metadata."""
from types import MappingProxyType

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_skycoord

from .wcs_axes import axes_from_fits

PROFILES = MappingProxyType({"small": ("3arcmin", 3.0), "medium": ("6.5arcmin", 6.5)})


def field_from_fits(path):
    """Sample cell-edge centre lines with full WCS; never subtract wrapped RA.

    These are sampled spherical path lengths, not a sky-aligned bounding box or
    proof that the requested square is fully covered. No science values change.
    """
    unavailable = {"available": False, "reason": "WCS field span unavailable"}
    if not axes_from_fits(path).get("available"):
        return unavailable
    try:
        with fits.open(path, memmap=False, lazy_load_hdus=True) as hdul:
            h = hdul["IMAGE"].header
            height, width = int(h["NAXIS2"]), int(h["NAXIS1"])
            wcs = WCS(h, fobj=hdul, key=" ").celestial
            horizontal = np.column_stack((np.linspace(-.5, width-.5, 17), np.full(17, (height-1)/2)))
            vertical = np.column_stack((np.full(17, (width-1)/2), np.linspace(-.5, height-.5, 17)))
            corners = np.array([[-.5,-.5],[width-.5,-.5],[width-.5,height-.5],[-.5,height-.5]])
            def sample(pixels):
                sky = pixel_to_skycoord(pixels[:,0], pixels[:,1], wcs, origin=0, mode="all").icrs
                world = np.column_stack((sky.ra.deg % 360, sky.dec.deg))
                if not np.isfinite(world).all():
                    raise ValueError("Nonfinite field WCS")
                return sky, {"pixel_xy": pixels.tolist(), "icrs_ra_dec_deg": world.tolist()}
            hs, hp = sample(horizontal)
            vs, vp = sample(vertical)
            _, cp = sample(corners)
            return {"available": True, "shape_yx": [height,width], "pixel_origin": 0,
                    "source": "FITS IMAGE celestial WCS, all distortions",
                    "method": "17-point spherical path length along each pixel-cell centre line",
                    "horizontal_arcmin": float(hs[:-1].separation(hs[1:]).arcmin.sum()),
                    "vertical_arcmin": float(vs[:-1].separation(vs[1:]).arcmin.sum()),
                    "horizontal_samples": hp, "vertical_samples": vp, "corners": cp,
                    "coverage_note": "Actual returned field; full requested coverage is not guaranteed."}
    except Exception:
        return unavailable

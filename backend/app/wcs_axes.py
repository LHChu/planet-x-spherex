"""Display-only edge coordinates evaluated by the complete Astropy WCS."""
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_skycoord


def axes_from_wcs(spatial, shape, source):
    """Use zero-based FITS pixel centres; PNG is vertically flipped, not rotated.

    Ticks sample the bottom and left pixel-cell boundaries at five positions.
    Their angular spacing may be nonuniform for rotated/distorted images.
    No centre/scale approximation or interpolation of sky coordinates is used.
    """
    unavailable = {"available": False, "reason": "WCS unavailable"}
    try:
        height, width = map(int, shape)
        if min(height, width) < 1 or not spatial.has_celestial or spatial.pixel_n_dim != 2 or spatial.world_n_dim != 2:
            return unavailable
        # Integer FITS coordinates are centres; outer cell edges are -0.5, N-0.5.
        fractions = np.linspace(0, 1, 7)[1:-1]
        x, y = width * fractions - .5, height * fractions - .5
        bottom = pixel_to_skycoord(x, np.full(5, -.5), spatial, origin=0, mode="all").icrs
        left = pixel_to_skycoord(np.full(5, -.5), y, spatial, origin=0, mode="all").icrs
        ra, dec = bottom.ra.deg % 360, left.dec.deg
        if not np.isfinite([ra, dec]).all():
            return unavailable
        return {"available": True, "frame": "ICRS", "unit": "deg", "source": source,
                "shape_yx": [height, width], "pixel_origin": 0, "png_y_flipped": True,
                "ra_edge": "bottom", "dec_edge": "left",
                "ra_ticks": [{"pixel": float(p), "degrees": float(v)} for p, v in zip(x, ra)],
                "dec_ticks": [{"pixel": float(p), "degrees": float(v)} for p, v in zip(y, dec)]}
    except Exception:
        # An optional display annotation must never prevent a valid image result.
        return unavailable


def axes_from_fits(path):
    """Keep fobj alive for SIP/lookup distortions; never use PRIMARY or alternates."""
    try:
        with fits.open(path, memmap=False, lazy_load_hdus=True) as hdul:
            header = hdul["IMAGE"].header
            required = ("CTYPE1", "CTYPE2", "CRPIX1", "CRPIX2", "CRVAL1", "CRVAL2")
            if any(key not in header for key in required):
                return {"available": False, "reason": "WCS unavailable"}
            has_cd = any(f"CD{i}_{j}" in header for i in (1, 2) for j in (1, 2))
            cd = [[header.get(f"CD{i}_{j}", 0.) for j in (1, 2)] for i in (1, 2)]
            if (has_cd and (not np.isfinite(cd).all() or np.linalg.det(cd) == 0)
                    or not has_cd and not all(f"CDELT{i}" in header for i in (1, 2))):
                return {"available": False, "reason": "WCS unavailable"}
            shape = (header.get("NAXIS2", 0), header.get("NAXIS1", 0))
            spatial = WCS(header, fobj=hdul, key=" ").celestial
            if any("-SIP" in str(header[key]) for key in ("CTYPE1", "CTYPE2")) and spatial.sip is None:
                return {"available": False, "reason": "WCS unavailable"}
            return axes_from_wcs(spatial, shape, "FITS IMAGE celestial WCS (all distortions)")
    except Exception:
        return {"available": False, "reason": "WCS unavailable"}

"""Shared Phase 1 IRSA and image logic, extracted from verify_spherex.py.

The verifier and API both call these functions. No FastAPI dependency here.
"""
import re
import time
import json
import urllib.error
import urllib.parse
import urllib.request
import numpy as np
from astropy.io import fits
from astropy.io.votable import parse
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.wcs import WCS
from astropy.wcs.utils import skycoord_to_pixel
from PIL import Image

LIMIT = 32 * 1024 * 1024


class TargetOutsideImage(ValueError):
    """A valid celestial transform placed the target outside this cutout."""

def fetch(url, path, cap, events, *, timeout=120, deadline=None):
    started = time.perf_counter()
    event = {"url": url, "destination": str(path), "bytes": 0}
    events.append(event)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SPHEREx-Minimal-Verification/1.0"})
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("NASA request deadline reached")
            timeout = min(timeout, remaining)
        with urllib.request.urlopen(request, timeout=timeout) as response, path.open("wb") as stream:
            event.update(status=response.status, content_type=response.headers.get("Content-Type"))
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("NASA download deadline reached")
                # One underlying read at a time lets us check the deadline even
                # when the peer sends data slowly, rather than filling 64 KiB.
                chunk = getattr(response, "read1", response.read)(65536)
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("NASA download deadline reached")
                if not chunk:
                    break
                event["bytes"] += len(chunk)
                if event["bytes"] > cap:
                    raise ValueError("Download exceeds configured byte limit")
                stream.write(chunk)
    except Exception as exc:
        event["error"] = repr(exc)
        if isinstance(exc, urllib.error.HTTPError):
            event["status"] = exc.code
            exc.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        event["elapsed_seconds"] = time.perf_counter() - started


def clean(value):
    if np.ma.is_masked(value):
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def query_images(ra, dec, radius_deg, output_dir, events, *, fetcher=None):
    download = fetch if fetcher is None else fetcher
    query_info = {}
    rows = []
    for collection in ("spherex_dr1", "spherex_qr3"):
        params = {"COLLECTION": collection, "POS": f"CIRCLE {ra} {dec} {radius_deg}", "MAXREC": 50}
        path = output_dir / f"{collection}.xml"
        download("https://irsa.ipac.caltech.edu/SIA?" + urllib.parse.urlencode(params), path,
              8 * 1024 * 1024, events)
        votable = parse(str(path))
        statuses = [{"value": info.value, "content": info.content}
                    for resource in votable.resources for info in resource.infos
                    if info.name == "QUERY_STATUS"]
        query_info.setdefault("query_status", {})[collection] = statuses
        if any(s["value"] == "ERROR" for s in statuses):
            raise ValueError(f"SIA QUERY_STATUS ERROR: {statuses}")
        table = votable.get_first_table().to_table(use_names_over_ids=True)
        query_info.setdefault("columns", {})[collection] = [
            {"name": c, "unit": str(table[c].unit), "description": table[c].description}
            for c in table.colnames]
        for row in table:
            data = {name: clean(row[name]) for name in table.colnames}
            match = re.search(r"(?:SPHEREx-D|D)([1-6])(?:_|$)", str(data.get("energy_bandpassname", "")))
            data["detector"] = int(match.group(1)) if match else None
            data["detector_source"] = "energy_bandpassname" if match else None
            rows.append(data)
        if rows:
            break
    return rows, query_info


def build_cutout_url(row, ra, dec, cutout_size="3arcmin"):
    url = str(row["access_url"])
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "irsa.ipac.caltech.edu" or not parts.path.startswith("/ibe/data/spherex/"):
        raise ValueError("Not an allowed IRSA SPHEREx on-premises URL")
    params = dict(urllib.parse.parse_qsl(parts.query))
    params.update(center=f"{ra},{dec}deg", size=cutout_size)
    cutout_url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(params)))
    return cutout_url


def render_cutout(path, row, ra, dec, radius_deg, output_dir, cutout_url, cutout_size="3arcmin"):
    with path.open("rb") as stream:
        if stream.read(9) != b"SIMPLE  =":
            raise ValueError("Response is not a FITS primary header")
    # A failed candidate's traceback can retain hdul/data even after __exit__.
    # These small cutouts must not leave memory mappings holding Windows handles.
    with fits.open(path, memmap=False, lazy_load_hdus=True) as hdul:
        hdu_info = []
        for hdu in hdul:
            header = hdu.header
            n = header.get("ZNAXIS", header.get("NAXIS", 0))
            prefix = "ZNAXIS" if "ZNAXIS" in header else "NAXIS"
            hdu_info.append({"name": hdu.name, "type": type(hdu).__name__,
                             "axes": [header.get(f"{prefix}{i}") for i in range(1, n + 1)],
                             "bitpix": header.get("ZBITPIX", header.get("BITPIX")),
                             "header": header.tostring(sep="\n", endcard=True, padding=False)})
        data = hdul["IMAGE"].data
        if data is None or data.ndim != 2:
            raise ValueError("IMAGE is not a 2D array")
        valid = np.isfinite(data)
        if not valid.any():
            raise ValueError("IMAGE has no finite pixels")
        # Use IMAGE's primary celestial WCS, including SIP distortion. Alternate
        # A is detector coordinates and W is wavelength, neither is RA/Dec.
        header = hdul["IMAGE"].header
        spatial = WCS(header, fobj=hdul, key=" ").celestial
        if spatial.pixel_n_dim != 2 or spatial.world_n_dim != 2:
            raise ValueError("IMAGE has no valid two-dimensional celestial WCS")
        x, y = skycoord_to_pixel(SkyCoord(ra, dec, unit="deg", frame="icrs"),
                                spatial, origin=0, mode="all")
        x, y = float(x), float(y)
        if not (np.isfinite(x) and np.isfinite(y)):
            raise ValueError(f"IMAGE WCS returned non-finite target pixel: x={x}, y={y}")
        height, width = data.shape
        # Zero-based pixel *centres* are integers; pixel cells extend by 0.5.
        # Half-open bounds agree with floor(pixel + 0.5), including edge cells.
        if not (-0.5 <= x < width - 0.5 and -0.5 <= y < height - 0.5):
            raise TargetOutsideImage(
                f"Target center is outside the returned IMAGE: ra={ra}, dec={dec}, "
                f"pixel_xy=({x:.9g}, {y:.9g}), shape_yx={data.shape}, origin=0, "
                f"bounds_x=[-0.5,{width - 0.5}), bounds_y=[-0.5,{height - 0.5}), "
                f"CTYPE=({header.get('CTYPE1')},{header.get('CTYPE2')}), "
                f"CRPIX=({header.get('CRPIX1')},{header.get('CRPIX2')}), "
                f"CRVAL=({header.get('CRVAL1')},{header.get('CRVAL2')}), "
                f"parent_window={cutout_edge_diagnostic(header, row, data.shape, x, y)}")
        ix, iy = int(np.floor(x + 0.5)), int(np.floor(y + 0.5))
        if not valid[iy, ix]:
            raise ValueError("Target pixel is not finite")
        lo, hi = np.percentile(data[valid], [1, 99])
        if hi <= lo:
            raise ValueError("IMAGE has no display contrast")
        normalized = np.nan_to_num((data.astype(np.float32) - lo) / (hi - lo), nan=0, posinf=1, neginf=0)
        normalized = np.arcsinh(10 * np.clip(normalized, 0, 1)) / np.arcsinh(10)
        pixels = np.flipud(np.rint(normalized * 255).astype(np.uint8))
        Image.fromarray(pixels).save(output_dir / "black-background.png")
        Image.fromarray(255 - pixels).save(output_dir / "white-background.png")
        metadata = {"query": {"ra": ra, "dec": dec, "radius_deg": radius_deg},
                    "cutout_size": cutout_size, "cutout_url": cutout_url,
                    "sia": row, "detector": hdul["IMAGE"].header.get("DETECTOR"),
                    "version": hdul[0].header.get("VERSION"), "hdu": hdu_info,
                    "shape": list(data.shape), "finite_pixels": int(valid.sum()),
                    "target_pixel_xy": [float(x), float(y)], "stretch": {"p1": float(lo), "p99": float(hi), "method": "asinh(10x)"},
                    "orientation": "native detector orientation; FITS rows flipped vertically for PNG"}
        # ObsCore t_min/t_max are MJD days. Preserve raw values and column metadata too.
        for key in ("t_min", "t_max"):
            if row.get(key) is not None:
                metadata[key + "_utc"] = Time(float(row[key]), format="mjd", scale="utc").isot
        (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata


def cutout_edge_diagnostic(header, row, shape, x, y):
    """Use SPHEREx's documented alternate A coordinates as diagnostics only."""
    try:
        if "0-based active pixel" not in str(header.get("WCSNAMEA", "")):
            return {"status": "parent pixel mapping unavailable"}
        x0, y0 = 1 - float(header["CRPIX1A"]), 1 - float(header["CRPIX2A"])
        parent_w, parent_h = int(row["s_xel1"]), int(row["s_xel2"])
        height, width = shape
        return {"origin_xy": [x0, y0], "parent_shape_yx": [parent_h, parent_w],
                "target_parent_xy": [x0 + x, y0 + y],
                "touches_parent_edge": any(abs(v) <= 1 for v in
                    (x0, y0, x0 + width - parent_w, y0 + height - parent_h))}
    except (KeyError, ValueError, TypeError):
        return {"status": "parent dimensions or pixel mapping unavailable"}

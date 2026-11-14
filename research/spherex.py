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
MAX_IMAGE_PIXELS = 262144  # Bound decompression/working arrays before reading IMAGE.
MAX_CLIENT_PIXELS = 65536
MAX_CLIENT_BYTES = 4 * 1024 * 1024
# Conservative display exclusions; SOURCE and informational flags remain usable.
BAD_FLAG_BITS = (1, 2, 6, 9, 15, 19)


def target_spectral_coordinates(header, hdul, x, y):
    """Alternate W is a raw-pixel lookup, with no celestial SIP correction."""
    if "CTYPE1W" not in header:
        return {"available": False, "reason": "No alternate W spectral WCS"}
    spectral_header = header.copy()
    for key in list(spectral_header):
        if re.fullmatch(r"(?:A|B|AP|BP)_(?:ORDER|\d+_\d+)", key):
            del spectral_header[key]
    try:
        wave = WCS(spectral_header, fobj=hdul, key="W")
        values = [float(v) for v in wave.all_pix2world(x, y, 0)]
        if not all(np.isfinite(values)):
            raise ValueError("Non-finite spectral coordinates")
        return {"available": True, "wavelength": values[0], "bandwidth": values[1],
                "units": list(wave.world_axis_units)}
    except (ValueError, KeyError, RuntimeError) as exc:
        return {"available": False, "reason": str(exc)}


def display_limits(values):
    """Finite, quality-selected samples only. Never percentile an empty array."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("IMAGE has no valid finite pixels for display")
    minimum, maximum = float(values.min()), float(values.max())
    lo, hi = np.percentile(values, [1, 99])
    fallback = None
    if hi <= lo:
        lo, hi, fallback = minimum, maximum, "minmax"
    if hi <= lo:
        delta = max(abs(lo) * 1e-6, 1e-6)
        lo, hi, fallback = lo - delta, hi + delta, "constant"
    if not (np.isfinite(lo) and np.isfinite(hi) and hi > lo and np.isfinite(hi - lo)):
        raise ValueError("IMAGE display range is not representable")
    return float(lo), float(hi), minimum, maximum, fallback


def stretch_pixels(data, valid, lo, hi, method="asinh"):
    if method not in ("linear", "asinh"):
        raise ValueError("Unknown display stretch")
    if not (np.isfinite(lo) and np.isfinite(hi) and hi > lo and np.isfinite(hi - lo)):
        raise ValueError("Display maximum must exceed minimum with a finite range")
    # Work on a copy of valid values; no NaN conversion or FITS mutation.
    normalized = (np.clip(data[valid].astype(np.float64), lo, hi) - lo) / (hi - lo)
    if method == "asinh":
        normalized = np.arcsinh(10 * normalized) / np.arcsinh(10)
    pixels = np.zeros(data.shape, dtype=np.uint8)
    pixels[valid] = np.rint(normalized * 255).astype(np.uint8)
    return np.flipud(pixels)


def display_payload(data, valid, flags, lo, hi, minimum, maximum, fallback, unit):
    counts, edges = np.histogram(data[valid].astype(np.float64), bins=64,
                                range=(minimum, maximum) if maximum > minimum else (lo, hi))
    # SI prefixes are case-sensitive: mJy is not MJy. Do not silently rescale.
    supported_unit = unit.replace(" ", "") == "MJy/sr"
    payload = {"unit": "MJy/sr" if supported_unit else unit,
               "source_bunit": unit, "shape": list(data.shape), "default_method": "linear",
               "order": "FITS row-major; flip y for display", "lo": lo, "hi": hi,
               "min": minimum, "max": maximum, "fallback": fallback,
               "histogram": {"counts": counts.tolist(), "edges": edges.tolist()},
               "quality_policy": {"excluded_bits": list(BAD_FLAG_BITS),
                                  "flags_present": flags is not None},
               "available": False}
    if not supported_unit:
        payload["reason"] = "IMAGE BUNIT is missing or unsupported; no MJy/sr controls"
        return payload
    if data.size > MAX_CLIENT_PIXELS:
        payload["reason"] = "Client pixel limit exceeded; PNG preview remains available"
        return payload
    payload.update(available=True,
                   values=[float(v) if np.isfinite(v) else None for v in data.ravel()],
                   valid=valid.ravel().tolist(),
                   flags=None if flags is None else flags.ravel().tolist())
    if len(json.dumps(payload, allow_nan=False).encode("utf-8")) > MAX_CLIENT_BYTES:
        for key in ("values", "valid", "flags"):
            payload.pop(key)
        payload.update(available=False, reason="Client byte limit exceeded; PNG preview remains available")
    return payload


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


def query_images(ra, dec, radius_deg, output_dir, events, *, fetcher=None, detector=None):
    if detector is not None and (type(detector) is not int or not 1 <= detector <= 6):
        raise ValueError("detector must be an integer from 1 to 6 or None")
    if detector is not None:
        return query_detector_images(ra, dec, radius_deg, output_dir, events,
                                     fetcher=fetcher, detector=detector)
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


def query_detector_images(ra, dec, radius_deg, output_dir, events, *, fetcher, detector):
    """Bounded prefix expansion; an unresolved overflow is never an absence claim.

    The API supplies its shared RequestBudget.fetch, including retries/deadline.
    DR1 remains preferred; QR3 is searched if DR1 has no matching detector.
    """
    download = fetch if fetcher is None else fetcher
    info = {"query_status": {}, "columns": {}, "detector_search": {
        "requested": detector, "attempts": [], "incomplete_collections": [],
        "truncated_collections": []}}
    search = info["detector_search"]
    for collection in ("spherex_dr1", "spherex_qr3"):
        for maxrec in (50, 500, 2000):
            params = {"COLLECTION": collection, "POS": f"CIRCLE {ra} {dec} {radius_deg}", "MAXREC": maxrec}
            path = output_dir / f"{collection}-detector-{maxrec}.xml"
            download("https://irsa.ipac.caltech.edu/SIA?" + urllib.parse.urlencode(params),
                     path, 8 * 1024 * 1024, events)
            votable = parse(str(path))
            statuses = [{"value": item.value, "content": item.content}
                        for resource in votable.resources for item in resource.infos
                        if item.name == "QUERY_STATUS"]
            if not statuses or any(s["value"] not in ("OK", "OVERFLOW") for s in statuses):
                raise ValueError(f"Invalid SIA QUERY_STATUS: {statuses}")
            info["query_status"][collection] = statuses
            table = votable.get_first_table().to_table(use_names_over_ids=True)
            info["columns"][collection] = [
                {"name": c, "unit": str(table[c].unit), "description": table[c].description}
                for c in table.colnames]
            if "energy_bandpassname" not in table.colnames:
                raise ValueError("SIA response lacks energy_bandpassname for detector selection")
            matches = []
            unknown = 0
            for row in table:
                data = {name: clean(row[name]) for name in table.colnames}
                match = re.fullmatch(r"SPHEREx-D([1-6])(?:_.*)?", str(data["energy_bandpassname"]))
                if match is None:
                    unknown += 1
                elif int(match.group(1)) == detector:
                    data.update(detector=detector, detector_source="energy_bandpassname")
                    matches.append(data)
            truncated = any(s["value"] == "OVERFLOW" for s in statuses) or len(table) >= maxrec
            search["attempts"].append({"collection": collection, "maxrec": maxrec,
                                       "rows": len(table), "matched": len(matches),
                                       "unknown_detector_rows": unknown, "truncated": truncated})
            if matches:
                # The selected prefix can be used, while completeness stays explicit.
                if truncated or unknown:
                    search["incomplete_collections"].append(collection)
                if truncated:
                    search["truncated_collections"].append(collection)
                return matches, info
            if not truncated:
                if unknown:
                    search["incomplete_collections"].append(collection)
                break
            if maxrec == 2000:
                search["incomplete_collections"].append(collection)
                search["truncated_collections"].append(collection)
    return [], info


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
        image_header = hdul["IMAGE"].header
        if (image_header.get("NAXIS") != 2 or
                int(image_header.get("NAXIS1", 0)) * int(image_header.get("NAXIS2", 0)) > MAX_IMAGE_PIXELS):
            raise ValueError("IMAGE dimensions exceed display working-memory limit")
        data = hdul["IMAGE"].data
        if data is None or data.ndim != 2:
            raise ValueError("IMAGE is not a 2D array")
        valid = np.isfinite(data)
        if not valid.any():
            raise ValueError("IMAGE has no finite pixels")
        finite_count = int(valid.sum())
        flags = None
        if "FLAGS" in hdul:
            flag_header = hdul["FLAGS"].header
            if (flag_header.get("NAXIS1"), flag_header.get("NAXIS2")) != (data.shape[1], data.shape[0]):
                raise ValueError("FLAGS dimensions do not match IMAGE")
            flags = hdul["FLAGS"].data
            if flags is None or flags.shape != data.shape or flags.dtype.kind not in "iu":
                raise ValueError("FLAGS must be an integer array matching IMAGE")
            valid &= (flags & sum(1 << bit for bit in BAD_FLAG_BITS)) == 0
        if not valid.any():
            raise ValueError("IMAGE has no valid pixels after quality masking")
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
        if not np.isfinite(data[iy, ix]):
            raise ValueError("Target pixel is not finite")
        lo, hi, minimum, maximum, fallback = display_limits(data[valid])
        pixels = stretch_pixels(data, valid, lo, hi)
        for name, gray in (("black", pixels), ("white", 255 - pixels)):
            image = Image.fromarray(gray)
            if not valid.all():
                image.putalpha(Image.fromarray(np.flipud(valid.astype(np.uint8) * 255)))
            image.save(output_dir / f"{name}-background.png")
        metadata = {"query": {"ra": ra, "dec": dec, "radius_deg": radius_deg},
                    "cutout_size": cutout_size, "cutout_url": cutout_url,
                    "sia": row, "detector": hdul["IMAGE"].header.get("DETECTOR"),
                    "version": hdul[0].header.get("VERSION"), "hdu": hdu_info,
                    "shape": list(data.shape), "finite_pixels": finite_count,
                    "valid_pixels": int(valid.sum()), "target_valid": bool(valid[iy, ix]),
                    "observation": {key: clean(header.get(key)) for key in
                                    ("DATE-OBS", "DATE-BEG", "DATE-END", "MJD-OBS", "OBSID", "DETECTOR", "BUNIT")},
                    "target_spectral": target_spectral_coordinates(header, hdul, x, y),
                    "display": display_payload(data, valid, flags, lo, hi, minimum, maximum,
                                               fallback, str(header.get("BUNIT", ""))),
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

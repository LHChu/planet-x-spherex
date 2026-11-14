"""Bounded synchronous Phase 4.4 frames. No client URLs, photometry or animation."""
import hashlib
import io
import json
import logging
import threading
import time
import uuid
import urllib.error
import urllib.request
from collections import OrderedDict
from urllib.parse import urlsplit, unquote

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from astropy.wcs.utils import skycoord_to_pixel
from PIL import Image

from research import spherex
from .epochs import MetadataBudget, mjd_utc, utc
from .frame_math import bilinear, propagate_flags, wavelength, peaks, residuals
from .nasa_requests import BudgetStopped, MAX_ATTEMPTS, REQUEST_SECONDS, retry_after_seconds
from .service import PreviewError, json_safe, preview_directory, is_timeout

log = logging.getLogger(__name__)
SIZE, SCALE = 29, 6.15
POLICY = "phase4.4-v1"


class ProductRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject even same-host redirects: no hidden requests outside the budget.
        if fp is not None:
            fp.close()
        raise ValueError("Product redirects are not permitted")


def fetch_cutout(url, path, cap, *, timeout, deadline):
    opener = urllib.request.build_opener(ProductRedirect())
    request = urllib.request.Request(url,headers={"User-Agent":"SPHEREx-Minimal-Verification/1.0"})
    try:
        with opener.open(request,timeout=timeout) as response, path.open("wb") as stream:
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("NASA download deadline reached")
                chunk = getattr(response,"read1",response.read)(65536)
                if time.monotonic() >= deadline:
                    raise TimeoutError("NASA download deadline reached")
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    raise ValueError("Download exceeds configured byte limit")
                stream.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise


class FrameBudget(MetadataBudget):
    def fetch(self, url, path, cap, events):
        for attempt in range(MAX_ATTEMPTS):
            self.check()
            self.requests += 1
            try:
                return fetch_cutout(url,path,cap,timeout=min(REQUEST_SECONDS,self.deadline-time.monotonic()),deadline=self.deadline)
            except urllib.error.HTTPError as exc:
                if exc.fp is not None:
                    exc.close()
                if exc.code not in (429,503):
                    raise
                self.not_before = time.monotonic()+max(2**attempt,retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None))
                if attempt+1 == MAX_ATTEMPTS:
                    raise


class SequenceCache:
    """Atomic sequence eviction: manifest, PNGs and raw arrays share a lifetime.

    8 MiB additional serialized storage; combined with existing caches <=32 MiB.
    Only small detached arrays are retained during construction, never FITS HDUs.
    """
    def __init__(self, ttl=600, failed_ttl=60, max_entries=16, max_bytes=8*1024*1024):
        self.ttl, self.failed_ttl = ttl, failed_ttl
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.items = OrderedDict()
        self.lock = threading.Lock()

    def prune(self):
        for key, (expiry, _, _, _, _) in list(self.items.items()):
            if expiry <= time.monotonic():
                del self.items[key]

    def find(self, selection):
        with self.lock:
            self.prune()
            return next((v[3] for v in self.items.values() if v[2] == selection), None)

    def put(self, selection, result, blobs):
        ttl = self.ttl if result["complete"] else self.failed_ttl
        sid = uuid.uuid4().hex
        result = {**result, "sequence_id": sid, "expires_at": utc(time.time()+ttl), "expires_in_seconds": ttl}
        size = len(json.dumps(result, allow_nan=False).encode()) + sum(len(b) for b in blobs.values())
        if size > self.max_bytes:
            raise PreviewError(503, "frame_capacity", "Sequence exceeds cache capacity.")
        with self.lock:
            self.prune()
            while self.items and (len(self.items) >= self.max_entries or sum(v[1] for v in self.items.values())+size > self.max_bytes):
                self.items.popitem(last=False)
            self.items[sid] = (time.monotonic()+ttl, size, selection, result, blobs)
        return result

    def blob(self, sid, name):
        with self.lock:
            self.prune()
            item = self.items.get(sid)
            return None if item is None else item[4].get(name)


def select_products(snapshot, ids):
    products = {p["product_id"]: p for p in snapshot["products"]}
    if any(pid not in products for pid in ids):
        raise PreviewError(422, "invalid_product", "Every product_id must belong to this search snapshot.")
    selected = [products[pid] for pid in ids]
    detectors = {p["detector"] for p in selected}
    if len(detectors) != 1 or next(iter(detectors)) not in range(1, 7):
        raise PreviewError(422, "detector_mismatch", "Select products from one known detector.")
    for p in selected:
        parts = urlsplit(p["access_url"])
        if (parts.scheme != "https" or parts.netloc != "irsa.ipac.caltech.edu"
                or not parts.path.startswith("/ibe/data/spherex/") or parts.query or parts.fragment
                or any(v in unquote(parts.path) for v in ("..", "\\", "\r", "\n"))
                or hashlib.sha256(p["access_url"].encode()).hexdigest() != p["product_id"]):
            raise PreviewError(422, "invalid_product_source", "Invalid server product source.")
    return selected


def grid(ra, dec):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.radesys = "ICRS"
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(SIZE+1)/2]*2
    w.wcs.cdelt = [-SCALE/3600, SCALE/3600]
    return w


def inspect_frame(path, product, ra, dec, target_grid):
    """Read only bounded IMAGE/FLAGS/-TAB; preserve native values separately."""
    with fits.open(path, memmap=False, lazy_load_hdus=True) as hdul:
        h = hdul["IMAGE"].header
        shape = (h.get("NAXIS2", 0), h.get("NAXIS1", 0))
        if h.get("NAXIS") != 2 or min(shape) < 2 or max(shape) > 128:
            raise ValueError("IMAGE must be a small 2D cutout (<=128 pixels per axis)")
        if h.get("OBSID") != product["obs_id"] or int(h.get("DETECTOR", 0)) != product["detector"]:
            raise ValueError("FITS OBSID/DETECTOR does not match selected product")
        if u.Unit(h["BUNIT"]) != u.MJy/u.sr:
            raise ValueError("Unexpected brightness unit")
        data = np.array(hdul["IMAGE"].data, copy=True)
        if data.dtype.kind != "f":
            raise ValueError("Expected floating IMAGE values")
        f = hdul["FLAGS"].header
        if f.get("NAXIS") != 2 or (f.get("NAXIS2"), f.get("NAXIS1")) != shape:
            raise ValueError("FLAGS shape mismatch")
        flags = np.array(hdul["FLAGS"].data, copy=True)
        if flags.dtype.kind not in "ui":
            raise ValueError("FLAGS must be integer bit masks")
        flags = flags.astype(np.uint64)
        spatial = WCS(h, fobj=hdul, key=" ").celestial
        if spatial.wcs.radesys != "ICRS":
            raise ValueError("Expected ICRS celestial WCS")
        x, y = map(float, skycoord_to_pixel(SkyCoord(ra, dec, unit="deg", frame="icrs"), spatial, origin=0, mode="all"))
        if not np.isfinite([x,y]).all() or not (-.5 <= x < shape[1]-.5 and -.5 <= y < shape[0]-.5):
            raise ValueError("Target outside IMAGE")
        sample = [[0,0], [shape[1]-1,0], [0,shape[0]-1], [shape[1]-1,shape[0]-1], [x,y]]
        fw = WCS(f, fobj=hdul, key=" ").celestial
        separation = SkyCoord(fw.all_pix2world(sample,0),unit="deg").separation(SkyCoord(spatial.all_pix2world(sample,0),unit="deg")).arcsec
        if not np.isfinite(separation).all() or separation.max() > 1e-4:
            raise ValueError("FLAGS WCS is not co-registered with IMAGE")
        definitions = {k[4:]: {"name": str(v).strip(), "mask": int(f["MSKM"+k[4:]]), "description": f.get("MSKD"+k[4:])}
                       for k,v in f.items() if k.startswith("MSKN")}
        if not definitions:
            raise ValueError("Missing FLAGS definitions")
        informational = 0
        for d in definitions.values():
            if d["name"] in ("SOURCE", "FULLSAMPLE"):
                informational |= d["mask"]
        good = np.isfinite(data) & ((flags & np.uint64(((1<<64)-1)^informational)) == 0)
        yy, xx = np.indices((SIZE,SIZE), dtype=float)
        sky = target_grid.all_pix2world(xx,yy,0)
        sx, sy = spatial.all_world2pix(*sky,0,tolerance=1e-8,maxiter=100,adaptive=True)
        aligned, weight, geometric = bilinear(data,good,sx,sy)
        propagated = propagate_flags(flags,sx,sy)
        sky2 = spatial.all_pix2world(sx,sy,0)
        gx, gy = target_grid.all_world2pix(*sky2,0)
        closure = np.hypot(gx-xx,gy-yy)
        closure_ok = bool(np.isfinite(closure).all() and closure.max() < 1e-5)
        ix, iy = int(np.floor(x+.5)), int(np.floor(y+.5))
        center_ok = bool(good[iy,ix] and np.isfinite(aligned[SIZE//2,SIZE//2]))
        spectral = {"status": "failed", "wavelength_um": None, "bandwidth_um": None}
        try:
            wh = hdul["WCS-WAVE"].header
            if wh.get("NAXIS1",0)*wh.get("NAXIS2",0) > 1024*1024 or any(str(v).startswith(("P","Q")) for k,v in wh.items() if k.startswith("TFORM")):
                raise ValueError("Oversized or variable-length spectral table")
            spectral = wavelength(h,hdul["WCS-WAVE"].data,x,y)
            core = WCS(h,fobj=hdul,key="W").wcs_pix2world([[x,y]],0)[0]
            core = [core[i]*u.Unit(h[f"CUNIT{i+1}W"]).to(u.um) for i in (0,1)]
            error = float(np.max(np.abs(np.array(core)-[spectral["wavelength_um"],spectral["bandwidth_um"]])))
            spectral.update(status="pass" if error < 1e-6 else "crosscheck_failed", max_check_error_um=error)
        except Exception as exc:
            spectral.update(status="failed", reason=str(exc))
        date = h.get("DATE-OBS")
        if str(h.get("TIMESYS",hdul[0].header.get("TIMESYS","UTC"))).strip().upper() != "UTC":
            raise ValueError("Unsupported non-UTC FITS observation time")
        # FITS DATE-OBS is UTC in these products; preserve literal and explicit source.
        date_utc = Time(date,format="isot",scale="utc").isot+"Z" if date else None
        metadata = {"date_obs": date, "observation_utc": date_utc or mjd_utc(product["t_min"]),
                    "time_source": "FITS_DATE-OBS" if date else "sia_t_min", "time_scale": "utc",
                    "mjd_obs": h.get("MJD-OBS"), "bunit": h["BUNIT"],
                    "target_native_xy": [x,y], "target_wavelength_um": spectral["wavelength_um"],
                    "target_bandwidth_um": spectral["bandwidth_um"], "spectral": spectral,
                    "flags_definitions": definitions, "quality_policy": "reject all except SOURCE/FULLSAMPLE; unknown bits rejected",
                    "native_shape_yx": shape, "valid_fraction": float(np.isfinite(aligned).mean()),
                    "center_valid": center_ok, "geometry": {"status": "pass" if closure_ok else "failed", "roundtrip_max_pixels": float(np.max(closure))},
                    "pipeline_version": hdul[0].header.get("VERSION"),
                    "calibration_history": [str(v) for k,v in h.items() if k == "HISTORY" and "[CALIB]" in str(v)],
                    "fits_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        arrays = dict(native_image=data, native_flags=flags, native_valid=good,
                      aligned_image=aligned, valid_mask=np.isfinite(aligned), valid_weight=weight,
                      geometric_weight=geometric, flags_or=propagated,
                      native_wcs_header=np.array(h.tostring()), grid_header=np.array(target_grid.to_header().tostring()))
        return metadata, arrays


def band_compatible(a, b):
    if a["spectral"]["status"] != "pass" or b["spectral"]["status"] != "pass":
        return False
    w = min(a["target_bandwidth_um"], b["target_bandwidth_um"])
    return (abs(a["target_wavelength_um"]-b["target_wavelength_um"]) <= .1*w
            and abs(a["target_bandwidth_um"]-b["target_bandwidth_um"])/w <= .1)


def png(data, lo, hi):
    valid = np.isfinite(data)
    scaled = np.arcsinh(10*np.clip((np.where(valid,data,lo)-lo)/max(hi-lo,1e-8),0,1))/np.arcsinh(10)
    rgba = np.zeros((*data.shape,4),np.uint8)
    rgba[:,:,:3] = np.rint(scaled[:,:,None]*255).astype(np.uint8)
    rgba[:,:,3] = valid.astype(np.uint8)*255
    out = io.BytesIO()
    Image.fromarray(np.flipud(rgba)).save(out,format="PNG")
    return out.getvalue()


def create_frames(snapshot, selected):
    ra, dec = snapshot["query"]["ra"], snapshot["query"]["dec"]
    target_grid = grid(ra,dec)
    budget = FrameBudget()  # 429/503, shared across all selected slots.
    frames, arrays = [], {}
    with preview_directory() as out:
        for index, product in enumerate(selected):
            frame = {k: product.get(k) for k in ("product_id","obs_id","detector","obs_collection","source_collections","access_url","processing","t_min","t_max")}
            frame.update(index=index, status="failed", error=None, image_url=None, data_url=None,
                         observation_utc=mjd_utc(product["t_min"]), time_source="sia_t_min", time_scale="utc",
                         target_wavelength_um=None, target_bandwidth_um=None, alignment={"status":"not_evaluated"})
            frames.append(frame)
            path = out / "cutout.fits"
            try:
                budget.check()
                url = spherex.build_cutout_url(product,ra,dec)
                budget.fetch(url,path,spherex.LIMIT,[])
                metadata, data = inspect_frame(path,product,ra,dec,target_grid)
                frame.update(metadata, status="reprojected")
                arrays[index] = data
            except Exception as exc:
                code = ("budget_stopped" if isinstance(exc,BudgetStopped) else "upstream_timeout" if is_timeout(exc)
                        else "upstream_http_error" if hasattr(exc,"code") else "frame_validation_failed")
                frame["error"] = {"code":code, "message":str(exc), "http_status":getattr(exc,"code",None), "budget_stop_reason":budget.stop_reason}
                log.warning("Epoch frame slot %s failed: %s",index,exc)
            finally:
                path.unlink(missing_ok=True)
    pair_checks = []
    for i in arrays:
        for j in arrays:
            if j <= i:
                continue
            pair_checks.append({"indices":[i,j], "band_compatible":band_compatible(frames[i],frames[j]),
                                "alignment":residuals(peaks(arrays[i]["aligned_image"]),peaks(arrays[j]["aligned_image"]))})
    for i in arrays:
        checks = [p["alignment"]["status"] for p in pair_checks if i in p["indices"]]
        ok = frames[i]["geometry"]["status"] == "pass" and frames[i]["center_valid"]
        frames[i]["alignment"] = {"status": "failed" if not ok or "residual_exceeds_threshold" in checks else "pass" if checks and all(s == "pass" for s in checks) else "unverified",
                                  "scope":"relative centroid diagnostic; WCS closure alone is not astrometric validation"}
    success = len(arrays)
    wavelength_ok = success >= 2 and all(p["band_compatible"] for p in pair_checks)
    calibration_ok = success >= 2 and all(
        frames[i]["pipeline_version"] and frames[i]["calibration_history"]
        and frames[i]["processing"]["product_version"] == "27"
        and (frames[i]["pipeline_version"],frames[i]["calibration_history"],frames[i]["bunit"]) ==
            (frames[next(iter(arrays))]["pipeline_version"],frames[next(iter(arrays))]["calibration_history"],frames[next(iter(arrays))]["bunit"])
        for i in arrays)
    common = np.logical_and.reduce([a["valid_mask"] for a in arrays.values()]) if arrays else np.zeros((SIZE,SIZE),bool)
    comparable = (success == len(selected) and wavelength_ok and calibration_ok and common.any()
                  and all(frames[i]["alignment"]["status"] == "pass" for i in arrays))
    normalization = {"policy": "shared_common_valid_p1_p99_asinh10" if comparable else "individual_p1_p99_asinh10_observation_browse",
                     "common_valid_pixels":int(common.sum()), "lo":None, "hi":None, "bunit":"MJy/sr"}
    if comparable:
        lo, hi = map(float,np.percentile(np.concatenate([a["aligned_image"][common] for a in arrays.values()]),[1,99]))
        normalization.update(lo=lo,hi=hi)
    blobs = {}
    for i, data in arrays.items():
        if comparable:
            low, high = lo, hi
        else:
            values = data["aligned_image"][data["valid_mask"]]
            low, high = map(float,np.percentile(values,[1,99])) if values.size else (0.,1.)
        frames[i]["normalization"] = {"lo":low,"hi":high,"stretch":"asinh","a":10}
        frames[i]["status"] = "ready" if frames[i]["alignment"]["status"] == "pass" else "alignment_unqualified"
        blobs[f"{i}.png"] = png(data["aligned_image"],low,high)
        raw = io.BytesIO()
        np.savez_compressed(raw,**data)
        blobs[f"{i}.npz"] = raw.getvalue()
    return json_safe({"schema_version":"1.0", "policy_version":POLICY, "search_id":snapshot["search_id"],
                     "complete":success == len(selected), "mode":"comparable_visualization" if comparable else "observation_browse",
                     "photometric_series":False, "wavelength_compatible":bool(wavelength_ok), "calibration_compatible":bool(calibration_ok),
                     "grid":{"header":dict(target_grid.to_header()),"shape_yx":[SIZE,SIZE],"pixel_scale_arcsec":SCALE},
                     "normalization":normalization, "pair_checks":pair_checks, "frames":frames,
                     "counts":{"requested":len(selected),"reprojected":success,"failed":len(selected)-success},
                     "nasa_request_count":budget.requests,
                     "warnings":["Visualization only; target bandpass is not full-field equivalence. No PSF/background/variance correction or light-curve inference."]}), blobs

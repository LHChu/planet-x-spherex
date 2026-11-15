"""Synthetic-only size prototype. No production settings or API are changed.

Run: .venv/Scripts/python.exe -m backend.tests.cutout_size_probe
The SIZE monkeypatch is scoped to a single offline worker; never import this in app.
"""
import ctypes
import io
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from backend.app import epoch_frames as epochs
from backend.app.cache import ImageCache
from backend.app.wcs_axes import axes_from_fits
from backend.tests.test_epoch_frames import synthetic, product, RA, DEC
from research import spherex

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend/test-results/cutout-sizes"


def deny_network(event, args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("All network access forbidden in synthetic size probe")


def write_synthetic(path, size, obs="one", angle=0, shape=None):
    """Reuse spectral/processing metadata, generate a larger sky-defined field."""
    synthetic(path, obs)
    shape = shape or (size, size)
    with patch.object(epochs, "SIZE", size):
        common = epochs.grid(RA, DEC)
        native = epochs.grid(RA, DEC)
    theta = np.deg2rad(angle)
    native.wcs.pc = [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]
    native.wcs.crpix = [(shape[1]+1)/2, (shape[0]+1)/2]
    yy, xx = np.indices(shape)
    gx, gy = common.all_world2pix(*native.all_pix2world(xx, yy, 0), 0)
    data = (.3 + .0001*gx + .0002*gy)
    for x, y in ((.25,.25), (.7,.25), (.25,.7), (.7,.7)):
        data += 10*np.exp(-((gx-x*size)**2+(gy-y*size)**2)/3)
    data = data.astype(np.float32)
    data[0, :3] = [np.nan, np.inf, -np.inf]
    data[0, 3:5] = [-5, 0]
    flags = np.full(shape, 1 << 21, dtype=np.uint32)
    flags[1, 1] |= 1 << 6  # rejected by both policies
    flags[2, 2] |= 1  # rejected only by stricter epoch policy
    with fits.open(path, mode="update", memmap=False) as hdul:
        for name in ("IMAGE", "FLAGS"):
            hdul[name].header.update(native.to_header())
        hdul["IMAGE"].data = data
        hdul["FLAGS"].data = flags
        # Constant synthetic wavelength table spans the entire native field.
        hdul["WCS-WAVE"].data["X"][0] = [1., float(shape[1])]
        hdul["WCS-WAVE"].data["Y"][0] = [1., float(shape[0])]
    return native


def assert_axes(path, spatial, shape):
    axes = axes_from_fits(path)
    assert axes["available"] and axes["shape_yx"] == list(shape)
    for tick in axes["ra_ticks"]:
        expected = spatial.all_pix2world([[tick["pixel"], -.5]], 0)[0, 0]
        assert abs(tick["degrees"] - expected) < 1e-9
    for tick in axes["dec_ticks"]:
        expected = spatial.all_pix2world([[-.5, tick["pixel"]]], 0)[0, 1]
        assert abs(tick["degrees"] - expected) < 1e-9
    return axes


def preview(path, out):
    return spherex.render_cutout(path, {}, RA, DEC, .01, out, "synthetic://offline", "offline-only")


def peak_rss():
    if os.name != "nt":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo(
            ctypes.c_void_p(kernel.GetCurrentProcess()), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def worker(size, mode):
    sys.addaudithook(deny_network)
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        path = out / "synthetic.fits"
        spatial = write_synthetic(path, size)
        baseline = peak_rss()
        tracemalloc.start()
        started = time.perf_counter()
        if mode == "preview":
            metadata = preview(path, out)
            assert metadata["shape"] == [size, size]
            d = metadata["display"]
            assert d["available"] and len(d["values"]) == size*size
            assert sum(d["histogram"]["counts"]) == size*size-4
            assert d["values"][:3] == [None]*3 and not d["valid"][size+1]
            assert d["valid"][2*size+2]  # explicit Preview vs epoch policy difference
            for name in ("black", "white"):
                image = Image.open(out / f"{name}-background.png").convert("RGBA")
                assert image.size == (size,size)
                assert image.getpixel((0,size-1))[3] == 0
                assert image.getpixel((1,size-2))[3] == 0
            blobs = [(out / f"{name}-background.png").read_bytes() for name in ("black", "white")]
            cache = ImageCache()
            key = cache.put(*blobs)
            assert cache.get(key) == blobs[0] and cache.get(key+"-inverse") == blobs[1]
            metadata["wcs_axes"] = assert_axes(path, spatial, (size,size))
            cache_bytes = sum(map(len, blobs))
            serialized = len(json.dumps(metadata, allow_nan=False).encode())
            fixture = metadata
        else:
            selected = [product("one"), product("two")]
            snapshot = {"search_id":"a"*32, "query":{"ra":RA,"dec":DEC}}
            def fetch(url, destination, cap, **kwargs):
                obs = Path(url.split("?")[0]).stem
                write_synthetic(destination, size, obs, angle=12 if obs == "two" else 0)
            # Offline prototype only. All native safety caps remain unchanged.
            with patch.object(epochs, "SIZE", size), patch.object(epochs, "fetch_cutout", side_effect=fetch):
                metadata, blobs = epochs.create_frames(snapshot, selected)
            assert metadata["complete"] and metadata["grid"]["shape_yx"] == [size,size]
            assert metadata["mode"] == "comparable_visualization", metadata["pair_checks"]
            for frame in metadata["frames"]:
                assert frame["geometry"]["status"] == "pass"
                assert frame["alignment"]["status"] == "pass"
                assert frame["spectral"]["status"] == "pass"
                i = frame["index"]
                with np.load(io.BytesIO(blobs[f"{i}.npz"]), allow_pickle=False) as arrays:
                    assert arrays["aligned_image"].shape == (size,size)
                    assert not arrays["native_valid"][2,2]
                    expected = arrays["aligned_image"].ravel()
                    actual = np.array([np.nan if v is None else v for v in frame["display"]["values"]])
                    np.testing.assert_allclose(actual, expected, equal_nan=True)
                assert Image.open(io.BytesIO(blobs[f"{i}.png"])).size == (size,size)
            cache = epochs.SequenceCache()
            cached = cache.put(("synthetic",size),metadata,blobs)
            assert cache.blob(cached["sequence_id"],"0.npz") == blobs["0.npz"]
            cache_bytes = next(iter(cache.items.values()))[1]
            serialized = len(json.dumps(metadata, allow_nan=False).encode())
            fixture = metadata
        elapsed = time.perf_counter()-started
        _, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result = dict(size=size, mode=mode, elapsed_seconds=elapsed, traced_peak_bytes=traced_peak,
                      process_peak_rss_bytes=peak_rss(), baseline_peak_rss_bytes=baseline,
                      serialized_metadata_bytes=serialized, cache_bytes=cache_bytes, fits_bytes=path.stat().st_size)
        (OUT / f"{mode}-{size}.json").write_text(json.dumps(fixture, allow_nan=False), encoding="utf-8")
        print(json.dumps(result))


def edge_checks():
    sys.addaudithook(deny_network)
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        path = out / "edge.fits"
        for size in (64,128):
            write_synthetic(path,size)
            # Existing production policy accepts these native inputs but still
            # emits 29x29. Test this separately from the patched-size prototype.
            metadata, arrays = epochs.inspect_frame(path,product(),RA,DEC,epochs.grid(RA,DEC))
            assert arrays["aligned_image"].shape == (29,29)
            assert metadata["native_shape_yx"] == (size,size)
            checks.append(f"native {size} accepted by unchanged epoch policy; output remains 29")
            for shape in ((size-1,size+1),(size+1,size)):
                spatial = write_synthetic(path,size,shape=shape)
                assert preview(path,out)["shape"] == list(shape)
                assert_axes(path,spatial,shape)
                if max(shape) > 128:
                    with patch.object(epochs,"SIZE",size):
                        try:
                            epochs.inspect_frame(path,product(),RA,DEC,epochs.grid(RA,DEC))
                        except ValueError as exc:
                            assert "128" in str(exc)
                        else:
                            raise AssertionError("129-axis native input must remain rejected")
                else:
                    with patch.object(epochs,"SIZE",size):
                        metadata, arrays = epochs.inspect_frame(path,product(),RA,DEC,epochs.grid(RA,DEC))
                        assert arrays["aligned_image"].shape == (size,size)
                        assert metadata["geometry"]["status"] == "pass"
                checks.append(f"preview {shape}; epoch native >128 rejected when applicable")
            for bad in ("nan", "masked", "flags_shape", "unit", "outside"):
                write_synthetic(path,size)
                with fits.open(path,mode="update",memmap=False) as hdul:
                    if bad == "nan": hdul["IMAGE"].data[:] = np.nan
                    if bad == "masked": hdul["FLAGS"].data[:] = 1 << 6
                    if bad == "flags_shape": hdul["FLAGS"].data = np.zeros((2,2),np.uint32)
                    if bad == "unit": hdul["IMAGE"].header["BUNIT"] = "unknown"
                    if bad == "outside": hdul["IMAGE"].header["CRVAL1"] = RA+10
                try:
                    metadata = preview(path,out)
                    assert bad == "unit" and not metadata["display"]["available"]
                except ValueError:
                    assert bad != "unit"
                with patch.object(epochs,"SIZE",size):
                    try:
                        metadata, arrays = epochs.inspect_frame(path,product(),RA,DEC,epochs.grid(RA,DEC))
                        assert bad in ("nan","masked") and not metadata["center_valid"]
                        assert not arrays["valid_mask"].any()
                    except ValueError:
                        assert bad in ("flags_shape","unit","outside")
                checks.append(f"{size}: {bad}")
        path.write_bytes(b"not a FITS file")
        for read in (lambda: preview(path,out), lambda: epochs.inspect_frame(path,product(),RA,DEC,epochs.grid(RA,DEC))):
            try: read()
            except (ValueError,OSError): pass
            else: raise AssertionError("Malformed FITS accepted")
    return checks


if __name__ == "__main__":
    if len(sys.argv) == 3:
        worker(int(sys.argv[1]),sys.argv[2])
    else:
        results = []
        for size in (29,64,128):
            for mode in ("preview","epochs"):
                process = subprocess.run([sys.executable,"-m","backend.tests.cutout_size_probe",str(size),mode],
                                         cwd=ROOT, capture_output=True, text=True, check=True)
                results.append(json.loads(process.stdout))
        report = {"network":"denied by Python audit hook in each worker", "samples_per_case":1,
                  "platform":platform.platform(), "python":platform.python_version(),
                  "epoch_frames":2, "measurements":results, "edge_checks":edge_checks()}
        (ROOT/"docs/cutout-size-measurements.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report,indent=2))

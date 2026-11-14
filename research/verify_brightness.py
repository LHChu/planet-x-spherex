"""Opt-in WISE 0855 check: at most one SIA response and one 3arcmin FITS.

Run from the repository root: .venv/Scripts/python.exe -m research.verify_brightness
Existing files are reused; --live permits only missing downloads, without retry.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import psutil
from astropy.io import fits
from astropy.wcs import WCS

from research import spherex
from backend.app.candidates import rank_candidates
from backend.app.service import json_safe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    out = Path("research/outputs/brightness-wise0855")
    out.mkdir(parents=True, exist_ok=True)
    events = []
    ra, dec, radius = 133.79513, -7.24515, .01
    calls = 0

    def limited_fetch(url, path, cap, events):
        nonlocal calls
        if path.exists():
            return
        if not args.live:
            raise RuntimeError("Missing local fixture; use --live for bounded verification")
        if "spherex_qr3" in url or calls >= 2:
            raise RuntimeError("Verification request budget reached; no fallback/retry")
        calls += 1
        spherex.fetch(url, path, cap, events, timeout=20)

    previous_path = out / "verification.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    report = {"query": {"ra": ra, "dec": dec, "radius_deg": radius}, "events": events,
              "download_history": previous.get("download_history", [])}
    try:
        rows, info = spherex.query_images(ra, dec, radius, out, events, fetcher=limited_fetch)
        report.update(sia_count=len(rows), query_status=info.get("query_status"),
                      rows=[{k: row.get(k) for k in ("obs_id", "detector", "t_min", "t_max", "energy_bandpassname", "em_min", "em_max")}
                            for row in rows])
        ranked = rank_candidates(rows, ra, dec)
        # Prefer longest wavelengths only among ranked candidates, without fetching others.
        ranked.sort(key=lambda entry: entry[1].get("detector") != 6)
        index, row, margin = ranked[0]
        url = spherex.build_cutout_url(row, ra, dec)
        path = out / "cutout.fits"
        report.update(selected_index=index, selected_sia=row, cutout_url=url)
        limited_fetch(url, path, spherex.LIMIT, events)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata = spherex.render_cutout(path, row, ra, dec, radius, out, url)
        report.update(metadata={k: v for k, v in metadata.items() if k not in ("hdu", "display")},
                      histogram=metadata["display"]["histogram"],
                      display_payload_bytes=len(json.dumps(metadata["display"], allow_nan=False).encode()),
                      fits_bytes=path.stat().st_size, fits_sha256=digest)
        with fits.open(path, memmap=False) as hdul:
            h = hdul["IMAGE"].header
            report["header_times"] = {k: h[k] for k in h if any(s in k for s in ("DATE", "MJD", "TSTART", "TSTOP"))}
            report["header_detector"] = h.get("DETECTOR")
            x, y = metadata["target_pixel_xy"]
            spatial = WCS(h, fobj=hdul).celestial
            report["wcs_roundtrip_radec"] = list(spatial.all_pix2world(x, y, 0))
            try:
                spectral = spherex.target_spectral_coordinates(h, hdul, x, y)
                if not spectral["available"]:
                    raise ValueError(spectral["reason"])
                report["target_wavelength_bandwidth"] = [spectral["wavelength"], spectral["bandwidth"]]
                report["spectral_units"] = spectral["units"]
            except Exception as exc:
                report["spectral_wcs_error"] = str(exc)
            valid = np.array(metadata["display"]["valid"]).reshape(hdul["IMAGE"].data.shape)
            for method in ("linear", "asinh"):
                spherex.stretch_pixels(hdul["IMAGE"].data, valid, metadata["display"]["lo"], metadata["display"]["hi"], method)
        report["fits_unchanged_after_render"] = hashlib.sha256(path.read_bytes()).hexdigest() == digest
        report["status"] = "verified_one_cutout_not_source_identification"
    except Exception as exc:
        report.update(status="incomplete", error=repr(exc))
    report["network_requests"] = calls
    report["download_history"].extend(events)
    memory = psutil.Process().memory_info()
    report["peak_process_working_set_bytes"] = getattr(memory, "peak_wset", memory.rss)
    report["memory_scope"] = "Whole verification process including imports; not concurrent API load"
    report = json_safe(report)
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "selected_sia", "histogram", "events")}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

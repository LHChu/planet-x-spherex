"""Orchestrate the shared, successful Phase 1 functions without running its CLI."""
import logging
import math
import socket
import tempfile
import time
import urllib.error
from contextlib import contextmanager
from pathlib import Path

from research import spherex
from .candidates import rank_candidates
from .nasa_requests import BudgetStopped, MAX_CANDIDATES, RequestBudget
from .wcs_axes import axes_from_fits
from .preview_size import PROFILES, field_from_fits

log = logging.getLogger(__name__)


class PreviewError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def is_timeout(exc):
    return isinstance(exc, (TimeoutError, socket.timeout)) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, (TimeoutError, socket.timeout)))


def json_safe(value):
    """FITS/SIA metadata can have masked or non-finite scalars, invalid in JSON."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    value = spherex.clean(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "tolist"):
        return json_safe(value.tolist())
    return value


@contextmanager
def preview_directory():
    """Clean up deterministically; report cleanup faults without masking errors."""
    temporary = tempfile.TemporaryDirectory(prefix="spherex-preview-")
    try:
        yield Path(temporary.name)
    except BaseException as original:
        try:
            temporary.cleanup()
        except OSError as cleanup_error:
            log.exception("Preview temporary directory cleanup failed: %s", temporary.name)
            original.add_note(f"Temporary directory cleanup also failed: {cleanup_error!r}")
        raise
    else:
        # With no active error, a cleanup fault must propagate, not be hidden.
        temporary.cleanup()


def create_preview(ra, dec, radius_deg, detector=None, cutout_profile="small"):
    if not isinstance(cutout_profile, str) or cutout_profile not in PROFILES:
        raise PreviewError(422, "invalid_cutout_profile", "Select small or medium for Preview Cutout Size.")
    cutout_size, requested_arcmin = PROFILES[cutout_profile]
    started = time.perf_counter()
    events = []
    budget = RequestBudget()
    # Radius controls SIA search only; angular cutout comes from a fixed allowlist.
    with preview_directory() as out:
        try:
            options = {} if detector is None else {"detector": detector}
            rows, query_info = spherex.query_images(ra, dec, radius_deg, out, events, fetcher=budget.fetch, **options)
        except Exception as exc:
            log.warning("SIA query failed: %r", exc)
            if is_timeout(exc) or budget.stop_reason == "deadline":
                raise PreviewError(504, "upstream_timeout", "The NASA SIA2 query timed out. Retry later.") from exc
            if detector is not None and isinstance(exc, BudgetStopped):
                raise PreviewError(503, "detector_search_incomplete", f"The D{detector} search stopped at the request budget or NASA wait limit. Data availability could not be confirmed.") from exc
            raise PreviewError(502, "upstream_error", "The NASA SIA2 query failed or returned invalid data. Retry later.") from exc
        if detector is not None:
            # Enforce selection before ranking even if a future query provider
            # returns unfiltered rows. Never fall back to a different detector.
            rows = [row for row in rows if row.get("detector") == detector]
        if not rows:
            if detector is not None:
                if query_info.get("detector_search", {}).get("incomplete_collections"):
                    raise PreviewError(503, "detector_search_incomplete", f"No D{detector} candidates were found in the returned results, but the SIA results are truncated or include unknown Detectors. This does not confirm that NASA has no matching data.")
                raise PreviewError(404, "detector_not_found", f"No D{detector} candidate images were found in the complete DR1 and QR3 SIA queries for these coordinates and radius.")
            raise PreviewError(404, "no_images", "No images were found for these coordinates and search radius.")
        timed_out = []
        seen = set()
        candidates_tried = 0
        for source_index, row, margin in rank_candidates(rows, ra, dec):
            if candidates_tried >= MAX_CANDIDATES:
                break
            try:
                url = spherex.build_cutout_url(row, ra, dec, cutout_size=cutout_size)
                if url in seen:
                    continue
                seen.add(url)  # Includes WCS-rejected URLs: never download again.
                budget.check()
                candidates_tried += 1
                fits_path = out / "cutout.fits"
                budget.fetch(url, fits_path, spherex.LIMIT, events)
                metadata = spherex.render_cutout(fits_path, row, ra, dec, radius_deg, out, url, cutout_size=cutout_size)
                if detector is not None and str(metadata.get("detector", "")).strip() != str(detector):
                    raise ValueError(f"Requested D{detector}, but FITS IMAGE DETECTOR={metadata.get('detector')!r}")
                metadata["wcs_axes"] = axes_from_fits(fits_path)
                metadata.update(query_info)
                metadata.update(cutout_profile=cutout_profile, requested_cutout_arcmin=requested_arcmin,
                                actual_shape_yx=metadata.get("shape"), wcs_field=field_from_fits(fits_path))
                metadata["requested_detector"] = detector
                metadata.update(fits_bytes=fits_path.stat().st_size,
                                image_count_returned=len(rows), candidate_attempts=candidates_tried,
                                nasa_request_count=budget.requests,
                                candidate_source_index=source_index,
                                footprint_margin_arcsec=None if margin is None else margin * 3600,
                                elapsed_seconds=time.perf_counter() - started)
                metadata["truncated"] = bool(query_info.get("detector_search", {}).get("truncated_collections")) or any(
                    s["value"] == "OVERFLOW" for statuses in query_info.get("query_status", {}).values()
                    for s in statuses)
                return (out / "black-background.png").read_bytes(), (out / "white-background.png").read_bytes(), json_safe(metadata)
            except BudgetStopped:
                log.warning("NASA preview budget stopped: %s", budget.stop_reason)
                break
            except spherex.TargetOutsideImage as exc:
                timed_out.append(False)
                log.warning("Skipping Cutout candidate source=%s: %s", source_index, exc)
            except Exception as exc:
                # Never keep exception/traceback objects across candidate retries:
                # their render_cutout frames retain HDUs and image arrays.
                timed_out.append(is_timeout(exc))
                log.warning("Cutout candidate source=%s failed: %r", source_index, exc)
        if budget.stop_reason == "deadline" or (timed_out and all(timed_out)):
            raise PreviewError(504, "upstream_timeout", "The NASA Cutout service timed out. Retry later.")
        if detector is not None:
            raise PreviewError(502, "detector_cutout_failed", f"D{detector} candidates were found, but no Cutout passed the WCS, quality, and Detector checks within the candidate and request budgets. No other Detector was used.")
        raise PreviewError(502, "cutout_failed", "No valid Cutout was obtained within the candidate and request budgets. Retry later or adjust the coordinates.")

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


def create_preview(ra, dec, radius_deg):
    started = time.perf_counter()
    events = []
    budget = RequestBudget()
    # Keep the verified 3arcmin display size. Radius controls the SIA search,
    # not the cutout size; these are deliberately separate documented inputs.
    with preview_directory() as out:
        try:
            rows, query_info = spherex.query_images(ra, dec, radius_deg, out, events, fetcher=budget.fetch)
        except Exception as exc:
            log.warning("SIA query failed: %r", exc)
            if is_timeout(exc) or budget.stop_reason == "deadline":
                raise PreviewError(504, "upstream_timeout", "NASA SIA2 查詢逾時，請稍後重試。") from exc
            raise PreviewError(502, "upstream_error", "NASA SIA2 查詢失敗或回傳無效資料，請稍後重試。") from exc
        if not rows:
            raise PreviewError(404, "no_images", "此座標與搜尋範圍內找不到影像。")
        timed_out = []
        seen = set()
        candidates_tried = 0
        for source_index, row, margin in rank_candidates(rows, ra, dec):
            if candidates_tried >= MAX_CANDIDATES:
                break
            try:
                url = spherex.build_cutout_url(row, ra, dec)
                if url in seen:
                    continue
                seen.add(url)  # Includes WCS-rejected URLs: never download again.
                budget.check()
                candidates_tried += 1
                fits_path = out / "cutout.fits"
                budget.fetch(url, fits_path, spherex.LIMIT, events)
                metadata = spherex.render_cutout(fits_path, row, ra, dec, radius_deg, out, url)
                metadata.update(query_info)
                metadata.update(fits_bytes=fits_path.stat().st_size,
                                image_count_returned=len(rows), candidate_attempts=candidates_tried,
                                nasa_request_count=budget.requests,
                                candidate_source_index=source_index,
                                footprint_margin_arcsec=None if margin is None else margin * 3600,
                                elapsed_seconds=time.perf_counter() - started)
                metadata["truncated"] = any(
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
            raise PreviewError(504, "upstream_timeout", "NASA Cutout 服務逾時，請稍後重試。")
        raise PreviewError(502, "cutout_failed", "在候選與請求預算內無法取得有效 Cutout，請稍後重試或調整座標。")

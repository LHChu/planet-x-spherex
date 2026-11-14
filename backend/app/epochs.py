"""Bounded SIA metadata snapshots. This module never requests FITS or renders frames."""
import hashlib
import hmac
import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from astropy.io.votable import parse
from astropy.time import Time

from research import spherex
from .candidates import footprint_margin
from .nasa_requests import RequestBudget, MAX_ATTEMPTS, REQUEST_SECONDS, retry_after_seconds
from .service import PreviewError, is_timeout, json_safe, preview_directory

log = logging.getLogger(__name__)
COLLECTIONS = ("spherex_dr1", "spherex_qr3")
MAXREC = 1000
SCHEMA_VERSION = "1.0"


def utc(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


class MetadataBudget(RequestBudget):
    """Same bounded policy as preview, with Phase 4.2's 429 handling."""
    def fetch(self, url, path, cap, events):
        for attempt in range(MAX_ATTEMPTS):
            self.check()
            self.requests += 1
            try:
                return spherex.fetch(url, path, cap, events,
                    timeout=min(REQUEST_SECONDS, self.deadline - time.monotonic()), deadline=self.deadline)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 503):
                    raise
                delay = max(2 ** attempt, retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None))
                self.not_before = time.monotonic() + delay
                if attempt + 1 == MAX_ATTEMPTS:
                    raise


class SnapshotCache:
    """Process-local FIFO with TTL, byte and entry limits; no raw XML retained."""
    def __init__(self, ttl=3600, empty_ttl=300, partial_ttl=60, max_entries=32, max_bytes=8*1024*1024):
        self.ttl, self.empty_ttl, self.partial_ttl = ttl, empty_ttl, partial_ttl
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.items = OrderedDict()
        self.lock = threading.Lock()
        self.secret = uuid.uuid4().bytes

    def prune(self):
        for key, (expires, _, _) in list(self.items.items()):
            if expires <= time.monotonic():
                del self.items[key]

    def find(self, query):
        with self.lock:
            self.prune()
            return next((value for _, _, value in self.items.values() if value["query"] == query), None)

    def put(self, snapshot):
        ttl = self.partial_ttl if not snapshot["complete"] else (self.ttl if snapshot["products"] else self.empty_ttl)
        snapshot.update(search_id=uuid.uuid4().hex, expires_at=utc(time.time()+ttl))
        size = len(json.dumps(snapshot, allow_nan=False).encode("utf-8"))
        if size > self.max_bytes:
            raise PreviewError(503, "metadata_capacity", "Metadata snapshot exceeds cache capacity; narrow the query.")
        with self.lock:
            self.prune()
            while self.items and (len(self.items) >= self.max_entries or sum(v[1] for v in self.items.values())+size > self.max_bytes):
                self.items.popitem(last=False)
            self.items[snapshot["search_id"]] = (time.monotonic()+ttl, size, snapshot)
        return snapshot

    def cursor(self, snapshot, offset):
        value = f'{snapshot["search_id"]}.{offset}'
        return value + "." + hmac.new(self.secret, value.encode(), "sha256").hexdigest()

    def resume(self, cursor, query):
        if not re.fullmatch(r"[0-9a-f]{32}\.[0-9]{1,6}\.[0-9a-f]{64}", cursor):
            raise PreviewError(422, "invalid_cursor", "Invalid metadata cursor.")
        sid, offset, signature = cursor.split(".")
        expected = hmac.new(self.secret, f"{sid}.{offset}".encode(), "sha256").hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise PreviewError(422, "invalid_cursor", "Invalid metadata cursor.")
        with self.lock:
            self.prune()
            item = self.items.get(sid)
        if item is None:
            raise PreviewError(410, "search_expired", "Metadata snapshot expired or was evicted; search again without a cursor.")
        snapshot = item[2]
        if snapshot["query"] != query or not 0 < int(offset) < len(snapshot["epochs"]):
            raise PreviewError(422, "invalid_cursor", "Cursor does not match this query.")
        return snapshot, int(offset)

    def page(self, snapshot, offset, limit):
        epochs = snapshot["epochs"][offset:offset+limit]
        ids = {pid for epoch in epochs for pid in epoch["product_ids"]}
        end = offset + len(epochs)
        return {**snapshot, "epochs": epochs,
                "products": [p for p in snapshot["products"] if p["product_id"] in ids],
                "pagination": {"limit": limit, "unit": "epochs", "next_cursor": self.cursor(snapshot, end) if end < len(snapshot["epochs"]) else None}}


def number(row, key):
    value = row.get(key)
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def mjd_utc(value):
    if value is None:
        return None
    try:
        return Time(value, format="mjd", scale="utc").isot + "Z"
    except (ValueError, OverflowError):
        return None


def normalize(row, collection, ra, dec):
    url = row.get("access_url")
    parts = urllib.parse.urlsplit(str(url))
    if (parts.scheme != "https" or parts.netloc != "irsa.ipac.caltech.edu"
            or not parts.path.startswith("/ibe/data/spherex/") or parts.fragment):
        raise ValueError("Invalid IRSA product URL")
    pid = hashlib.sha256(url.encode()).hexdigest()
    obs_id = row.get("obs_id") or None
    match = re.search(r"(?:SPHEREx-D|D)([1-6])(?:_|$)", str(row.get("energy_bandpassname", "")))
    version = re.search(r"(l2b(?:_retry)?)-v(\d+)-(\d{4}-\d{3})", url)
    margin = footprint_margin(row, ra, dec)
    warnings = []
    if not obs_id:
        warnings.append("missing_obs_id_not_merged_by_time")
    if margin is None:
        warnings.append("unknown_metadata_coverage")
    t_min, t_max = number(row, "t_min"), number(row, "t_max")
    if t_min is None or t_max is None or t_min > t_max:
        warnings.append("missing_or_invalid_time")
    return {"product_id": pid, "epoch_id": obs_id or "unknown-"+pid, "obs_id": obs_id,
            "obs_collection": collection, "source_collections": [collection],
            "publisher_did": row.get("obs_publisher_did"), "product_type": row.get("dataproduct_type"),
            "detector": int(match[1]) if match else None, "energy_bandpassname": row.get("energy_bandpassname"),
            "t_min": t_min, "t_max": t_max, "date_obs": None, "date_obs_source": None,
            "em_min": number(row, "em_min"), "em_max": number(row, "em_max"), "em_unit": "m",
            "target_wavelength_um": None, "target_bandwidth_um": None, "target_wavelength_status": "not_evaluated",
            "access_url": url,
            "processing": {"flavor": version[1] if version else None, "product_version": version[2] if version else None,
                           "processing_date": version[3] if version else None, "pipeline_software_version": None},
            "calibration_status": "release_compatible_header_unverified" if version and version[2] == "27" else "unknown_header_unverified",
            "coverage": {"center": "unknown" if margin is None else "metadata_contains_target" if margin >= 0 else "metadata_outside_target",
                         "footprint_margin_arcsec": None if margin is None else margin*3600, "wcs_verified": False, "valid_fraction": None},
            "native_pixel_scale_arcsec": number(row, "s_pixel_scale"),
            "frame_status": "not_requested", "image_url": None, "superseded_product_ids": [], "warnings": warnings}


def search_metadata(query, budget=None):
    budget = MetadataBudget() if budget is None else budget
    products, sources, warnings = {}, [], []
    queried_at = utc()
    with preview_directory() as out:
        for collection in query["collections"]:
            before = budget.requests
            source = {"name": collection, "status": "error", "returned_rows": None, "truncated": False, "error": None}
            try:
                params = {"COLLECTION": collection, "POS": f'CIRCLE {query["ra"]} {query["dec"]} {query["radius_deg"]}', "MAXREC": MAXREC}
                if query["time_range_mjd"] is not None:
                    params["TIME"] = " ".join(map(str, query["time_range_mjd"]))
                path = out / f"{collection}.xml"
                budget.fetch("https://irsa.ipac.caltech.edu/SIA?"+urllib.parse.urlencode(params), path, 8*1024*1024, [])
                votable = parse(str(path))
                statuses = [info.value for resource in votable.resources for info in resource.infos if info.name == "QUERY_STATUS"]
                if not statuses or any(s not in ("OK", "OVERFLOW") for s in statuses):
                    raise ValueError("Invalid SIA QUERY_STATUS")
                table = votable.get_first_table().to_table(use_names_over_ids=True)
                if len(table) > MAXREC or not {"access_url", "obs_id", "t_min", "t_max"}.issubset(table.colnames):
                    raise ValueError("Invalid or oversized SIA table")
                # Normalize the entire collection before publishing any of its rows.
                normalized = [normalize(json_safe({name: row[name] for name in table.colnames}), collection, query["ra"], query["dec"]) for row in table]
                source.update(status="partial" if "OVERFLOW" in statuses else "ok", returned_rows=len(table),
                              truncated="OVERFLOW" in statuses, query_status=statuses)
                for product in normalized:
                    if product["product_id"] in products:
                        existing = products[product["product_id"]]
                        if collection not in existing["source_collections"]:
                            existing["source_collections"].append(collection)
                    else:
                        products[product["product_id"]] = product
            except Exception as exc:
                log.warning("Epoch SIA collection %s failed: %r", collection, exc)
                code = "upstream_timeout" if is_timeout(exc) or budget.stop_reason == "deadline" else "upstream_error"
                source["error"] = {"code": code, "message": "SIA metadata query failed or budget stopped."}
            source["request_count"] = budget.requests-before
            sources.append(source)
    if all(s["status"] == "error" for s in sources):
        timeout = all(s["error"]["code"] == "upstream_timeout" for s in sources)
        raise PreviewError(504 if timeout else 502, "upstream_timeout" if timeout else "upstream_error", "All SIA metadata collections failed.")
    complete = all(s["status"] == "ok" for s in sources)
    if not complete:
        warnings.append("partial_metadata_results; narrow time range if truncated")
    selected = []
    for p in products.values():
        if query["detectors"] and p["detector"] not in query["detectors"]:
            continue
        interval = query["time_range_mjd"]
        if interval and (p["t_min"] is None or p["t_max"] is None or p["t_min"] > p["t_max"] or p["t_max"] < interval[0] or p["t_min"] > interval[1]):
            continue
        selected.append(p)
    selected.sort(key=lambda p: (p["t_min"] if p["t_min"] is not None else math.inf, p["obs_id"] or "", p["detector"] or 0, p["product_id"]))
    groups = {}
    alternatives = {}
    for p in selected:
        groups.setdefault(p["epoch_id"], []).append(p)
        if p["obs_id"]:
            alternatives.setdefault((p["obs_id"], p["detector"], p["product_type"]), []).append(p)
    for group in alternatives.values():
        if len(group) > 1:
            for p in group:
                p["warnings"].append("multiple_products_preserved_no_automatic_version_selection")
    epochs = []
    for eid, group in groups.items():
        starts = [p["t_min"] for p in group if p["t_min"] is not None]
        ends = [p["t_max"] for p in group if p["t_max"] is not None]
        start, end = min(starts, default=None), max(ends, default=None)
        epochs.append({"epoch_id": eid, "obs_id": group[0]["obs_id"], "start_mjd": start, "end_mjd": end,
                       "start_utc": mjd_utc(start), "end_utc": mjd_utc(end), "time_source": "sia", "time_scale": "utc",
                       "product_ids": [p["product_id"] for p in group]})
    epochs.sort(key=lambda e: (e["start_mjd"] if e["start_mjd"] is not None else math.inf, e["epoch_id"]))
    return {"schema_version": SCHEMA_VERSION, "query": query, "queried_at": queried_at, "time_scale": "utc",
            "collections": sources, "complete": complete,
            "counts": {"products": len(selected), "exposures": len(epochs),
                       "metadata_center_covered_exposures": len({p["epoch_id"] for p in selected if p["coverage"]["center"] == "metadata_contains_target"})},
            "epochs": epochs, "products": selected, "warnings": warnings}

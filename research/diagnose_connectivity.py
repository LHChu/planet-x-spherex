"""Opt-in standalone urllib/DNS diagnostics using the unchanged backend budget.

Run from the repository root: python -m research.diagnose_connectivity
Full source URLs go only to an ignored local artifact, never production logs.
"""
import argparse
import hashlib
import json
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from astropy.io.votable import parse

from backend.app.nasa_requests import (BudgetStopped, MAX_ATTEMPTS, MAX_REQUESTS,
    REQUEST_SECONDS, TOTAL_SECONDS, RequestBudget)
from research import spherex

ROOT = Path(__file__).resolve().parent


def endpoint(url):
    parts = urllib.parse.urlsplit(url)
    return {"scheme": parts.scheme, "hostname": parts.hostname}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--votable", type=Path, default=ROOT / "outputs/spherex_dr1.xml")
    parser.add_argument("--refresh", action="store_true", help="Query SIA once through the same bounded budget; indices may change")
    parser.add_argument("--candidates", type=int, nargs="+", default=[40,42,41,43,44,45,7,6,30,31])
    parser.add_argument("--ra", type=float, default=127.69444)
    parser.add_argument("--dec", type=float, default=-39.17760)
    parser.add_argument("--radius", type=float, default=0.01)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/python-connection-diagnostics.json")
    args = parser.parse_args()
    report = {"utc": datetime.now(timezone.utc).isoformat(), "candidates": [], "attempts": [], "waits": [],
        "snapshot_note": "Candidate indices identify only this report's SIA snapshot, not necessarily an earlier failed request.",
        "budget": {"max_requests": MAX_REQUESTS, "max_attempts_per_url": MAX_ATTEMPTS,
                   "total_seconds": TOTAL_SECONDS, "socket_timeout_seconds": REQUEST_SECONDS}}
    report["python_proxy_hosts"] = {kind: endpoint(value)["hostname"] for kind, value in urllib.request.getproxies().items()
                                    if kind in ("http", "https", "all")}
    native_dns, native_sleep = socket.getaddrinfo, time.sleep
    native_fetch = spherex.fetch
    state = {"attempt": None, "candidate": "SIA"}

    class RedirectRecorder(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            record = state["attempt"]
            destination = urllib.parse.urljoin(req.full_url, newurl)
            if record is not None:
                record["redirects"].append({"status": code, "from": endpoint(req.full_url), "to": endpoint(destination)})
                record["last_requested_endpoint"] = endpoint(destination)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    # Default ProxyHandler remains in place: same environment/Windows urllib
    # proxy configuration as the API. No forced direct connection or DNS change.
    opener = urllib.request.build_opener(RedirectRecorder())

    def trace_dns(host, *positional, **kwargs):
        entry = {"hostname": host.decode() if isinstance(host, bytes) else str(host)}
        if state["attempt"] is not None:
            state["attempt"]["dns"].append(entry)
        try:
            addresses = native_dns(host, *positional, **kwargs)
            entry["addresses"] = sorted({item[4][0] for item in addresses})
            return addresses
        except OSError as exc:
            entry.update(error_type=type(exc).__name__, errno=exc.errno)
            if state["attempt"] is not None:
                state["attempt"]["dns_failure_hostname"] = entry["hostname"]
            raise

    def trace_open(request, *positional, **kwargs):
        try:
            response = opener.open(request, *positional, **kwargs)
        except urllib.error.HTTPError as exc:
            state["attempt"].update(final_endpoint=endpoint(exc.geturl()), final_hostname_confirmed=True,
                status=exc.code, retry_after=exc.headers.get("Retry-After") if exc.headers else None)
            raise
        state["attempt"].update(final_endpoint=endpoint(response.geturl()), final_hostname_confirmed=True,
                                status=response.status, retry_after=response.headers.get("Retry-After"))
        return response

    def trace_fetch(url, path, cap, events, **kwargs):
        attempt = {"candidate_source_index": state["candidate"], "initial_endpoint": endpoint(url),
            "last_requested_endpoint": endpoint(url), "redirects": [], "dns": [],
            "final_endpoint": None, "final_hostname_confirmed": False, "started_monotonic": time.monotonic()}
        report["attempts"].append(attempt)
        state["attempt"] = attempt
        try:
            return native_fetch(url, path, cap, events, **kwargs)
        except Exception as exc:
            # Keep diagnostic types, not reprs that could embed complete URLs.
            attempt["error_type"] = type(exc).__name__
            attempt["reason_type"] = type(getattr(exc, "reason", None)).__name__
            raise
        finally:
            attempt["elapsed_seconds"] = time.monotonic() - attempt["started_monotonic"]
            state["attempt"] = None

    def trace_sleep(seconds):
        report["waits"].append({"candidate_source_index": state["candidate"], "seconds": seconds})
        return native_sleep(seconds)

    budget = RequestBudget()
    try:
        with tempfile.TemporaryDirectory(prefix="spherex-connection-diagnostic-") as directory, patch(
                "socket.getaddrinfo", side_effect=trace_dns), patch(
                "urllib.request.urlopen", side_effect=trace_open), patch.object(
                spherex, "fetch", side_effect=trace_fetch), patch("time.sleep", side_effect=trace_sleep):
            out = Path(directory)
            if args.refresh:
                rows, query_info = spherex.query_images(args.ra, args.dec, args.radius, out, [], fetcher=budget.fetch)
                collection = list(query_info["query_status"])[-1]
                snapshot = out / f"{collection}.xml"
                report["snapshot_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
                # Preserve the exact result for future source-index comparisons.
                args.output.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copyfile(snapshot, args.output.with_suffix(".votable.xml"))
            else:
                report["snapshot_path"] = str(args.votable.resolve())
                report["snapshot_sha256"] = hashlib.sha256(args.votable.read_bytes()).hexdigest()
                table = parse(str(args.votable)).get_first_table().to_table(use_names_over_ids=True)
                rows = [{name: spherex.clean(row[name]) for name in table.colnames} for row in table]
            # Check all ten URL constructions before spending any more requests.
            for index in args.candidates:
                if not 0 <= index < len(rows):
                    raise ValueError("Candidate index is outside this SIA snapshot")
                row = rows[index]
                url = spherex.build_cutout_url(row, args.ra, args.dec)
                report["candidates"].append({"candidate_source_index": index, "access_url": row["access_url"],
                    "cutout_url": url, **endpoint(url), "official_cutout_path": True})
            seen = set()
            for candidate in report["candidates"]:
                index, url = candidate["candidate_source_index"], candidate["cutout_url"]
                if url in seen:
                    continue
                seen.add(url)
                state["candidate"] = index
                try:
                    budget.fetch(url, out / "cutout.fits", spherex.LIMIT, [])
                except BudgetStopped:
                    break
                except Exception:
                    pass  # Every failed attempt is already recorded, continue bounded probe.
    except Exception as exc:
        report["diagnostic_error_type"] = type(exc).__name__
    finally:
        report["request_count"] = budget.requests
        report["stop_reason"] = budget.stop_reason
        report["attempt_counts"] = dict(Counter(str(a["candidate_source_index"]) for a in report["attempts"]))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        # Deliberately summarize only hosts/statuses; full input URLs are local.
        for attempt in report["attempts"]:
            print(json.dumps({k: attempt.get(k) for k in ("candidate_source_index", "initial_endpoint", "final_endpoint",
                  "last_requested_endpoint", "dns_failure_hostname", "status", "retry_after", "error_type")}, ensure_ascii=False))
        print(f"Diagnostic artifact: {args.output.resolve()}")
    return 1 if report.get("diagnostic_error_type") else 0


if __name__ == "__main__":
    raise SystemExit(main())

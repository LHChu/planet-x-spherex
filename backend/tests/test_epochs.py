"""Offline metadata API tests; generated VOTables require no research outputs."""
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from astropy.io.votable import from_table, writeto
from astropy.io.votable.tree import Info
from astropy.table import Table
from fastapi.testclient import TestClient

from backend.app import epochs
from backend.app.main import create_app
from research import spherex

PAYLOAD = {"ra": 127.69444, "dec": -39.1776, "radius_deg": .01}
ROOT = Path(__file__).resolve().parents[2]


def row(obs="first", detector=1, start=60000., suffix="a"):
    return {"obs_id": obs, "energy_bandpassname": f"SPHEREx-D{detector}",
            "t_min": start, "t_max": start+.001,
            "access_url": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/l2b_retry-v27-2026-197/{suffix}.fits",
            "s_region": "POLYGON ICRS 127 -40 128 -40 128 -38 127 -38",
            "em_min": 7.455e-7, "em_max": 1.1167e-6, "s_pixel_scale": 6.15}


def write_votable(path, rows, status="OK"):
    template = row()
    table = Table(names=list(template), dtype=["U80", "U30", "f8", "f8", "U300", "U150", "f8", "f8", "f8"])
    for item in rows:
        table.add_row([item[key] for key in template])
    votable = from_table(table)
    votable.resources[0].infos.append(Info(name="QUERY_STATUS", value=status))
    writeto(votable, str(path))


class EpochApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)
        self.calls = []
        self.rows = {"spherex_dr1": [row(), row(detector=4, start=60000.000001, suffix="b")],
                     "spherex_qr3": [row("second", start=60002., suffix="c")]}
        self.status = {}
        self.errors = {}
        self.fetch_patch = patch.object(spherex, "fetch", side_effect=self.fetch)
        self.fetch_patch.start()
        self.addCleanup(self.fetch_patch.stop)

    def fetch(self, url, path, cap, events, **kwargs):
        self.assertEqual(urlsplit(url).path, "/SIA")  # FITS requests fail this test.
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["MAXREC"], ["1000"])
        self.assertEqual(cap, 8*1024*1024)
        name = params["COLLECTION"][0]
        self.calls.append(params)
        if name in self.errors:
            raise self.errors[name]
        write_votable(path, self.rows[name], self.status.get(name, "OK"))

    def post(self, **fields):
        return self.client.post("/api/epochs/search", json={**PAYLOAD, **fields})

    def test_merge_group_paginate_and_cache_without_fits(self):
        first = self.post(limit=1)
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertTrue(body["complete"])
        self.assertEqual(body["counts"], {"products": 3, "exposures": 2, "metadata_center_covered_exposures": 2})
        self.assertEqual(len(body["epochs"]), 1)
        self.assertEqual(len(body["products"]), 2)
        self.assertEqual(body["epochs"][0]["start_utc"], "2023-02-25T00:00:00.000Z")
        product = body["products"][0]
        self.assertEqual(product["processing"]["flavor"], "l2b_retry")
        self.assertEqual(product["processing"]["product_version"], "27")
        for p in body["products"]:
            self.assertIsNone(p["date_obs"])
            self.assertIsNone(p["target_wavelength_um"])
            self.assertIsNone(p["image_url"])
            self.assertFalse(p["coverage"]["wcs_verified"])
            self.assertEqual(p["target_wavelength_status"], "not_evaluated")
        second = self.post(cursor=body["pagination"]["next_cursor"], limit=1).json()
        self.assertEqual(second["search_id"], body["search_id"])
        self.assertEqual(second["epochs"][0]["obs_id"], "second")
        self.assertIsNone(second["pagination"]["next_cursor"])
        self.assertEqual(self.post(limit=200).json()["search_id"], body["search_id"])
        self.assertEqual(len(self.calls), 2)

    def test_filters_time_overlap_and_collection_whitelist(self):
        result = self.post(collections=["spherex_dr1"], detectors=[4], time_range_mjd=[60000.0005, 60001.]).json()
        self.assertEqual(result["counts"]["products"], 1)
        self.assertEqual(result["products"][0]["detector"], 4)
        self.assertEqual(self.calls[0]["TIME"], ["60000.0005 60001.0"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.post(time_range_mjd=[60010., 60011.]).json()["counts"]["products"], 0)

    def test_validation_no_network(self):
        bad = [{"collections": []}, {"collections": ["spherex_dr1_deep"]},
               {"collections": ["spherex_dr1", "spherex_dr1"]}, {"detectors": []},
               {"detectors": [True]}, {"detectors": [1, 1]}, {"detectors": [7]},
               {"time_range_mjd": [2., 1.]}, {"time_range_mjd": [1.]},
               {"time_range_mjd": ["1", 2]}, {"limit": True}, {"limit": 0},
               {"limit": 201}, {"ra": "1"}, {"ra": 360.}, {"dec": -91.},
               {"radius_deg": .1}, {"access_url": "https://example.com"}, {"cursor": ""}]
        for fields in bad:
            with self.subTest(fields=fields):
                response = self.post(**fields)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_input")
        response = self.client.post("/api/epochs/search", content='{"ra": NaN, "dec": 0, "radius_deg": 0.01}', headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(self.calls), 0)

    def test_overflow_and_partial_failure_not_empty_success(self):
        self.status["spherex_dr1"] = "OVERFLOW"
        self.errors["spherex_qr3"] = TimeoutError()
        body = self.post().json()
        self.assertFalse(body["complete"])
        self.assertTrue(body["collections"][0]["truncated"])
        self.assertEqual(body["collections"][0]["status"], "partial")
        self.assertEqual(body["collections"][1]["status"], "error")
        self.assertIsNone(body["collections"][1]["returned_rows"])
        self.assertEqual(body["counts"]["products"], 2)
        self.assertTrue(body["warnings"])

    def test_empty_success_and_all_failure_errors(self):
        self.rows = dict.fromkeys(epochs.COLLECTIONS, [])
        body = self.post().json()
        self.assertTrue(body["complete"])
        self.assertEqual(body["epochs"], [])
        self.assertEqual(body["products"], [])
        for error, status in [(ValueError("malformed XML"), 502), (TimeoutError(), 504)]:
            self.app.state.epoch_cache = epochs.SnapshotCache()
            self.errors = dict.fromkeys(epochs.COLLECTIONS, error)
            response = self.post()
            self.assertEqual(response.status_code, status)
            self.assertIn("error", response.json())
        self.assertFalse(self.app.state.preview_lock.locked())

    def test_query_status_error_invalid_url_and_malformed_xml(self):
        self.status["spherex_dr1"] = "ERROR"
        self.rows["spherex_qr3"][0]["access_url"] = "https://example.com/unsafe.fits"
        self.assertEqual(self.post().status_code, 502)
        with patch.object(spherex, "fetch", side_effect=lambda url, path, *args, **kwargs: path.write_text("not XML")):
            self.assertEqual(self.post().status_code, 502)

    def test_exact_url_dedup_preserves_sources_and_versions(self):
        duplicate = dict(self.rows["spherex_dr1"][0])
        alternative = {**duplicate, "access_url": duplicate["access_url"].replace("v27", "v28")}
        self.rows["spherex_qr3"] = [duplicate, alternative]
        body = self.post().json()
        self.assertEqual(body["counts"]["products"], 3)
        self.assertEqual(body["counts"]["exposures"], 1)
        p = next(p for p in body["products"] if p["access_url"] == duplicate["access_url"])
        self.assertEqual(p["source_collections"], list(epochs.COLLECTIONS))
        p = next(p for p in body["products"] if "v28" in p["access_url"])
        self.assertEqual(p["calibration_status"], "unknown_header_unverified")
        self.assertTrue(p["warnings"])

    def test_missing_metadata_retained_without_time_merging(self):
        self.rows["spherex_dr1"] = [row("", start=float("nan")), row("", suffix="b")]
        self.rows["spherex_qr3"] = []
        body = self.post().json()
        self.assertEqual(body["counts"]["exposures"], 2)
        self.assertTrue(any(p["t_min"] is None for p in body["products"]))
        self.assertTrue(all(p["obs_id"] is None for p in body["products"]))
        json.dumps(body, allow_nan=False)

    def test_cursor_tamper_mismatch_expiry_and_restart(self):
        body = self.post(limit=1).json()
        cursor = body["pagination"]["next_cursor"]
        self.assertEqual(self.post(cursor="invalid").status_code, 422)
        self.assertEqual(self.post(cursor=cursor+"a").status_code, 422)
        self.assertEqual(self.post(cursor=cursor, detectors=[1]).status_code, 422)
        with patch.object(epochs.time, "monotonic", return_value=10**12):
            response = self.post(cursor=cursor)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(len(self.calls), 2)
        restarted = TestClient(create_app()).post("/api/epochs/search", json={**PAYLOAD, "cursor": cursor})
        self.assertEqual(restarted.status_code, 422)

    def test_shared_lock_blocks_preview_and_search_cache_hit_is_free(self):
        body = self.post().json()
        self.app.state.preview_lock.acquire()
        try:
            self.assertEqual(self.post().json()["search_id"], body["search_id"])
            result = self.post(detectors=[1])
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.headers["Retry-After"], "5")
            self.assertEqual(self.client.post("/api/preview", json=PAYLOAD).status_code, 503)
        finally:
            self.app.state.preview_lock.release()
        self.assertEqual(len(self.calls), 2)

    def test_equivalent_filter_order_and_stable_product_ids(self):
        first = self.post(detectors=[4, 1], collections=["spherex_qr3", "spherex_dr1"]).json()
        second = self.post(detectors=[1, 4]).json()
        self.assertEqual(first["search_id"], second["search_id"])
        self.assertEqual(len(self.calls), 2)
        self.app.state.epoch_cache = epochs.SnapshotCache()
        for rows in self.rows.values():
            rows.reverse()
        third = self.post(detectors=[1, 4]).json()
        self.assertEqual([p["product_id"] for p in first["products"]], [p["product_id"] for p in third["products"]])

    def test_unknown_and_outside_coverage_not_claimed_verified(self):
        self.rows["spherex_dr1"][0]["s_region"] = "CIRCLE ICRS 0 0 1"
        self.rows["spherex_dr1"][1]["s_region"] = "POLYGON ICRS 0 0 1 0 1 1 0 1"
        self.rows["spherex_qr3"] = []
        body = self.post().json()
        self.assertEqual(body["counts"]["metadata_center_covered_exposures"], 0)
        self.assertEqual({p["coverage"]["center"] for p in body["products"]}, {"unknown", "metadata_outside_target"})
        self.assertTrue(all(not p["coverage"]["wcs_verified"] for p in body["products"]))

    @unittest.skipUnless((ROOT/"research/outputs/phase4-1/spherex_dr1.xml").exists(), "Optional saved Phase 4.1 metadata")
    def test_real_phase41_metadata_replay(self):
        def replay(url, path, *args, **kwargs):
            self.assertEqual(urlsplit(url).path, "/SIA")
            name = parse_qs(urlsplit(url).query)["COLLECTION"][0]
            shutil.copyfile(ROOT/f"research/outputs/phase4-1/{name}.xml", path)
        with patch.object(spherex, "fetch", side_effect=replay):
            body = self.post(limit=200).json()
            self.assertEqual(body["counts"], {"products": 428, "exposures": 217, "metadata_center_covered_exposures": 215})
            last = self.post(limit=200, cursor=body["pagination"]["next_cursor"]).json()
        self.assertEqual(len(body["epochs"])+len(last["epochs"]), 217)
        self.assertEqual(len(body["products"])+len(last["products"]), 428)


class MetadataBudgetTests(unittest.TestCase):
    def test_retry_attempt_cap_request_limit_and_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget = epochs.MetadataBudget()
            with patch.object(spherex, "fetch", side_effect=urllib.error.HTTPError("https://test", 503, "busy", {}, None)) as fetch, patch.object(epochs.time, "sleep"):
                with self.assertRaises(urllib.error.HTTPError):
                    budget.fetch("https://test", Path(tmp)/"x", 100, [])
                self.assertEqual(fetch.call_count, 3)
                self.assertEqual(budget.requests, 3)
            for attr, value, reason in [("requests", 16, "request_limit"), ("deadline", 0, "deadline")]:
                budget = epochs.MetadataBudget()
                setattr(budget, attr, value)
                with patch.object(spherex, "fetch") as fetch:
                    with self.assertRaises(epochs.PreviewError):
                        epochs.search_metadata({**PAYLOAD, "collections": list(epochs.COLLECTIONS), "detectors": None, "time_range_mjd": None}, budget)
                    fetch.assert_not_called()
                self.assertEqual(budget.stop_reason, reason)

    def test_429_and_503_retry_after_blocks_next_collection(self):
        for status in (429, 503):
            budget = epochs.MetadataBudget()
            with tempfile.TemporaryDirectory() as tmp, patch.object(spherex, "fetch", side_effect=urllib.error.HTTPError("https://test", status, "busy", {"Retry-After": "60"}, None)) as fetch:
                with self.assertRaises(Exception):
                    budget.fetch("https://test", Path(tmp)/"x", 100, [])
                with self.assertRaises(Exception):
                    budget.fetch("https://test/next", Path(tmp)/"x", 100, [])
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(budget.stop_reason, "retry_after")


class SnapshotCacheTests(unittest.TestCase):
    def snapshot(self, query):
        return {"query": query, "complete": True, "products": [], "epochs": []}

    def test_entry_byte_limits_and_ttl(self):
        cache = epochs.SnapshotCache(max_entries=1)
        cache.put(self.snapshot({"q": 1}))
        cache.put(self.snapshot({"q": 2}))
        self.assertIsNone(cache.find({"q": 1}))
        self.assertIsNotNone(cache.find({"q": 2}))
        with patch.object(epochs.time, "monotonic", return_value=10**12):
            self.assertIsNone(cache.find({"q": 2}))
        cache = epochs.SnapshotCache(max_bytes=100)
        with self.assertRaises(epochs.PreviewError):
            cache.put(self.snapshot({"large": "x"*100}))

    def test_byte_eviction_and_partial_empty_ttl(self):
        cache = epochs.SnapshotCache(max_bytes=500, ttl=3600, empty_ttl=300, partial_ttl=60)
        cache.put(self.snapshot({"q": "a"*100}))
        cache.put(self.snapshot({"q": "b"*100}))
        self.assertIsNone(cache.find({"q": "a"*100}))
        self.assertIsNotNone(cache.find({"q": "b"*100}))
        cache = epochs.SnapshotCache()
        with patch.object(epochs.time, "monotonic", return_value=0):
            cache.put(self.snapshot({"empty": 1}))
            cache.put({**self.snapshot({"partial": 1}), "complete": False})
        with patch.object(epochs.time, "monotonic", return_value=61):
            self.assertIsNone(cache.find({"partial": 1}))
            self.assertIsNotNone(cache.find({"empty": 1}))
        with patch.object(epochs.time, "monotonic", return_value=301):
            self.assertIsNone(cache.find({"empty": 1}))


if __name__ == "__main__":
    unittest.main()

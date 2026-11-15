"""Offline detector selection, bounded SIA expansion and preview-only schema."""
import tempfile
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from astropy.io.votable import from_table, writeto
from astropy.io.votable.tree import Info
from astropy.table import Table
from fastapi.testclient import TestClient

from backend.app import service
from backend.app.main import create_app
from backend.app.nasa_requests import BudgetStopped, RequestBudget
from research import spherex

BODY = {"ra": 133.79513, "dec": -7.24515, "radius_deg": .01}
WISE = Path(__file__).resolve().parents[2] / "research/outputs/brightness-wise0855"


def row(detector, name=None):
    return {"energy_bandpassname": f"SPHEREx-D{detector}",
            "detector": detector,
            "access_url": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/{name or detector}.fits"}


def write_table(path, rows, status="OK"):
    table = Table(names=["access_url", "energy_bandpassname"], dtype=["U300", "U40"])
    for item in rows:
        table.add_row([item["access_url"], item["energy_bandpassname"]])
    votable = from_table(table)
    if status is not None:
        votable.resources[0].infos.append(Info(name="QUERY_STATUS", value=status))
    writeto(votable, str(path))


class DetectorTests(unittest.TestCase):
    @unittest.skipUnless(all((WISE / name).exists() for name in ("cutout.fits", "spherex_dr1.xml", "metadata.json")),
                         "Optional recorded WISE 0855 SIA and FITS required")
    def test_wise0855_d6_full_offline_sia_to_api(self):
        recorded = json.loads((WISE / "metadata.json").read_text(encoding="utf-8"))
        calls = []

        def replay(url, path, cap, events, **kwargs):
            calls.append(url)
            if urlsplit(url).path == "/SIA":
                shutil.copyfile(WISE / "spherex_dr1.xml", path)
            else:
                self.assertEqual(url.split("?")[0], recorded["sia"]["access_url"])
                shutil.copyfile(WISE / "cutout.fits", path)

        with patch.object(spherex, "fetch", side_effect=replay):
            client = TestClient(create_app())
            response = client.post("/api/preview", json={**BODY, "detector": 6})
        self.assertEqual(response.status_code, 200, response.text)
        metadata = response.json()["metadata"]
        self.assertEqual(metadata["requested_detector"], 6)
        self.assertEqual(metadata["sia"]["detector"], 6)
        self.assertEqual(metadata["detector"], 6)
        self.assertAlmostEqual(metadata["target_spectral"]["wavelength"], 4.860934196424479, places=9)
        self.assertEqual(metadata["observation"]["DATE-OBS"], "2025-05-05T20:01:35.430")
        self.assertEqual(metadata["valid_pixels"], 827)
        self.assertEqual(sum(metadata["display"]["histogram"]["counts"]), 827)
        self.assertTrue(metadata["truncated"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(client.get(response.json()["image_url"]).status_code, 200)
        self.assertEqual(client.get(response.json()["inverted_image_url"]).status_code, 200)

    def query(self, responder, detector=6):
        calls = []

        def fetch(url, path, cap, events):
            params = parse_qs(urlsplit(url).query)
            collection, limit = params["COLLECTION"][0], int(params["MAXREC"][0])
            calls.append((collection, limit))
            self.assertEqual(cap, 8 * 1024 * 1024)
            rows, status = responder(collection, limit)
            write_table(path, rows, status)

        with tempfile.TemporaryDirectory() as directory:
            result = spherex.query_images(**BODY, output_dir=Path(directory), events=[], fetcher=fetch, detector=detector)
        return result, calls

    def test_each_detector_and_auto(self):
        rows = [row(i) for i in range(1, 7)]
        for detector in range(1, 7):
            with self.subTest(detector=detector):
                (selected, info), calls = self.query(lambda *args: (rows, "OK"), detector)
                self.assertEqual([r["detector"] for r in selected], [detector])
                self.assertEqual(calls, [("spherex_dr1", 50)])
        (selected, info), calls = self.query(lambda *args: (rows, "OK"), None)
        self.assertEqual([r["detector"] for r in selected], list(range(1, 7)))
        self.assertNotIn("detector_search", info)
        self.assertEqual(calls, [("spherex_dr1", 50)])

    def test_missing_in_first_fifty_expands_before_cutout_and_ranking(self):
        calls, ranked = [], []

        def fetch(url, path, cap, events, **kwargs):
            if urlsplit(url).path == "/SIA":
                limit = int(parse_qs(urlsplit(url).query)["MAXREC"][0])
                calls.append(limit)
                write_table(path, [row(1, f"first-{i}") for i in range(50)] +
                            ([] if limit == 50 else [row(6)]), "OVERFLOW" if limit == 50 else "OK")
            else:
                self.assertEqual([r["detector"] for r in ranked], [6])
                self.assertIn("/6.fits?", url)
                calls.append("cutout-D6")
                path.write_bytes(b"fixture")

        def rank(rows, *args):
            ranked.extend(rows)
            return [(0, rows[0], None)]

        with patch.object(spherex, "fetch", side_effect=fetch), patch.object(service, "rank_candidates", side_effect=rank), patch.object(spherex, "render_cutout", side_effect=self.render):
            _, _, metadata = service.create_preview(**BODY, detector=6)
        self.assertEqual(calls, [50, 500, "cutout-D6"])
        self.assertEqual(metadata["requested_detector"], 6)
        self.assertEqual(metadata["nasa_request_count"], 3)
        self.assertFalse(metadata["truncated"])
        self.assertEqual(len(metadata["detector_search"]["attempts"]), 2)

    @staticmethod
    def render(path, row, ra, dec, radius, out, url, cutout_size="3arcmin"):
        assert cutout_size == "3arcmin"
        (out / "black-background.png").write_bytes(b"black")
        (out / "white-background.png").write_bytes(b"white")
        return {"detector": row["detector"]}

    def test_qr3_searched_when_dr1_has_only_other_detectors(self):
        (rows, info), calls = self.query(lambda collection, limit: ([row(6 if collection.endswith("qr3") else 1)], "OK"))
        self.assertEqual([r["detector"] for r in rows], [6])
        self.assertEqual(calls, [("spherex_dr1", 50), ("spherex_qr3", 50)])

    def test_unresolved_overflow_is_not_absence_and_has_bounded_expansion(self):
        result, calls = self.query(lambda *args: ([row(1)], "OVERFLOW"))
        self.assertEqual(calls, [(c, n) for c in ("spherex_dr1", "spherex_qr3") for n in (50, 500, 2000)])
        self.assertEqual(result[1]["detector_search"]["incomplete_collections"], ["spherex_dr1", "spherex_qr3"])
        self.assert_no_download_error(result, 503, "detector_search_incomplete")

    def test_complete_absence_unknown_detector_and_full_prefix(self):
        result, _ = self.query(lambda *args: ([row(1)], "OK"))
        self.assert_no_download_error(result, 404, "detector_not_found")
        unknown = {**row(1), "energy_bandpassname": "unknown"}
        result, _ = self.query(lambda *args: ([unknown], "OK"))
        self.assert_no_download_error(result, 503, "detector_search_incomplete")
        # Conservatively expand a full MAXREC prefix even if upstream says OK.
        _, calls = self.query(lambda collection, limit: ([row(1)] * 50 if limit == 50 else [row(6)], "OK"))
        self.assertEqual(calls, [("spherex_dr1", 50), ("spherex_dr1", 500)])

    def assert_no_download_error(self, query_result, status, code):
        with patch.object(spherex, "query_images", return_value=query_result), patch.object(service, "rank_candidates") as rank, patch.object(spherex, "fetch") as fetch:
            response = TestClient(create_app()).post("/api/preview", json={**BODY, "detector": 6})
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["error"]["code"], code)
        rank.assert_not_called()
        fetch.assert_not_called()

    def test_found_in_truncated_response_can_be_used_but_is_marked(self):
        (rows, info), calls = self.query(lambda *args: ([row(6)], "OVERFLOW"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(rows[0]["detector"], 6)
        self.assertEqual(info["detector_search"]["incomplete_collections"], ["spherex_dr1"])

    def test_invalid_status_fails_not_absence(self):
        for status in ("ERROR", None):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.query(lambda *args: ([], status))

    def test_filter_enforced_before_rank_and_wrong_fits_never_succeeds(self):
        def rank(rows, *args):
            self.assertEqual([r["detector"] for r in rows], [6])
            return [(0, rows[0], None)]

        def fetch(url, path, *args, **kwargs):
            self.assertIn("/6.fits?", url)
            path.write_bytes(b"fixture")

        with patch.object(spherex, "query_images", return_value=([row(1), row(6)], {})), patch.object(service, "rank_candidates", side_effect=rank), patch.object(spherex, "fetch", side_effect=fetch), patch.object(spherex, "render_cutout", return_value={"detector": 1}):
            with self.assertRaises(service.PreviewError) as caught:
                service.create_preview(**BODY, detector=6)
        self.assertEqual(caught.exception.code, "detector_cutout_failed")

    def test_errors_budget_deadline_and_upstream_never_become_no_data(self):
        for error, status, code in [(BudgetStopped("request_limit"), 503, "detector_search_incomplete"),
                                    (TimeoutError(), 504, "upstream_timeout"),
                                    (ValueError("bad XML"), 502, "upstream_error")]:
            with self.subTest(code=code), patch.object(spherex, "query_images", side_effect=error), patch.object(spherex, "fetch") as fetch:
                response = TestClient(create_app()).post("/api/preview", json={**BODY, "detector": 6})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                fetch.assert_not_called()
        # The shared RequestBudget also stops expansion before another fetch.
        budget = RequestBudget()
        budget.requests = 16
        with tempfile.TemporaryDirectory() as directory, patch.object(spherex, "fetch") as fetch:
            with self.assertRaises(BudgetStopped):
                spherex.query_images(**BODY, output_dir=Path(directory), events=[], fetcher=budget.fetch, detector=6)
            fetch.assert_not_called()

    def test_preview_schema_validation_auto_and_epochs_schema_unchanged(self):
        client = TestClient(create_app())
        with patch("backend.app.main.create_preview", return_value=(b"black", b"white", {})) as preview:
            for detector in (0, 7, True, "6", 1.5):
                self.assertEqual(client.post("/api/preview", json={**BODY, "detector": detector}).status_code, 422)
            preview.assert_not_called()
            for detector in range(1, 7):
                self.assertEqual(client.post("/api/preview", json={**BODY, "detector": detector}).status_code, 200)
                self.assertEqual(preview.call_args.args, (BODY["ra"], BODY["dec"], BODY["radius_deg"]))
                self.assertEqual(preview.call_args.kwargs, {"detector": detector})
            for extra in ({}, {"detector": None}):
                self.assertEqual(client.post("/api/preview", json={**BODY, **extra}).status_code, 200)
                self.assertEqual(preview.call_args.kwargs, {})
            # Preview-only field must remain rejected by the epochs endpoint.
            self.assertEqual(client.post("/api/epochs/search", json={**BODY, "detector": 6}).status_code, 422)

"""Offline tests replay Phase 1's real VOTable/FITS; live test is opt-in."""
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.cache import ImageCache
from backend.app.main import create_app
from research import spherex

FIXTURES = Path(__file__).resolve().parents[2] / "research" / "outputs"
PAYLOAD = {"ra": 127.69444, "dec": -39.17760, "radius_deg": 0.01}


class ApiTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "http://localhost:5500"}):
            self.app = create_app()
        self.client = TestClient(self.app)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_invalid_inputs_never_call_nasa(self):
        bad = [{**PAYLOAD, "ra": 360}, {**PAYLOAD, "dec": -91}, {**PAYLOAD, "radius_deg": 0},
               {**PAYLOAD, "radius_deg": 1}, {**PAYLOAD, "ra": "127.6"},
               {**PAYLOAD, "ra": True}, {**PAYLOAD, "extra": 1}, {"ra": 1}]
        with patch("backend.app.main.create_preview") as service:
            for body in bad:
                with self.subTest(body=body):
                    self.assertEqual(self.client.post("/api/preview", json=body).status_code, 422)
            for value in ("NaN", "Infinity", "-Infinity"):
                response = self.client.post("/api/preview", content='{"ra":' + value + ',"dec":0,"radius_deg":0.01}', headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422)
            service.assert_not_called()

    def test_no_data(self):
        with patch.object(spherex, "query_images", return_value=([], {})):
            response = self.client.post("/api/preview", json=PAYLOAD)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "no_images")

    def test_upstream_failures(self):
        for error, status in [(TimeoutError("timeout"), 504), (ValueError("bad VOTable"), 502)]:
            with self.subTest(status=status), patch.object(spherex, "query_images", side_effect=error):
                self.assertEqual(self.client.post("/api/preview", json=PAYLOAD).status_code, status)

    def test_cutout_failure_and_lock_release(self):
        row = {"access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/test.fits"}
        with patch.object(spherex, "query_images", return_value=([row], {})), patch.object(spherex, "fetch", side_effect=TimeoutError()):
            self.assertEqual(self.client.post("/api/preview", json=PAYLOAD).status_code, 504)
        self.assertTrue(self.app.state.preview_lock.acquire(blocking=False))
        self.app.state.preview_lock.release()

    def test_busy(self):
        self.app.state.preview_lock.acquire()
        try:
            response = self.client.post("/api/preview", json=PAYLOAD)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["Retry-After"], "5")
            self.assertEqual(self.client.get("/health").status_code, 200)
        finally:
            self.app.state.preview_lock.release()

    def test_cors(self):
        for origin, expected in [("http://localhost:5500", 200), ("https://untrusted.example", 400)]:
            response = self.client.options("/api/preview", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
            self.assertEqual(response.status_code, expected)
            if expected == 200:
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
        response = self.client.post("/api/preview", json={}, headers={"Origin": "http://localhost:5500"})
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5500")

    def test_unknown_images(self):
        for key in ("bad", "a" * 32, "a" * 32 + "-inverse"):
            self.assertEqual(self.client.get(f"/api/images/{key}.png").status_code, 404)

    @unittest.skipUnless((FIXTURES / "cutout.fits").exists(), "Phase 1 real FITS fixture is required")
    def test_real_phase1_replay(self):
        original = json.loads((FIXTURES / "metadata.json").read_text(encoding="utf-8"))
        selected_url = original["sia"]["access_url"]

        def replay_fetch(url, destination, cap, events, **kwargs):
            if "/SIA?" in url:
                shutil.copyfile(FIXTURES / "spherex_dr1.xml", destination)
            elif url.split("?")[0] == selected_url:
                shutil.copyfile(FIXTURES / "cutout.fits", destination)
            else:
                raise urllib.error.HTTPError(url, 503, "Phase 1 recorded candidate failure", {}, None)

        # This fixture replays the original selection order; ranking and timed
        # backoff are covered independently, without sleeping in this image test.
        with patch.object(spherex, "fetch", side_effect=replay_fetch), patch(
                "backend.app.service.rank_candidates", side_effect=lambda rows, *args:
                [(i, row, None) for i, row in enumerate(rows)]), patch("backend.app.nasa_requests.time.sleep"):
            response = self.client.post("/api/preview", json=PAYLOAD)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["metadata"]["shape"], [29, 29])
        self.assertEqual(result["metadata"]["sia"]["obs_id"], original["sia"]["obs_id"])
        self.assertTrue(result["metadata"]["truncated"])
        self.assertIn("t_min_utc", result["metadata"])
        black = self.client.get(result["image_url"])
        white = self.client.get(result["inverted_image_url"])
        self.assertEqual(black.headers["content-type"], "image/png")
        a = np.array(Image.open(io.BytesIO(black.content)))
        b = np.array(Image.open(io.BytesIO(white.content)))
        np.testing.assert_array_equal(a, np.array(Image.open(FIXTURES / "black-background.png")))
        np.testing.assert_array_equal(b, 255 - a)

    @unittest.skipUnless(os.getenv("SPHEREX_LIVE") == "1", "Set SPHEREX_LIVE=1 for a real NASA request")
    def test_live_nasa(self):
        response = self.client.post("/api/preview", json=PAYLOAD)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        image = self.client.get(result["image_url"])
        self.assertEqual(image.status_code, 200)
        Image.open(io.BytesIO(image.content)).verify()
        result["test_mode"] = "live NASA via FastAPI TestClient"
        report = Path(__file__).resolve().parents[1] / "test-results"
        report.mkdir(exist_ok=True)
        (report / "live-preview.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        (report / "live-preview.png").write_bytes(image.content)


class SharedLogicTests(unittest.TestCase):
    def test_qr3_fallback_only_on_empty_dr1(self):
        from astropy.table import Table
        from astropy.io.votable import from_table, writeto
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            def fetch(url, path, cap, events):
                calls.append(url)
                table = Table(names=["access_url", "energy_bandpassname"], dtype=["U200", "U30"])
                if "spherex_qr3" in url:
                    table.add_row(["https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/example.fits", "SPHEREx-D1"])
                writeto(from_table(table), str(path))

            with patch.object(spherex, "fetch", side_effect=fetch):
                rows, _ = spherex.query_images(1, 2, 0.01, root, [])
            self.assertEqual(len(calls), 2)
            self.assertEqual(rows[0]["detector"], 1)

    def test_cache_bounds_and_expiry(self):
        cache = ImageCache(ttl=1, max_entries=1, max_bytes=4)
        key = cache.put(b"a", b"b")
        self.assertEqual(cache.get(key + "-inverse"), b"b")
        cache.put(b"c", b"d")
        self.assertIsNone(cache.get(key))
        with self.assertRaises(ValueError):
            cache.put(b"12345", b"6")
        with patch("backend.app.cache.time.monotonic", return_value=0):
            key = cache.put(b"a", b"b")
        self.assertIsNone(cache.get(key))


if __name__ == "__main__":
    unittest.main()

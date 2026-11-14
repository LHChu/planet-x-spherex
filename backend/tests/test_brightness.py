"""Science/display separation, quality masks and bounded client payloads."""
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from PIL import Image
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.tests.test_cutout_regressions import write_cutout, render
from research import spherex

WISE_FIXTURE = Path(__file__).resolve().parents[2] / "research/outputs/brightness-wise0855"


class BrightnessTests(unittest.TestCase):
    @unittest.skipUnless((WISE_FIXTURE / "cutout.fits").exists(), "Optional recorded WISE 0855 cutout required")
    def test_wise0855_offline_api_replay(self):
        recorded = json.loads((WISE_FIXTURE / "metadata.json").read_text(encoding="utf-8"))
        calls = []

        def replay(url, destination, cap, events, **kwargs):
            calls.append(url)
            shutil.copyfile(WISE_FIXTURE / "cutout.fits", destination)

        with patch.object(spherex, "query_images", return_value=([recorded["sia"]], {})), patch.object(spherex, "fetch", side_effect=replay):
            client = TestClient(create_app())
            response = client.post("/api/preview", json={"ra": 133.79513, "dec": -7.24515, "radius_deg": .01})
        self.assertEqual(response.status_code, 200, response.text)
        m = response.json()["metadata"]
        self.assertEqual(m["detector"], 6)
        self.assertEqual(m["observation"]["DATE-OBS"], "2025-05-05T20:01:35.430")
        self.assertAlmostEqual(m["target_spectral"]["wavelength"], 4.860934196424479, places=9)
        self.assertEqual(m["valid_pixels"], 827)
        self.assertEqual(len(calls), 1)
        self.assertEqual(client.get(response.json()["image_url"]).status_code, 200)
        self.assertEqual(client.get(response.json()["inverted_image_url"]).status_code, 200)

    def test_degenerate_percentiles_and_empty(self):
        lo, hi, _, _, fallback = spherex.display_limits(np.r_[np.zeros(1000), 10])
        self.assertEqual((lo, hi, fallback), (0, 10, "minmax"))
        lo, hi, _, _, fallback = spherex.display_limits(np.full(5, -3.0))
        self.assertLess(lo, -3)
        self.assertGreater(hi, -3)
        self.assertEqual(fallback, "constant")
        for values in ([], [np.nan], [np.inf]):
            with self.assertRaises(ValueError):
                spherex.display_limits(values)

    def test_fits_integer_blank_and_all_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "cutout.fits"
            coord = write_cutout(path)
            with fits.open(path, memmap=False) as source:
                header = source["IMAGE"].header.copy()
            header["BLANK"] = -32768
            header["BUNIT"] = "MJy / sr"
            data = np.arange(25, dtype=np.int16).reshape(5, 5)
            data[0, 0] = -32768
            fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(data=data, header=header, name="IMAGE")]).writeto(path, overwrite=True)
            m = render(path, out, coord)
            self.assertEqual(m["valid_pixels"], 24)
            self.assertIsNone(m["display"]["values"][0])
            self.assertEqual(m["display"]["min"], 1)
            with fits.open(path, mode="update", memmap=False) as hdul:
                hdul["IMAGE"].data = np.full((5, 5), np.nan, dtype=np.float32)
            with self.assertRaisesRegex(ValueError, "no finite pixels"):
                render(path, out, coord)

    def test_raw_histogram_flags_transparency_and_immutable_fits(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "cutout.fits"
            coord = write_cutout(path)
            with fits.open(path, mode="update", memmap=False) as hdul:
                hdul["IMAGE"].header["BUNIT"] = "MJy / sr"
                hdul["IMAGE"].data[0, :4] = [np.nan, np.inf, -np.inf, -5]
                hdul["IMAGE"].data[0, 4] = 0
                flags = np.zeros((5, 5), dtype=np.int32)
                flags[1, 0] = 1 << 6  # NONFUNC
                flags[1, 1] = 1 << 21  # SOURCE is usable
                hdul.append(fits.ImageHDU(data=flags, name="FLAGS"))
            before = hashlib.sha256(path.read_bytes()).digest()
            m = render(path, out, coord)
            d = m["display"]
            self.assertTrue(d["available"])
            self.assertEqual(d["values"][:4], [None, None, None, -5])
            self.assertFalse(d["valid"][5])
            self.assertTrue(d["valid"][6])
            self.assertTrue(d["valid"][4])  # finite zero/negative are not excluded
            self.assertEqual(d["values"][4], 0)
            self.assertEqual(sum(d["histogram"]["counts"]), 21)
            self.assertEqual(d["min"], -5)
            json.dumps(m, allow_nan=False)
            a = np.array(Image.open(out / "black-background.png").convert("RGBA"))
            b = np.array(Image.open(out / "white-background.png").convert("RGBA"))
            self.assertEqual(a.shape, (5, 5, 4))
            self.assertEqual(a[4, 0, 3], 0)
            self.assertEqual(b[4, 0, 3], 0)
            self.assertEqual(a[3, 0, 3], 0)
            with fits.open(path, memmap=False) as hdul:
                for method in ("linear", "asinh"):
                    for lo, hi in ((-10, 30), (0, 1)):
                        spherex.stretch_pixels(hdul["IMAGE"].data, np.array(d["valid"]).reshape(5, 5), lo, hi, method)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
            # The existing API and PNG cache accept the additive metadata.
            with patch("backend.app.main.create_preview", return_value=(
                    (out / "black-background.png").read_bytes(),
                    (out / "white-background.png").read_bytes(), m)):
                client = TestClient(create_app())
                response = client.post("/api/preview", json={"ra": coord[0], "dec": coord[1], "radius_deg": .01})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.json()["metadata"]["display"], d)
            Image.open(io.BytesIO(client.get(response.json()["image_url"]).content)).verify()

    def test_bounds_unknown_unit_and_bad_ranges(self):
        data = np.arange(25, dtype=np.float32).reshape(5, 5)
        valid = np.ones_like(data, dtype=bool)
        args = (data, valid, None, 0., 24., 0., 24., None)
        for setting in ("MAX_CLIENT_PIXELS", "MAX_CLIENT_BYTES"):
            with patch.object(spherex, setting, 1):
                d = spherex.display_payload(*args, "MJy / sr")
                self.assertFalse(d["available"])
                self.assertNotIn("values", d)
        self.assertFalse(spherex.display_payload(*args, "Jy")["available"])
        self.assertFalse(spherex.display_payload(*args, "mJy/sr")["available"])
        for lo, hi in ((1, 1), (2, 1), (np.nan, 2), (0, np.inf)):
            with self.assertRaises(ValueError):
                spherex.stretch_pixels(data, valid, lo, hi)

    def test_all_invalid_flags_and_dimension_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "cutout.fits"
            coord = write_cutout(path)
            with patch.object(spherex, "MAX_IMAGE_PIXELS", 1):
                with self.assertRaisesRegex(ValueError, "working-memory"):
                    render(path, out, coord)
            with fits.open(path, mode="update", memmap=False) as hdul:
                hdul.append(fits.ImageHDU(data=np.full((5, 5), 1 << 6, dtype=np.int32), name="FLAGS"))
            with self.assertRaisesRegex(ValueError, "quality masking"):
                render(path, out, coord)

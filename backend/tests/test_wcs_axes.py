"""Offline celestial edge coordinates; no network or new NASA files."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, Sip

from backend.app import service
from backend.app.epoch_frames import grid, SIZE
from backend.app.wcs_axes import axes_from_fits, axes_from_wcs
from backend.tests.test_cutout_regressions import write_cutout, render


def distorted(angle=23):
    w = WCS(naxis=2)
    w.wcs.crpix = [12.3, 7.8]
    w.wcs.crval = [359.999, 60]
    w.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
    w.wcs.radesys = "ICRS"
    theta = np.deg2rad(angle)
    w.wcs.cd = .001 * np.array([[-np.cos(theta), np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    a, b = np.zeros((4, 4)), np.zeros((4, 4))
    a[2, 0], a[1, 1], b[0, 2], b[3, 0] = .002, -.001, -.003, .00001
    w.sip = Sip(a, b, None, None, w.wcs.crpix)
    return w


def manual_tan_sip(w, x, y):
    # Independent forward SIP polynomial + CD matrix + inverse TAN projection.
    u, v = x + 1 - w.wcs.crpix[0], y + 1 - w.wcs.crpix[1]
    du = sum(w.sip.a[i, j] * u**i * v**j for i, j in np.ndindex(w.sip.a.shape))
    dv = sum(w.sip.b[i, j] * u**i * v**j for i, j in np.ndindex(w.sip.b.shape))
    xi, eta = np.deg2rad(w.wcs.cd @ [u + du, v + dv])
    ra0, dec0 = np.deg2rad(w.wcs.crval)
    denominator = np.cos(dec0) - eta * np.sin(dec0)
    ra = ra0 + np.arctan2(xi, denominator)
    dec = np.arctan2(np.sin(dec0) + eta * np.cos(dec0), np.hypot(denominator, xi))
    return [np.rad2deg(ra) % 360, np.rad2deg(dec)]


class WcsAxesTests(unittest.TestCase):
    def test_exact_sip_tan_rotation_wrap_and_pixel_cell_edges(self):
        for angle in (0, 23, 90, 180, 270):
            w = distorted(angle)
            axes = axes_from_wcs(w, (17, 29), "test")
            self.assertTrue(axes["available"])
            self.assertEqual(axes["shape_yx"], [17, 29])
            json.dumps(axes, allow_nan=False)
            for tick in axes["ra_ticks"]:
                expected = manual_tan_sip(w, tick["pixel"], -.5)[0]
                error = (tick["degrees"] - expected + 180) % 360 - 180
                self.assertAlmostEqual(error, 0, places=10)
            for tick in axes["dec_ticks"]:
                expected = manual_tan_sip(w, -.5, tick["pixel"])[1]
                self.assertAlmostEqual(tick["degrees"], expected, places=10)
            self.assertTrue(all(0 <= t["degrees"] < 360 for t in axes["ra_ticks"]))
        axes = axes_from_wcs(distorted(), (17, 29), "test")
        self.assertAlmostEqual(axes["ra_ticks"][2]["pixel"], 14)
        self.assertAlmostEqual(axes["dec_ticks"][2]["pixel"], 8)
        w = distorted()
        without_sip = w.wcs_pix2world([[t["pixel"], -.5] for t in axes["ra_ticks"]], 0)[:, 0]
        self.assertGreater(np.max(np.abs(without_sip - [t["degrees"] for t in axes["ra_ticks"]])), 1e-5)

    def test_image_hdu_used_instead_of_primary_or_alternate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cutout.fits"
            write_cutout(path, sip=True)
            before = hashlib.sha256(path.read_bytes()).digest()
            axes = axes_from_fits(path)
            self.assertTrue(axes["available"])
            self.assertTrue(all(t["degrees"] > 359 or t["degrees"] < 1 for t in axes["ra_ticks"]))
            self.assertTrue(all(59 < t["degrees"] < 61 for t in axes["dec_ticks"]))
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
            path.unlink()  # No open FITS handles survive on Windows.

    def test_valid_diagonal_cd_with_implicit_zero_off_diagonal_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagonal.fits"
            header = grid(0, -60).to_header()
            del header["CDELT1"], header["CDELT2"]
            header["CD1_1"], header["CD2_2"] = -.001, .001
            fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.zeros((17, 29)), header=header, name="IMAGE")]).writeto(path)
            self.assertTrue(axes_from_fits(path)["available"])

    def test_missing_invalid_or_incomplete_sip_never_guesses(self):
        self.assertFalse(axes_from_wcs(WCS(naxis=2), (29, 29), "test")["available"])
        self.assertFalse(axes_from_wcs(grid(1, 2), (0, 29), "test")["available"])
        self.assertFalse(axes_from_fits(Path("does-not-exist.fits"))["available"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cutout.fits"
            for missing in ("CRVAL1", "CTYPE1", "CDELT1", "A_ORDER"):
                h = distorted().to_header(relax=True)
                del h[missing]
                fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.zeros((17, 29)), header=h, name="IMAGE")]).writeto(path, overwrite=True)
                self.assertFalse(axes_from_fits(path)["available"], missing)

    def test_common_grid_matches_phase44_and_flipped_png_direction(self):
        w = grid(127.69444, -39.17760)
        axes = axes_from_wcs(w, (SIZE, SIZE), "Phase 4.4 ICRS TAN output grid")
        ra, dec = axes["ra_ticks"], axes["dec_ticks"]
        self.assertTrue(all(a["degrees"] > b["degrees"] for a, b in zip(ra, ra[1:])))
        self.assertTrue(all(a["degrees"] < b["degrees"] for a, b in zip(dec, dec[1:])))
        for axis, component in (("ra_ticks", 0), ("dec_ticks", 1)):
            for tick in axes[axis]:
                xy = [tick["pixel"], -.5] if component == 0 else [-.5, tick["pixel"]]
                self.assertAlmostEqual(tick["degrees"], w.all_pix2world([xy], 0)[0, component], places=10)

    def test_preview_metadata_addition_preserves_science_and_png_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "source.fits"
            coord = write_cutout(path, sip=True)
            original_hash = hashlib.sha256(path.read_bytes()).digest()
            original = render(path, out, coord)
            pngs = [(out / f"{name}-background.png").read_bytes() for name in ("black", "white")]
            def replay(url, target, *args, **kwargs):
                shutil.copyfile(path, target)
            with patch.object(service.spherex, "query_images", return_value=([{"access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/exposure.fits"}], {})), patch.object(service.RequestBudget, "fetch", side_effect=replay):
                black, white, metadata = service.create_preview(*coord, .01)
            self.assertTrue(metadata["wcs_axes"]["available"])
            self.assertEqual([black, white], pngs)
            for key in ("display", "target_pixel_xy", "target_spectral", "shape", "valid_pixels", "stretch"):
                self.assertEqual(metadata[key], original[key], key)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), original_hash)


if __name__ == "__main__":
    unittest.main()

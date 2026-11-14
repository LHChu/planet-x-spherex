"""WCS edge cells and Windows file lifetime; no NASA connection required."""
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, Sip

from backend.app import service
from research import spherex


def write_cutout(path, target_xy=(2, 2), invalid_pixel=None, sip=False):
    """Known celestial WCS, including RA wrap, with a misleading PRIMARY WCS."""
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [3, 3]
    wcs.wcs.crval = [359.999, 60]
    wcs.wcs.cd = np.array([[-0.001, 0.0002], [0.0002, 0.001]])
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    if sip:
        a, b = np.zeros((3, 3)), np.zeros((3, 3))
        a[2, 0], b[0, 2] = 1e-4, -1e-4
        wcs.sip = Sip(a, b, None, None, wcs.wcs.crpix)
        wcs.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
    coord = wcs.pixel_to_world(*target_xy)
    header = wcs.to_header(relax=True)
    # This alternate detector WCS must not be used to convert RA/Dec.
    header["WCSAXESA"] = 2
    header["CTYPE1A"], header["CTYPE2A"] = "LINEAR", "LINEAR"
    header["CRPIX1A"], header["CRPIX2A"] = -1000, -1000
    header["DETECTOR"] = 1
    wrong = WCS(naxis=2)
    wrong.wcs.crpix, wrong.wcs.crval = [1, 1], [180, -60]
    wrong.wcs.cdelt, wrong.wcs.ctype = [0.001, 0.001], ["RA---TAN", "DEC--TAN"]
    data = np.arange(25, dtype=np.float32).reshape(5, 5)
    if invalid_pixel is not None:
        data[invalid_pixel] = np.nan
    with fits.HDUList([fits.PrimaryHDU(header=wrong.to_header()),
                       fits.ImageHDU(data=data, header=header, name="IMAGE")]) as hdul:
        hdul.writeto(path, overwrite=True)
    return float(coord.ra.deg), float(coord.dec.deg)


def render(path, out, coord):
    return spherex.render_cutout(path, {}, *coord, 0.01, out, "https://example.invalid/test")


class CutoutRegressions(unittest.TestCase):
    def test_image_primary_wcs_origin_edges_rotation_and_sip(self):
        # -0.25 is inside the first pixel cell; 4.25 is inside the last.
        for xy, sip in [((2, 2), False), ((-0.25, 2), False),
                        ((4.25, 2), False), ((2, -0.25), False),
                        ((2, 4.25), False), ((1.3, 3.1), True)]:
            with self.subTest(xy=xy, sip=sip), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                path = out / "cutout.fits"
                coord = write_cutout(path, xy, sip=sip)
                metadata = render(path, out, coord)
                np.testing.assert_allclose(metadata["target_pixel_xy"], xy, atol=1e-5)
                # On Windows rename/unlink fail if a FITS mapping is still open.
                renamed = path.with_name("renamed.fits")
                path.rename(renamed)
                renamed.unlink()

    def test_nearest_pixel_checked_instead_of_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "cutout.fits"
            # Target 1.75 belongs to pixel 2; pixel 1 is NaN and must not reject it.
            coord = write_cutout(path, (1.75, 2), invalid_pixel=(2, 1))
            render(path, out, coord)
            # Conversely, a NaN at the true nearest pixel must be rejected.
            coord = write_cutout(path, (1.75, 2), invalid_pixel=(2, 2))
            with self.assertRaisesRegex(ValueError, "Target pixel is not finite"):
                render(path, out, coord)

    def test_outside_rejection_retained_tracebacks_do_not_lock_file(self):
        retained = []
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "cutout.fits"
            for xy in [(-0.75, 2), (4.75, 2), (2, -0.75), (2, 4.75)]:
                coord = write_cutout(path, xy)
                try:
                    render(path, out, coord)
                except spherex.TargetOutsideImage as exc:
                    retained.append(exc)  # Deliberately keep live render frames.
                    self.assertIn("origin=0", str(exc))
                    self.assertIn("shape_yx=(5, 5)", str(exc))
                else:
                    self.fail("Outside target must not produce a PNG")
                path.unlink()  # Must succeed even with traceback/array references.
            self.assertEqual(len(retained), 4)
            coord = write_cutout(path)
            render(path, out, coord)  # Retry using the exact same filename.
            path.unlink()
        self.assertFalse(out.exists())

    def test_invalid_wcs_not_misreported_as_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / "cutout.fits"
            with fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(
                    data=np.arange(25, dtype=np.float32).reshape(5, 5), name="IMAGE")]) as hdul:
                hdul.writeto(path)
            try:
                render(path, out, (0, 0))
            except ValueError as exc:
                self.assertNotIsInstance(exc, spherex.TargetOutsideImage)
                self.assertIn("celestial WCS", str(exc))
                path.unlink()  # Exception is still live here.
            else:
                self.fail("Missing celestial WCS must be rejected")

    def test_invalid_candidate_then_valid_candidate_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad, good = root / "bad.fits", root / "good.fits"
            target = write_cutout(good)
            # Shift celestial CRVAL while keeping a well-formed IMAGE WCS.
            write_cutout(bad)
            with fits.open(bad, mode="update", memmap=False) as hdul:
                hdul["IMAGE"].header["CRVAL1"] = 359.9
            rows = [{"access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/" + name}
                    for name in ("bad.fits", "good.fits")]
            attempts = []

            def fetch(url, path, cap, events, **kwargs):
                if attempts:
                    # Force Windows to check that the preceding failed candidate
                    # released its handle before the next download overwrites it.
                    path.unlink()
                shutil.copyfile(bad if not attempts else good, path)
                attempts.append(path)

            with patch.object(spherex, "query_images", return_value=(rows, {})), patch.object(spherex, "fetch", side_effect=fetch):
                black, white, metadata = service.create_preview(*target, 0.01)
            self.assertEqual(metadata["candidate_attempts"], 2)
            self.assertTrue(black.startswith(b"\x89PNG"))
            self.assertTrue(white.startswith(b"\x89PNG"))
            self.assertFalse(attempts[0].parent.exists())

    def test_all_outside_candidates_preserve_api_error_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "outside.fits"
            ra, dec = write_cutout(fixture, (-2, 2))
            destinations = []
            downloaded_urls = []
            rejected_urls = []
            original_render = spherex.render_cutout

            def fetch(url, path, cap, events, **kwargs):
                shutil.copyfile(fixture, path)
                destinations.append(path)
                downloaded_urls.append(url)

            def render(path, row, *args, **kwargs):
                try:
                    return original_render(path, row, *args, **kwargs)
                except spherex.TargetOutsideImage:
                    rejected_urls.append(row["access_url"])
                    raise

            rows = [{"access_url": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/outside-{i}.fits"}
                    for i in range(2)]
            # Two distinct exposures plus a duplicate: ranking must retain all
            # unknown footprints, but the duplicate must not be downloaded again.
            candidates = [rows[0], rows[0], rows[1]]
            ranked = service.rank_candidates(candidates, ra, dec)
            self.assertEqual([index for index, _, _ in ranked], [0, 1, 2])
            self.assertTrue(all(margin is None for _, _, margin in ranked))
            with patch.object(spherex, "query_images", return_value=(candidates, {})), patch.object(spherex, "fetch", side_effect=fetch), patch.object(spherex, "render_cutout", side_effect=render):
                with self.assertRaises(service.PreviewError) as caught:
                    service.create_preview(ra, dec, 0.01)
            self.assertEqual((caught.exception.status, caught.exception.code), (502, "cutout_failed"))
            self.assertEqual(downloaded_urls, [spherex.build_cutout_url(row, ra, dec) for row in rows])
            self.assertEqual(rejected_urls, [row["access_url"] for row in rows])
            self.assertEqual(len(destinations), 2)
            for path in destinations:
                self.assertFalse(path.exists())
                self.assertFalse(path.parent.exists())

    def test_download_stream_closed_on_success_and_failure(self):
        class Download(io.BytesIO):
            status = 200
            headers = {"Content-Type": "application/fits"}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cutout.fits"
            for cap in (32, 2):
                response = Download(b"test-data")
                with patch("research.spherex.urllib.request.urlopen", return_value=response):
                    if cap == 2:
                        with self.assertRaises(ValueError):
                            spherex.fetch("https://example.invalid", path, cap, [])
                        self.assertFalse(path.exists())
                    else:
                        spherex.fetch("https://example.invalid", path, cap, [])
                        path.unlink()
                self.assertTrue(response.closed)

    def test_cleanup_error_does_not_replace_preview_error(self):
        cleanup = Mock(side_effect=PermissionError(32, "simulated file in use"))
        temporary = SimpleNamespace(name="unused-test-directory", cleanup=cleanup)
        original = service.PreviewError(502, "cutout_failed", "original error")
        with patch.object(service.tempfile, "TemporaryDirectory", return_value=temporary):
            with self.assertLogs(service.log, level="ERROR"):
                try:
                    with service.preview_directory():
                        raise original
                except service.PreviewError as exc:
                    self.assertIs(exc, original)
                    self.assertTrue(any("cleanup also failed" in note for note in exc.__notes__))
                else:
                    self.fail("Original PreviewError must propagate")
        cleanup.assert_called_once()

    def test_cleanup_error_without_original_error_is_not_hidden(self):
        temporary = SimpleNamespace(name="unused-test-directory", cleanup=Mock(side_effect=PermissionError(32, "in use")))
        with patch.object(service.tempfile, "TemporaryDirectory", return_value=temporary):
            with self.assertRaises(PermissionError):
                with service.preview_directory():
                    pass


if __name__ == "__main__":
    unittest.main()

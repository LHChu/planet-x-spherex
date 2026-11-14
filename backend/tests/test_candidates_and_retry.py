"""Bounded candidate selection and 503 retries; all requests/time are mocked."""
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

from backend.app import service
from backend.app.candidates import footprint_margin, rank_candidates
from backend.app import nasa_requests as nasa
from research import spherex


def polygon(left, right, bottom, top):
    return f"POLYGON ICRS {left} {bottom} {right} {bottom} {right} {top} {left} {top} {left} {bottom}"


class CandidateTests(unittest.TestCase):
    def test_interior_and_boundary_distance_take_priority_over_input_order(self):
        rows = [{"s_region": polygon(0.5, 2, -1, 1)}, {},
                {"s_region": polygon(-0.01, 2, -1, 1)},
                {"s_region": polygon(-1, 1, -1, 1)}]
        result = rank_candidates(rows, 0, 0)
        self.assertEqual([i for i, _, _ in result], [3, 2, 1, 0])
        self.assertGreater(result[0][2], result[1][2])
        self.assertLess(result[-1][2], 0)

    def test_ra_wrap_poles_and_winding(self):
        self.assertGreater(footprint_margin({"s_region": polygon(359, 1, -1, 1)}, 0, 0), 0)
        polar = "POLYGON ICRS 0 89 90 89 180 89 270 89"
        self.assertGreater(footprint_margin({"s_region": polar}, 0, 90), 0)
        reverse = "POLYGON ICRS 270 89 180 89 90 89 0 89"
        self.assertAlmostEqual(footprint_margin({"s_region": polar}, 0, 90),
                               footprint_margin({"s_region": reverse}, 0, 90))

    def test_unknown_or_malformed_region_is_not_declared_outside(self):
        for region in (None, "CIRCLE ICRS 0 0 1", "POLYGON ICRS 0 0 1", "POLYGON ICRS NaN 0 1 0 0 1"):
            self.assertIsNone(footprint_margin({"s_region": region}, 0, 0))

    def test_cutout_edge_diagnostics(self):
        header = {"WCSNAMEA": "0-based active pixel coordinates", "CRPIX1A": -99, "CRPIX2A": -2026}
        info = spherex.cutout_edge_diagnostic(header, {"s_xel1": 2040, "s_xel2": 2040},
                                              (13, 29), 14.0545857, 14.4063788)
        self.assertTrue(info["touches_parent_edge"])
        self.assertGreater(info["target_parent_xy"][1], 2039.5)
        self.assertEqual(info["origin_xy"], [100, 2027])

    def test_continue_after_five_and_never_redownload_outside_duplicate(self):
        rows = [{"access_url": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/{i}.fits"}
                for i in range(6)]
        rows.insert(1, rows[0])
        requested = []

        def fetch(url, path, cap, events, **kwargs):
            requested.append(url)
            path.write_bytes(b"fixture")

        def render(path, row, ra, dec, radius, out, url):
            if "5.fits?" not in url:
                raise spherex.TargetOutsideImage("outside test fixture")
            (out / "black-background.png").write_bytes(b"black-unit-fixture")
            (out / "white-background.png").write_bytes(b"white-unit-fixture")
            return {}

        with patch.object(spherex, "query_images", return_value=(rows, {})), patch.object(spherex, "fetch", side_effect=fetch), patch.object(spherex, "render_cutout", side_effect=render):
            _, _, metadata = service.create_preview(0, 0, 0.01)
        self.assertEqual(len(requested), 6)
        self.assertEqual(len(set(requested)), 6)
        self.assertEqual(metadata["candidate_attempts"], 6)

    def test_candidate_limit(self):
        rows = [{"access_url": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/{i}.fits"}
                for i in range(50)]
        with patch.object(spherex, "query_images", return_value=(rows, {})), patch.object(spherex, "fetch") as fetch, patch.object(spherex, "render_cutout", side_effect=spherex.TargetOutsideImage("outside")):
            with self.assertRaises(service.PreviewError) as caught:
                service.create_preview(0, 0, 0.01)
        self.assertEqual(caught.exception.code, "cutout_failed")
        self.assertEqual(fetch.call_count, nasa.MAX_CANDIDATES)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.waits = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cutout.fits"
        for name, fn in [("monotonic", lambda: self.now), ("sleep", self.sleep)]:
            patcher = patch(f"backend.app.nasa_requests.time.{name}", side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.budget = nasa.RequestBudget()

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds

    def error(self, status=503, retry_after=None):
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return urllib.error.HTTPError("https://irsa.ipac.caltech.edu/test", status, "test", headers, None)

    def fetch(self, url="https://irsa.ipac.caltech.edu/test"):
        return self.budget.fetch(url, self.path, 32, [])

    def test_exponential_backoff_then_success(self):
        with patch.object(spherex, "fetch", side_effect=[self.error(), self.error(), None]) as download:
            self.fetch()
        self.assertEqual(self.waits, [1, 2])
        self.assertEqual(download.call_count, 3)
        self.assertEqual(self.budget.requests, 3)
        self.assertLessEqual(download.call_args.kwargs["timeout"], nasa.REQUEST_SECONDS)

    def test_retry_after_seconds_and_http_date(self):
        stamp = 1700000000
        date = format_datetime(datetime.fromtimestamp(stamp + 7, timezone.utc), usegmt=True)
        for header, expected in [("5", 5), (date, 7)]:
            self.waits.clear()
            self.budget = nasa.RequestBudget()
            with patch("backend.app.nasa_requests.time.time", return_value=stamp), patch.object(
                    spherex, "fetch", side_effect=[self.error(retry_after=header), None]):
                self.fetch()
            self.assertEqual(self.waits, [expected])

    def test_invalid_retry_after_uses_backoff(self):
        with patch.object(spherex, "fetch", side_effect=[self.error(retry_after="invalid"), None]):
            self.fetch()
        self.assertEqual(self.waits, [1])

    def test_large_retry_after_stops_instead_of_retrying_early_or_switching_url(self):
        with patch.object(spherex, "fetch", side_effect=self.error(retry_after="60")) as download:
            with self.assertRaises(nasa.BudgetStopped):
                self.fetch()
            with self.assertRaises(nasa.BudgetStopped):
                self.fetch("https://irsa.ipac.caltech.edu/another")
        self.assertEqual(download.call_count, 1)
        self.assertEqual(self.waits, [])
        self.assertEqual(self.budget.stop_reason, "retry_after")

    def test_persistent_503_has_finite_attempts_and_cross_candidate_cooldown(self):
        with patch.object(spherex, "fetch", side_effect=self.error()) as download:
            with self.assertRaises(urllib.error.HTTPError):
                self.fetch()
        self.assertEqual(download.call_count, 3)
        with patch.object(spherex, "fetch"):
            self.fetch("https://irsa.ipac.caltech.edu/another")
        self.assertEqual(self.waits, [1, 2, 4])

    def test_non_503_not_retried(self):
        for error in (self.error(404), TimeoutError("test")):
            with patch.object(spherex, "fetch", side_effect=error) as download:
                with self.assertRaises(type(error)):
                    self.fetch()
            self.assertEqual(download.call_count, 1)
        self.assertEqual(self.waits, [])

    def test_shared_request_cap_and_deadline(self):
        with patch("backend.app.nasa_requests.MAX_REQUESTS", 2), patch.object(spherex, "fetch") as download:
            self.fetch()
            self.fetch("https://irsa.ipac.caltech.edu/another")
            with self.assertRaises(nasa.BudgetStopped):
                self.fetch()
        self.assertEqual(download.call_count, 2)
        self.assertEqual(self.budget.stop_reason, "request_limit")
        self.budget = nasa.RequestBudget()
        self.now = self.budget.deadline + 1
        with patch.object(spherex, "fetch") as download:
            with self.assertRaises(nasa.BudgetStopped):
                self.fetch()
        download.assert_not_called()
        self.assertEqual(self.budget.stop_reason, "deadline")


if __name__ == "__main__":
    unittest.main()

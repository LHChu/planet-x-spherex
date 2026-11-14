"""Offline API/numerical tests. Generated FITS required; local research replay optional."""
import hashlib
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import epoch_frames as m
from backend.app.epochs import normalize
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
RA, DEC = 127.69444, -39.1776


def product(obs="one", detector=1):
    return normalize({"obs_id":obs,"energy_bandpassname":f"SPHEREx-D{detector}",
                      "access_url":f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/l2b-v27-2026-196/{obs}.fits",
                      "t_min":60794.,"t_max":60794.001},"spherex_dr1",RA,DEC)


def synthetic(path, obs, detector=1, wave=.86, bandwidth=.021, angle=0, shift=0, bad=False):
    w = m.grid(RA,DEC)
    theta = np.deg2rad(angle)
    w.wcs.pc = [[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]]
    w.wcs.crpix += shift
    h = w.to_header()
    h.update(OBSID=obs,DETECTOR=str(detector),BUNIT="MJy / sr",DATE_OBS="unused")
    h["DATE-OBS"] = "2025-04-29T14:18:55.983"
    h["HISTORY"] = "[CALIB] synthetic same calibration"
    for i in (1,2):
        h[f"CTYPE{i}W"] = "WAVE-TAB"
        h[f"CRPIX{i}W"] = 1.
        h[f"CRVAL{i}W"] = 1.
        h[f"CDELT{i}W"] = 1.
        h[f"CUNIT{i}W"] = "um"
        h[f"PV{i}_3W"] = i
        h[f"PS{i}_0W"] = "WCS-WAVE"
        h[f"PS{i}_1W"] = "VALUES"
        h[f"PS{i}_2W"] = "X" if i == 1 else "Y"
    yy,xx = np.indices((29,29))
    # Sources defined in the common sky grid; rotated WCS must reproject them.
    sky = w.all_pix2world(xx,yy,0)
    gx,gy = m.grid(RA,DEC).all_world2pix(*sky,0)
    data = np.full((29,29),.3)
    for x,y in ((6,6),(21,6),(8,20),(21,21)):
        data += 10*np.exp(-((gx-x)**2+(gy-y)**2)/1.8)
    data = data.astype(np.float32)
    data[0,0] = np.nan
    flags = np.full((29,29),1<<21,dtype=np.uint32)
    flags[1,1] |= 1
    if bad:
        flags[14,14] |= 1
    fh = w.to_header()
    fh["MSKN0001"], fh["MSKM0001"] = "SOURCE",1<<21
    fh["MSKN0002"], fh["MSKM0002"] = "BAD",1
    values = np.empty((1,2,2,2),np.float64)
    values[:,:,:,0],values[:,:,:,1] = wave,bandwidth
    wave_hdu = fits.BinTableHDU.from_columns([
        fits.Column(name="X",format="2D",dim="(2)",array=[[1.,29.]]),
        fits.Column(name="Y",format="2D",dim="(2)",array=[[1.,29.]]),
        fits.Column(name="VALUES",format="8D",dim="(2,2,2)",array=values)],name="WCS-WAVE")
    primary = fits.PrimaryHDU()
    primary.header["VERSION"] = "7.0.5"
    fits.HDUList([primary,fits.ImageHDU(data,header=h,name="IMAGE"),
                  fits.ImageHDU(flags,header=fh,name="FLAGS"),wave_hdu]).writeto(path,overwrite=True)


class FrameApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)
        self.products = [product("one"),product("two"),product("three")]
        self.snapshot = self.app.state.epoch_cache.put({"query":{"ra":RA,"dec":DEC},"complete":True,"products":self.products})
        self.ids = [p["product_id"] for p in self.products]
        self.calls = []
        self.options = {}
        def fetch(url,path,cap,**kwargs):
            self.calls.append(url)
            obs = Path(url.split("?")[0]).stem
            opts = self.options.get(obs,{})
            if isinstance(opts,Exception):
                raise opts
            synthetic(path,obs,**opts)
        self.mock = patch.object(m,"fetch_cutout",side_effect=fetch)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def post(self, ids=None, **kwargs):
        return self.client.post("/api/epoch-frames",json={"search_id":self.snapshot["search_id"],"product_ids":self.ids[:2] if ids is None else ids,**kwargs})

    def test_shared_grid_wavelength_normalization_native_mask_and_cache(self):
        self.options["two"] = {"angle":12}
        response = self.post()
        self.assertEqual(response.status_code,200,response.text)
        b = response.json()
        self.assertEqual(b["mode"],"comparable_visualization",b)
        self.assertFalse(b["photometric_series"])
        self.assertEqual(b["counts"]["reprojected"],2)
        self.assertEqual(b["nasa_request_count"],2)
        self.assertEqual(b["grid"]["shape_yx"],[29,29])
        self.assertEqual(b["frames"][0]["normalization"],b["frames"][1]["normalization"])
        f = b["frames"][0]
        self.assertEqual(f["observation_utc"],"2025-04-29T14:18:55.983Z")
        self.assertAlmostEqual(f["target_wavelength_um"],.86)
        artifact = self.client.get(f["data_url"])
        with np.load(io.BytesIO(artifact.content),allow_pickle=False) as a:
            self.assertTrue(np.isnan(a["native_image"][0,0]))
            self.assertFalse(a["native_valid"][1,1])
            self.assertTrue(a["native_valid"][14,14])  # SOURCE is informational
            self.assertEqual(int(a["native_flags"][1,1]),(1<<21)|1)
            self.assertFalse(a["valid_mask"][1,1])
            self.assertTrue(np.isnan(a["aligned_image"][1,1]))
        image = Image.open(io.BytesIO(self.client.get(f["image_url"]).content))
        self.assertEqual(image.mode,"RGBA")
        self.assertEqual(np.asarray(image)[-1,0,3],0)
        # Response URLs are derived without mutating the cached manifest.
        again = self.post().json()
        self.assertEqual(again["sequence_id"],b["sequence_id"])
        self.assertEqual(len(self.calls),2)

    def test_different_wave_or_bandwidth_is_browse(self):
        for opts in ({"wave":.95},{"bandwidth":.03}):
            self.app.state.sequence_cache = m.SequenceCache()
            self.options["two"] = opts
            b = self.post().json()
            self.assertEqual(b["mode"],"observation_browse")
            self.assertFalse(b["wavelength_compatible"])
            self.assertIn("individual",b["normalization"]["policy"])

    def test_partial_failure_keeps_order_and_no_replacement(self):
        self.options["two"] = ValueError("damaged FITS")
        b = self.post(self.ids).json()
        self.assertFalse(b["complete"])
        self.assertEqual([f["product_id"] for f in b["frames"]],self.ids)
        self.assertEqual(b["frames"][1]["status"],"failed")
        self.assertIn("damaged FITS",b["frames"][1]["error"]["message"])
        self.assertIsNone(b["frames"][1]["image_url"])
        self.assertEqual(b["counts"],{"requested":3,"reprojected":2,"failed":1})
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.post(self.ids).json()["sequence_id"],b["sequence_id"])
        self.assertEqual(len(self.calls),3)

    def test_centroid_failure_not_hidden_by_wcs_closure(self):
        with patch.object(m,"residuals",return_value={"status":"residual_exceeds_threshold","matched_stars":3,"max_pixels":1.1}):
            b = self.post().json()
        self.assertEqual(b["mode"],"observation_browse")
        self.assertEqual(b["frames"][1]["geometry"]["status"],"pass")
        self.assertEqual(b["frames"][1]["alignment"]["status"],"failed")
        self.assertEqual(b["frames"][1]["status"],"alignment_unqualified")

    def test_center_quality_rejected(self):
        self.options["two"] = {"bad":True}
        b = self.post().json()
        self.assertFalse(b["frames"][1]["center_valid"])
        self.assertEqual(b["frames"][1]["alignment"]["status"],"failed")
        self.assertEqual(b["mode"],"observation_browse")

    def test_unknown_spectral_and_calibration_not_comparable(self):
        with patch.object(m,"wavelength",side_effect=ValueError("outside control grid")):
            b = self.post().json()
        self.assertEqual(b["mode"],"observation_browse")
        self.assertFalse(b["wavelength_compatible"])
        self.assertEqual(b["frames"][0]["spectral"]["status"],"failed")

    def test_unknown_calibration_and_insufficient_stars(self):
        real_inspect = m.inspect_frame
        def unknown(*args):
            meta, arrays = real_inspect(*args)
            meta["calibration_history"] = []
            return meta, arrays
        with patch.object(m,"inspect_frame",side_effect=unknown):
            b = self.post().json()
        self.assertEqual(b["mode"],"observation_browse")
        self.assertFalse(b["calibration_compatible"])
        self.app.state.sequence_cache = m.SequenceCache()
        with patch.object(m,"peaks",return_value=[]):
            b = self.post().json()
        self.assertEqual(b["frames"][0]["alignment"]["status"],"unverified")
        self.assertEqual(b["mode"],"observation_browse")

    def test_validation_membership_detector_and_url_no_download(self):
        bad = [{"product_ids":[]},{"product_ids":self.ids*2},{"product_ids":[self.ids[0]]*2},
               {"product_ids":[self.ids[0],"f"*64]},{"search_id":"not-an-id"},
               {"access_url":"https://evil.example/a"},{"product_ids":[True,self.ids[0]]}]
        for fields in bad:
            self.assertEqual(self.post(**fields).status_code,422,fields)
        self.products[1]["detector"] = 2
        self.assertEqual(self.post().json()["error"]["code"],"detector_mismatch")
        self.products[1]["detector"] = 1
        self.products[1]["access_url"] = "https://evil.example/a"
        self.assertEqual(self.post().json()["error"]["code"],"invalid_product_source")
        self.assertEqual(self.calls,[])

    def test_expired_search_even_when_sequence_cached_and_restart(self):
        self.assertEqual(self.post().status_code,200)
        with self.app.state.epoch_cache.lock:
            self.app.state.epoch_cache.items.clear()
        self.assertEqual(self.post().status_code,410)
        fresh = TestClient(create_app())
        self.assertEqual(fresh.post("/api/epoch-frames",json={"search_id":self.snapshot["search_id"],"product_ids":self.ids[:2]}).status_code,410)

    def test_search_ttl_and_foreign_product(self):
        self.app.state.epoch_cache.ttl = -1
        old = self.app.state.epoch_cache.put({"query":{},"complete":True,"products":self.products})
        self.assertEqual(self.post(search_id=old["search_id"]).status_code,410)
        foreign = product("foreign")["product_id"]
        self.assertEqual(self.post([self.ids[0],foreign]).status_code,422)
        self.assertEqual(self.calls,[])

    def test_shared_lock_and_release(self):
        lock = self.app.state.preview_lock
        lock.acquire()
        try:
            response = self.post()
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.headers["Retry-After"],"5")
            self.assertEqual(self.calls,[])
        finally:
            lock.release()
        self.post()
        self.assertFalse(lock.locked())

    def test_503_long_retry_after_stops_remaining_slots(self):
        self.options["one"] = urllib.error.HTTPError("https://irsa.ipac.caltech.edu",503,"busy",{"Retry-After":"60"},None)
        b = self.post(self.ids).json()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(b["counts"]["failed"],3)
        self.assertTrue(all(f["error"]["budget_stop_reason"] == "retry_after" for f in b["frames"]))

    def test_503_retry_exhaustion_partial_and_cooldown(self):
        self.options["two"] = urllib.error.HTTPError("https://irsa.ipac.caltech.edu",503,"busy",{"Retry-After":"0"},None)
        with patch.object(m.FrameBudget,"check"):  # avoid real delay; retry counter still real
            b = self.post(self.ids).json()
        self.assertEqual(b["nasa_request_count"],5)
        self.assertEqual(b["frames"][1]["error"]["http_status"],503)
        self.assertEqual(b["frames"][2]["obs_id"],"three")
        self.assertEqual(b["counts"]["reprojected"],2)

    def test_429_and_deadline_or_request_limit_stop_downloads(self):
        self.options["one"] = urllib.error.HTTPError("https://test",429,"slow",{"Retry-After":"60"},None)
        b = self.post(self.ids).json()
        self.assertEqual(b["nasa_request_count"],1)
        self.assertEqual(b["frames"][1]["error"]["budget_stop_reason"],"retry_after")
        self.options.clear()
        for reason in ("deadline","request_limit"):
            self.app.state.sequence_cache = m.SequenceCache()
            budget = m.FrameBudget()
            if reason == "deadline":
                budget.deadline = 0
            else:
                budget.requests = 16
            with patch.object(m,"FrameBudget",return_value=budget):
                b = self.post(self.ids).json()
            self.assertEqual(b["counts"]["failed"],3)
            self.assertEqual(b["frames"][0]["error"]["budget_stop_reason"],reason)
        self.assertEqual(len(self.calls),1)

    def test_cache_expiry_eviction_capacity_and_atomic_artifacts(self):
        self.app.state.sequence_cache = m.SequenceCache(ttl=-1)
        first = self.post().json()
        self.assertEqual(self.client.get(first["frames"][0]["image_url"]).status_code,404)
        self.app.state.sequence_cache = m.SequenceCache(max_entries=1)
        first = self.post().json()
        self.post(list(reversed(self.ids[:2])))
        self.assertEqual(self.client.get(first["frames"][0]["data_url"]).status_code,404)
        self.app.state.sequence_cache = m.SequenceCache(max_bytes=10)
        self.assertEqual(self.post().status_code,503)
        self.assertFalse(self.app.state.preview_lock.locked())


class NumericalAndSafetyTests(unittest.TestCase):
    def test_bounded_download_and_timeout_cleanup(self):
        class Response(io.BytesIO):
            def read1(self, size):
                return self.read(size)
        opener = unittest.mock.Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.urllib.request,"build_opener",return_value=opener):
            path = Path(tmp)/"cutout.fits"
            opener.open.return_value = Response(b"12345")
            with self.assertRaises(ValueError):
                m.fetch_cutout("https://test",path,4,timeout=20,deadline=float("inf"))
            self.assertFalse(path.exists())
            opener.open.return_value = Response(b"12345")
            with self.assertRaises(TimeoutError):
                m.fetch_cutout("https://test",path,10,timeout=20,deadline=0)
            self.assertFalse(path.exists())

    def test_grid_center_direction_bilinear_flags_and_band_boundaries(self):
        w = m.grid(RA,DEC)
        np.testing.assert_allclose(w.all_world2pix([[RA,DEC]],0),[[14,14]],atol=1e-9)
        self.assertLess(w.wcs.cdelt[0],0)
        y,x = np.indices((4,4))
        data = 2*x+3*y
        result,_,_ = m.bilinear(data,np.ones((4,4),bool),[1.25],[1.5])
        self.assertAlmostEqual(float(result[0]),7.)
        result,_,_ = m.bilinear(data,np.ones((4,4),bool),[-.1],[1.5])
        self.assertTrue(np.isnan(result[0]))
        flags = np.array([[1,2],[4,8]],np.uint64)
        self.assertEqual(int(m.propagate_flags(flags,np.array([.5]),np.array([.5]))[0]),15)
        self.assertEqual(int(m.propagate_flags(flags,np.array([np.nan]),np.array([np.nan]))[0]),0)
        a = {"spectral":{"status":"pass"},"target_wavelength_um":1.,"target_bandwidth_um":.02}
        self.assertTrue(m.band_compatible(a,{**a,"target_wavelength_um":1.001}))
        self.assertFalse(m.band_compatible(a,{**a,"target_wavelength_um":1.003}))

    def test_redirect_rejects_untrusted_targets(self):
        redirect = m.ProductRedirect()
        req = urllib.request.Request("https://irsa.ipac.caltech.edu/ibe/data/spherex/a")
        for url in ("http://irsa.ipac.caltech.edu/ibe/data/spherex/a", "https://evil.example/a",
                    "https://irsa.ipac.caltech.edu:443/ibe/data/spherex/a", "https://irsa.ipac.caltech.edu/ibe/data/spherex/%2e%2e/a",
                    "https://irsa.ipac.caltech.edu/other", "https://irsa.ipac.caltech.edu/ibe/data/spherex/allowed"):
            with self.assertRaises(ValueError):
                redirect.redirect_request(req,None,302,"redirect",{},url)

    def test_bad_identity_flags_wcs_and_oversize_rejected(self):
        p = product()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"test.fits"
            for mode in ("identity","flags","size"):
                synthetic(path,"one")
                with fits.open(path,mode="update") as h:
                    if mode == "identity":
                        h["IMAGE"].header["OBSID"] = "other"
                    elif mode == "flags":
                        h["FLAGS"].header["CRVAL1"] += 1
                    else:
                        h["IMAGE"].data = np.zeros((129,129),np.float32)
                with self.assertRaises(ValueError):
                    m.inspect_frame(path,p,RA,DEC,m.grid(RA,DEC))

    def test_local_phase42_replay_pair_and_bad_alignment(self):
        root = ROOT/"research/outputs/phase4-2"
        rows_path = ROOT/"research/outputs/phase4-1/rows.json"
        names = ["2025W18_1B_0162_3","2025W45_1A_0121_1","2025W49_1A_0391_1"]
        paths = [ROOT/"research/outputs/cutout.fits"]+[root/n/"cutout.fits" for n in names[1:]]
        if not rows_path.exists() or not all(p.exists() for p in paths):
            self.skipTest("Optional local Phase 4.2 FITS not present")
        rows = json.loads(rows_path.read_text(encoding="utf-8"))
        selected = [normalize(next(r for r in rows if r["obs_id"] == n and r["detector"] == 1),"spherex_dr1",RA,DEC) for n in names]
        files = {p["access_url"]:path for p,path in zip(selected,paths)}
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        def replay(url,path,cap,**kw):
            shutil.copyfile(files[url.split("?")[0]],path)
        snapshot = {"search_id":"a"*32,"query":{"ra":RA,"dec":DEC}}
        with patch.object(m,"fetch_cutout",side_effect=replay):
            pair, _ = m.create_frames(snapshot,selected[1:])
            three, _ = m.create_frames(snapshot,selected)
        self.assertEqual(pair["mode"],"comparable_visualization",pair)
        self.assertEqual(pair["normalization"]["common_valid_pixels"],650)
        self.assertAlmostEqual(pair["normalization"]["lo"],.237902,places=5)
        self.assertAlmostEqual(pair["normalization"]["hi"],5.704328,places=5)
        self.assertAlmostEqual(pair["frames"][0]["target_wavelength_um"],.861452,places=5)
        self.assertEqual(three["mode"],"observation_browse")
        self.assertEqual(three["frames"][2]["alignment"]["status"],"failed")
        self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])


if __name__ == "__main__":
    unittest.main()

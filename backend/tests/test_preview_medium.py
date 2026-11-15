"""Preview-only angular presets through the real API, with generated FITS."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS, Sip
from astropy.wcs.utils import pixel_to_skycoord
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import service
from backend.app.main import create_app
from backend.app.cache import ImageCache
from backend.app.preview_size import PROFILES, field_from_fits
from backend.app import epoch_frames
from backend.app.nasa_requests import RequestBudget
from research import spherex

BODY = {"ra":359.999,"dec":80.,"radius_deg":.01}
ROW = {"access_url":"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/synthetic.fits", "detector":1}


def generated(path, shape=(64,64), dtype="float32", sip=False, ra=359.999, dec=80., edge=False):
    height,width = shape
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.radesys = "ICRS"
    w.wcs.crval = [ra,dec]
    w.wcs.crpix = [(.75 if edge else (width+1)/2), (height+1)/2]
    theta = np.deg2rad(23)
    w.wcs.cd = 6.15/3600*np.array([[-np.cos(theta),np.sin(theta)],[np.sin(theta),np.cos(theta)]])
    if sip:
        a,b = np.zeros((4,4)),np.zeros((4,4))
        a[2,0],b[0,2],a[1,1] = 2e-5,-3e-5,1e-5
        w.sip = Sip(a,b,None,None,w.wcs.crpix)
        w.wcs.ctype = ["RA---TAN-SIP","DEC--TAN-SIP"]
    h = w.to_header(relax=True)
    h["BUNIT"],h["DETECTOR"] = "MJy/sr",1
    rng = np.random.default_rng(20261115)
    data = rng.normal(-3,10,shape).astype(dtype)  # high entropy, including negatives
    flags = rng.choice(np.array([0,1<<21,1<<6],dtype=np.uint32),shape,p=[.45,.45,.1])
    cx,cy = (0 if edge else width//2),height//2
    flags[cy,cx] = 0
    if data.dtype.kind == "f": data[-1,:3] = [np.nan,np.inf,-np.inf]
    else:
        h["BLANK"] = -32768
        data[-1,0] = -32768
    data[cy,cx] = 5
    fits.HDUList([fits.PrimaryHDU(),fits.ImageHDU(data,header=h,name="IMAGE"),
                  fits.ImageHDU(flags,header=w.to_header(relax=True),name="FLAGS")]).writeto(path,overwrite=True)
    return w


def synthetic_request(client, body, **fixture_options):
    """Only query/fetch are replaced; URL, renderer, WCS, JSON and cache are real."""
    urls = []
    def fetch(url,path,cap,events,**kwargs):
        assert cap == 32*1024*1024
        urls.append(url)
        size = parse_qs(urlsplit(url).query)["size"][0]
        shape = (29,29) if size == "3arcmin" else (64,64)
        generated(path, **{"shape":shape, "ra":body["ra"], "dec":body["dec"], **fixture_options})
    with patch.object(spherex,"query_images",return_value=([ROW],{})) as query, \
         patch.object(spherex,"fetch",side_effect=fetch), \
         patch.object(spherex,"render_cutout",wraps=spherex.render_cutout) as render:
        response = client.post("/api/preview",json=body)
        return response,urls,query.call_args,render.call_args


class PreviewMediumTests(unittest.TestCase):
    def test_legacy_small_medium_url_renderer_search_and_https_cache(self):
        app = create_app()
        with TestClient(app,base_url="https://offline.example") as client:
            for profile in (None,"small","medium"):
                body = {**BODY,**({} if profile is None else {"cutout_profile":profile})}
                response,urls,query,render = synthetic_request(client,body)
                self.assertEqual(response.status_code,200,response.text)
                m = response.json()["metadata"]
                expected,arcmin = PROFILES[profile or "small"]
                self.assertEqual(parse_qs(urlsplit(urls[0]).query)["size"],[expected])
                self.assertEqual(render.kwargs["cutout_size"],expected)
                self.assertEqual(m["cutout_size"],expected)
                self.assertEqual(m["requested_cutout_arcmin"],arcmin)
                self.assertEqual(m["cutout_profile"],profile or "small")
                self.assertEqual(query.args[:3],(BODY["ra"],BODY["dec"],BODY["radius_deg"]))
                self.assertNotIn("cutout_profile",query.kwargs)
                self.assertEqual(m["actual_shape_yx"],m["display"]["shape"])
                self.assertTrue(m["wcs_field"]["available"])
                self.assertEqual(response.headers["cache-control"],"no-store")
                for key in ("image_url","inverted_image_url"):
                    self.assertTrue(response.json()[key].startswith("https://offline.example/"))
                    png = client.get(response.json()[key])
                    self.assertEqual(png.headers["cache-control"],"no-store")
                    image = Image.open(io.BytesIO(png.content)).convert("RGBA")
                    self.assertEqual(list(reversed(image.size)),m["actual_shape_yx"])
                    self.assertEqual(image.getpixel((0,0))[3],0)

    def test_invalid_sizes_never_call_service_and_epoch_has_no_profile(self):
        client = TestClient(create_app())
        with patch("backend.app.main.create_preview") as create:
            for value in ("large","128","256","6.5arcmin","MEDIUM","",None,64,True,{},[]):
                self.assertEqual(client.post("/api/preview",json={**BODY,"cutout_profile":value}).status_code,422)
            for name in ("cutout_size","requested_cutout_arcmin","size"):
                self.assertEqual(client.post("/api/preview",json={**BODY,name:6.5}).status_code,422)
            create.assert_not_called()
        with patch.object(spherex,"query_images") as query:
            with self.assertRaises(service.PreviewError): service.create_preview(**BODY,cutout_profile="large")
            query.assert_not_called()
        self.assertEqual(epoch_frames.SIZE,29)
        self.assertEqual(client.post("/api/epochs/search",json={**BODY,"cutout_profile":"medium"}).status_code,422)
        schema = client.get("/openapi.json").json()["components"]["schemas"]["PreviewRequest"]
        self.assertEqual(schema["properties"]["cutout_profile"]["enum"],["small","medium"])
        self.assertEqual(schema["properties"]["cutout_profile"]["default"],"small")

    def test_larger_sip_ra_wrap_poles_dtype_crop_masks_and_span(self):
        client = TestClient(create_app())
        variants = [((64,64),"float32",True,359.999,0.,False),
                    ((63,65),"float64",True,359.999,85.,False),
                    ((65,64),"int16",False,.001,-85.,False),
                    ((32,61),"int32",True,359.999,80.,True)]
        for shape,dtype,sip,ra,dec,edge in variants:
            with self.subTest(shape=shape,dtype=dtype,dec=dec):
                body = {**BODY,"ra":ra,"dec":dec,"cutout_profile":"medium"}
                response,_,_,_ = synthetic_request(client,body,shape=shape,dtype=dtype,sip=sip,edge=edge)
                self.assertEqual(response.status_code,200,response.text)
                m = response.json()["metadata"]
                self.assertEqual(m["actual_shape_yx"],list(shape))
                d = m["display"]
                self.assertTrue(d["available"])
                self.assertEqual(sum(d["histogram"]["counts"]),sum(d["valid"]))
                self.assertIsNone(d["values"][-shape[1]])
                self.assertLess(d["min"],0)
                field = m["wcs_field"]
                self.assertTrue(field["available"])
                for direction,expected_axis in (("horizontal",shape[1]),("vertical",shape[0])):
                    samples = field[direction+"_samples"]
                    sky = SkyCoord(samples["icrs_ra_dec_deg"],unit="deg",frame="icrs")
                    expected = float(sky[:-1].separation(sky[1:]).arcmin.sum())
                    self.assertAlmostEqual(field[direction+"_arcmin"],expected,places=10)
                    self.assertAlmostEqual(expected,expected_axis*6.15/60,delta=.03)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory)/"reference.fits"
                    w = generated(path,shape,dtype,sip,ra,dec,edge)
                    for direction in ("horizontal","vertical"):
                        sample = field[direction+"_samples"]
                        xy = np.array(sample["pixel_xy"])
                        truth = pixel_to_skycoord(xy[:,0],xy[:,1],w,origin=0,mode="all")
                        actual = SkyCoord(sample["icrs_ra_dec_deg"],unit="deg")
                        self.assertLess(float(actual.separation(truth).arcsec.max()),1e-6)
                    if sip:
                        linear = WCS(w.to_header(relax=True)).celestial
                        linear.sip = None
                        plain = pixel_to_skycoord(xy[:,0],xy[:,1],linear,origin=0,mode="all")
                        self.assertGreater(float(plain.separation(truth).arcsec.max()),.01)
                if dec == 0.:
                    ras = np.array(field["horizontal_samples"]["icrs_ra_dec_deg"])[:,0]
                    self.assertGreater(float(np.ptp(ras)),359.)
                    self.assertLess(field["horizontal_arcmin"],7.)

    def test_field_unavailable_does_not_invent_span(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"bad.fits"
            generated(path)
            with fits.open(path,mode="update") as hdul: del hdul["IMAGE"].header["CTYPE1"]
            self.assertFalse(field_from_fits(path)["available"])
            self.assertNotIn("horizontal_arcmin",field_from_fits(path))

    def test_high_entropy_cache_capacity_expiry_and_profile_isolation(self):
        app = create_app()
        client = TestClient(app)
        a,_,_,_ = synthetic_request(client,{**BODY,"cutout_profile":"medium"},dtype="float64")
        a = a.json()
        black = client.get(a["image_url"]).content
        white = client.get(a["inverted_image_url"]).content
        self.assertGreater(len(black)+len(white),6000)
        cache = ImageCache(max_bytes=len(black)+len(white))
        app.state.image_cache = cache
        one = cache.put(black,white)
        two = cache.put(black,white)
        self.assertIsNone(cache.get(one))
        self.assertEqual(cache.get(two),black)
        self.assertEqual(client.get(f"/api/images/{one}.png").status_code,404)
        with patch("backend.app.cache.time.monotonic",return_value=float("inf")):
            self.assertIsNone(cache.get(two))
        app.state.image_cache = ImageCache()
        small,_,_,_ = synthetic_request(client,BODY)
        medium,_,_,_ = synthetic_request(client,{**BODY,"cutout_profile":"medium"})
        self.assertNotEqual(small.json()["key"],medium.json()["key"])
        self.assertEqual(Image.open(io.BytesIO(client.get(small.json()["image_url"]).content)).size,(29,29))
        self.assertEqual(Image.open(io.BytesIO(client.get(medium.json()["image_url"]).content)).size,(64,64))

    def test_existing_limits_and_busy_lock_unchanged(self):
        self.assertEqual((spherex.LIMIT,spherex.MAX_IMAGE_PIXELS,spherex.MAX_CLIENT_PIXELS,spherex.MAX_CLIENT_BYTES),
                         (32*1024**2,262144,65536,4*1024**2))
        budget = RequestBudget()
        self.assertGreater(budget.deadline,0)
        app = create_app()
        app.state.preview_lock.acquire()
        try:
            with patch("backend.app.main.create_preview") as create:
                response = TestClient(app).post("/api/preview",json={**BODY,"cutout_profile":"medium"})
                self.assertEqual(response.status_code,503)
                create.assert_not_called()
        finally: app.state.preview_lock.release()


if __name__ == "__main__": unittest.main()

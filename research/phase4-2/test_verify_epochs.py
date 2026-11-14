"""Offline numerical and request-safety checks for the research experiment."""
import importlib.util
import tempfile
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np
from astropy.wcs import WCS

spec=importlib.util.spec_from_file_location('experiment',Path(__file__).with_name('verify_epochs.py'))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ResearchChecks(unittest.TestCase):
    def test_bilinear_plane_and_invalid_support(self):
        y,x=np.indices((5,5));data=2*x+3*y
        valid=np.ones((5,5),bool)
        result,_,_=m.bilinear(data,valid,np.array([1.25]),np.array([2.5]))
        self.assertAlmostEqual(float(result[0]),10)
        valid[2,1]=False
        result,weight,_=m.bilinear(data,valid,np.array([1.25]),np.array([2.5]))
        self.assertTrue(np.isnan(result[0]))
        self.assertLess(weight[0],1)
        # A neighbor with zero interpolation weight must not invalidate a centre.
        valid[:]=True;valid[2,2]=False
        self.assertTrue(np.isfinite(m.bilinear(data,valid,[1],[2])[0][0]))

    def test_no_edge_extrapolation(self):
        data=np.ones((4,4))
        result,_,geometric=m.bilinear(data,np.ones_like(data,bool),[-.1,3.1],[2,2])
        self.assertTrue(np.isnan(result).all())
        self.assertTrue((geometric<1).all())

    def test_grid_orientation_and_center(self):
        w=m.grid()
        np.testing.assert_allclose(w.all_world2pix([[m.RA,m.DEC]],0),[[14,14]],atol=1e-8)
        sky=w.all_pix2world([[14,14],[15,14],[14,15]],0)
        self.assertLess(sky[1,0],sky[0,0])
        self.assertGreater(sky[2,1],sky[0,1])

    def test_rotated_gaussian_reprojects_to_fixed_sky_position(self):
        native=m.grid()
        angle=np.deg2rad(29)
        native.wcs.pc=[[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]]
        native.wcs.crpix=[15.3,14.7]
        yy,xx=np.indices((29,29),dtype=float)
        ra,dec=m.grid().all_pix2world([[11.2,16.1]],0)[0]
        cx,cy=native.all_world2pix([[ra,dec]],0)[0]
        source=np.exp(-((xx-cx)**2+(yy-cy)**2)/(2*1.2**2))
        r,d=m.grid().all_pix2world(xx,yy,0)
        sx,sy=native.all_world2pix(r,d,0)
        aligned,_,_=m.bilinear(source,np.ones_like(source,bool),sx,sy)
        detected=m.peaks(aligned)
        self.assertTrue(detected)
        self.assertLess(np.hypot(detected[0][0]-11.2,detected[0][1]-16.1),.2)

    def test_flags_are_or_of_contributing_pixels(self):
        flags=np.array([[1,2],[4,8]],dtype=np.uint64)
        self.assertEqual(int(m.propagate_flags(flags,np.array([.5]),np.array([.5]))[0]),15)
        self.assertEqual(int(m.propagate_flags(flags,np.array([0.]),np.array([0.]))[0]),1)

    def test_wave_uses_alternate_w_origin_not_sip(self):
        # Linear control values make an independent exact interpolation oracle.
        yy,xx=np.indices((2,2))
        values=np.stack([1+xx*.1+yy*.2,np.full((2,2),.02)],axis=-1)
        table={'X':np.array([[1,11]]),'Y':np.array([[1,11]]),'VALUES':values[None]}
        header={'CRPIX1W':-4.,'CRPIX2W':-9.,'CRVAL1W':1.,'CRVAL2W':1.,
                'CUNIT1W':'um','CUNIT2W':'um','A_ORDER':2,'A_2_0':999}
        result=m.wavelength(header,table,0,0)
        np.testing.assert_allclose(result['table_xy_fits'],[6,11])
        self.assertAlmostEqual(float(result['wavelength_um']),1.25)
        with self.assertRaises(ValueError):m.wavelength(header,table,0,1)

    def test_empirical_residual_needs_three_real_matches(self):
        a=[[3,3,10],[9,9,20],[15,15,30]]
        b=[[3.1,3.1,10],[9.2,9.1,20],[15.1,15,30]]
        self.assertEqual(m.residuals(a,b)['status'],'pass')
        self.assertEqual(m.residuals(a[:1],b[:1])['status'],'insufficient_stars')

    def test_retry_after_stops_next_request_and_logs_429(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'requests.json';budget=m.LoggedBudget(ledger)
            calls=[]
            def unavailable(url,path,cap,events,**kwargs):
                calls.append(url);events.append({'url':url,'status':429,'error':'test'})
                raise urllib.error.HTTPError(url,429,'slow down',{'Retry-After':'60'},None)
            with patch.object(m.spherex,'fetch',unavailable):
                with self.assertRaises(Exception):budget.fetch_one('https://test',Path(tmp)/'x','test')
            self.assertEqual(len(calls),1)
            self.assertEqual(budget.events[0]['status'],429)
            self.assertEqual(budget.stop_reason,'retry_after')
            self.assertTrue(ledger.exists())


if __name__=='__main__':
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout,verbosity=2))

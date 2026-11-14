"""Bounded, independent Phase 4.2 experiment; offline unless --download is given.

Run from repo root: research/.venv/Scripts/python.exe research/phase4-2/verify_epochs.py
Does not query SIA, run the preview API, or change any Phase 1-3 files.
"""
import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psutil
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import skycoord_to_pixel, proj_plane_pixel_scales
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research import spherex
from backend.app.nasa_requests import (
    RequestBudget, MAX_ATTEMPTS, REQUEST_SECONDS, retry_after_seconds,
)

RA, DEC, SCALE, SIZE = 127.69444, -39.17760, 6.15, 29
TARGET = SkyCoord(RA, DEC, unit="deg", frame="icrs")
OUT = ROOT / "research/outputs/phase4-2"
REUSE_ID = "2025W18_1B_0162_3"
NEW_IDS = ["2025W21_1B_0582_1", "2025W45_1A_0121_1",
           "2025W49_1A_0391_1", "2026W21_1A_0480_1"]


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return safe(value.tolist())
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save_json(path, value):
    path.write_text(json.dumps(safe(value), ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def grid():
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.radesys = "ICRS"
    w.wcs.crval = [RA, DEC]
    w.wcs.crpix = [(SIZE + 1) / 2] * 2
    w.wcs.cdelt = [-SCALE / 3600, SCALE / 3600]
    return w


def bilinear(data, good, x, y):
    """Require complete geometric AND valid-pixel support; never fill holes."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    finite_xy = np.isfinite(x) & np.isfinite(y)
    ix = np.floor(np.where(finite_xy, x, 0)).astype(int)
    iy = np.floor(np.where(finite_xy, y, 0)).astype(int)
    fx, fy = x - ix, y - iy
    result, valid_weight, geom_weight = np.zeros(x.shape), np.zeros(x.shape), np.zeros(x.shape)
    for dx, dy, weight in [(0, 0, (1-fx)*(1-fy)), (1, 0, fx*(1-fy)),
                           (0, 1, (1-fx)*fy), (1, 1, fx*fy)]:
        xx, yy = ix + dx, iy + dy
        inside = finite_xy & (xx >= 0) & (xx < data.shape[1]) & (yy >= 0) & (yy < data.shape[0])
        xx, yy = np.clip(xx, 0, data.shape[1]-1), np.clip(yy, 0, data.shape[0]-1)
        ok = inside & good[yy, xx]
        geom_weight += np.where(inside, weight, 0)
        valid_weight += np.where(ok, weight, 0)
        result += np.where(ok, data[yy, xx], 0) * np.where(ok, weight, 0)
    usable = (geom_weight >= 1-1e-6) & (valid_weight >= 1-1e-6)
    return np.where(usable, result, np.nan).astype(np.float32), valid_weight, geom_weight


def propagate_flags(flags, x, y):
    """Conservative bitwise OR of all contributing interpolation pixels."""
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    out = np.zeros(x.shape, dtype=np.uint64)
    for dx, dy, wt in [(0,0,(1-(x-ix))*(1-(y-iy))), (1,0,(x-ix)*(1-(y-iy))),
                       (0,1,(1-(x-ix))*(y-iy)), (1,1,(x-ix)*(y-iy))]:
        xx, yy = ix+dx, iy+dy
        inside=(xx>=0)&(xx<flags.shape[1])&(yy>=0)&(yy<flags.shape[0])&(wt>1e-8)
        clipped = flags[np.clip(yy,0,flags.shape[0]-1),np.clip(xx,0,flags.shape[1]-1)]
        out |= np.where(inside, clipped, np.uint64(0))
    return out


def wavelength(header, table, x, y):
    """Alternate W linear transform -> FITS -TAB control grid, no spatial SIP."""
    pixel = np.array([x+1, y+1])
    crpix = np.array([header[f"CRPIX{i}W"] for i in (1,2)])
    crval = np.array([header[f"CRVAL{i}W"] for i in (1,2)])
    cdelt = np.array([header.get(f"CDELT{i}W",1) for i in (1,2)])
    pc = np.array([[header.get(f"PC{i}_{j}W",int(i==j)) for j in (1,2)] for i in (1,2)])
    coord = crval + cdelt * (pc @ (pixel-crpix))
    xs, ys, values = [np.asarray(table[n][0]) for n in ("X","Y","VALUES")]
    if values.shape != (len(ys),len(xs),2) or not (np.diff(xs)>0).all() or not (np.diff(ys)>0).all():
        raise ValueError("Unsupported spectral -TAB table layout")
    if not (xs[0]<=coord[0]<=xs[-1] and ys[0]<=coord[1]<=ys[-1]):
        raise ValueError("Target outside wavelength control grid; no extrapolation")
    i=min(len(xs)-2,max(0,int(np.searchsorted(xs,coord[0],side="right")-1)))
    j=min(len(ys)-2,max(0,int(np.searchsorted(ys,coord[1],side="right")-1)))
    fx,fy=(coord[0]-xs[i])/(xs[i+1]-xs[i]),(coord[1]-ys[j])/(ys[j+1]-ys[j])
    val=(1-fx)*(1-fy)*values[j,i]+fx*(1-fy)*values[j,i+1]+(1-fx)*fy*values[j+1,i]+fx*fy*values[j+1,i+1]
    val=np.array([val[k]*u.Unit(header[f"CUNIT{k+1}W"]).to(u.um) for k in (0,1)])
    if not np.isfinite(val).all() or (val<=0).any():
        raise ValueError("Invalid wavelength/bandwidth")
    return {"wavelength_um":val[0],"bandwidth_um":val[1],"table_xy_fits":coord,
            "method":"bilinear WCS-WAVE; alternate W linear transform; no spatial SIP",
            "scope":"visualization approximation, not precision photometry"}


def peaks(data):
    """Small independent image-centroid diagnostic, not a source catalog."""
    good=np.isfinite(data)
    if good.sum()<30:
        return []
    median=np.median(data[good]); noise=1.4826*np.median(np.abs(data[good]-median))
    candidates=[]
    for y in range(3,data.shape[0]-3):
        for x in range(3,data.shape[1]-3):
            patch=data[y-2:y+3,x-2:x+3]
            if not np.isfinite(patch).all() or data[y,x]<median+5*max(noise,1e-6):
                continue
            if data[y,x]<np.max(data[y-1:y+2,x-1:x+2]):
                continue
            background=np.median(np.concatenate([patch[0],patch[-1],patch[1:-1,0],patch[1:-1,-1]]))
            weight=np.maximum(patch-background,0)
            if weight.sum()<=0:
                continue
            yy,xx=np.indices(patch.shape)
            candidates.append([float((weight*(xx+x-2)).sum()/weight.sum()),
                               float((weight*(yy+y-2)).sum()/weight.sum()),float(data[y,x]-median)])
    selected=[]
    for candidate in sorted(candidates,key=lambda v:-v[2]):
        if all(np.hypot(candidate[0]-p[0],candidate[1]-p[1])>=3 for p in selected):
            selected.append(candidate)
    return selected[:20]


def residuals(reference, moving):
    a,b=np.asarray(reference,float),np.asarray(moving,float)
    if not len(a) or not len(b):
        return {"status":"insufficient_stars","matched_stars":0,"median_pixels":None,"matches":[]}
    distances=np.linalg.norm(a[:,None,:2]-b[None,:,:2],axis=2)
    matches=[]
    for i,j in enumerate(np.argmin(distances,axis=1)):
        if np.argmin(distances[:,j])==i and distances[i,j]<=1.5:
            matches.append({"reference_xy":a[i,:2],"moving_xy":b[j,:2],"distance_pixels":distances[i,j]})
    ds=[m["distance_pixels"] for m in matches]
    median=float(np.median(ds)) if ds else None
    return {"status":("insufficient_stars" if len(ds)<3 else "pass" if median<0.5 and max(ds)<1 else "residual_exceeds_threshold"),
            "matched_stars":len(ds),"median_pixels":median,"max_pixels":max(ds) if ds else None,
            "median_arcsec":median*SCALE if median is not None else None,"matches":matches,
            "method":"independent 5x5 background-subtracted centroids; mutual nearest <=1.5px; no fitted shift",
            "caveat":"cross-wavelength morphology and blends can bias centroids"}


class LoggedBudget(RequestBudget):
    """Existing limits plus 429 and durable UTC attempt log, research only."""
    def __init__(self, ledger):
        super().__init__()
        self.ledger=ledger
        self.events=json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
        self.requests=len(self.events)  # Never silently reset request count on rerun.
        for event in self.events:
            if event.get("retry_not_before_utc"):
                delay=datetime.fromisoformat(event["retry_not_before_utc"]).timestamp()-time.time()
                self.not_before=max(self.not_before,time.monotonic()+max(0,delay))

    def fetch_one(self,url,path,obs_id):
        existing_urls={e['url'] for e in self.events}
        if url not in existing_urls and len(existing_urls)>=5:
            raise RuntimeError("Five distinct new Cutouts already attempted")
        old_attempts=sum(e['url']==url for e in self.events)
        for attempt in range(old_attempts,MAX_ATTEMPTS):
            self.check()
            self.requests+=1
            events=[]
            started_utc=utc()
            try:
                spherex.fetch(url,path,spherex.LIMIT,events,
                              timeout=min(REQUEST_SECONDS,self.deadline-time.monotonic()),deadline=self.deadline)
                return
            except urllib.error.HTTPError as exc:
                if exc.code not in (429,503):
                    raise
                wait=max(2**attempt,retry_after_seconds(exc.headers.get('Retry-After')))
                self.not_before=time.monotonic()+wait
                events[-1]['retry_after']=exc.headers.get('Retry-After')
                events[-1]['retry_not_before_utc']=datetime.fromtimestamp(time.time()+wait,timezone.utc).isoformat()
                if attempt+1==MAX_ATTEMPTS:
                    raise
            finally:
                for event in events:
                    event.update(obs_id=obs_id,started_utc=started_utc,finished_utc=utc(),attempt=attempt+1)
                self.events.extend(events)
                save_json(self.ledger,self.events)
        raise RuntimeError("Per-URL attempt budget exhausted")


def inspect(path,row,destination):
    result={"obs_id":row['obs_id'],"source_metadata":row,"path":str(path.relative_to(ROOT)),
            "sha256":digest(path),"bytes":path.stat().st_size,"status":"failed"}
    with fits.open(path,memmap=False,lazy_load_hdus=True) as hdul:
        header=hdul['IMAGE'].header
        if header.get('OBSID')!=row['obs_id'] or int(header.get('DETECTOR',0))!=1:
            raise ValueError("FITS identity/detector does not match selected metadata")
        data=np.array(hdul['IMAGE'].data,dtype=np.float32)
        if data.ndim!=2 or max(data.shape)>128:
            raise ValueError("Not a small spatial Cutout")
        if not u.Unit(header['BUNIT']).is_equivalent(u.MJy/u.sr):
            raise ValueError("Unexpected brightness unit")
        spatial=WCS(header,fobj=hdul,key=' ').celestial
        if spatial.wcs.radesys!='ICRS':
            raise ValueError("Unexpected celestial frame")
        x,y=map(float,skycoord_to_pixel(TARGET,spatial,origin=0,mode='all'))
        inside=np.isfinite([x,y]).all() and -.5<=x<data.shape[1]-.5 and -.5<=y<data.shape[0]-.5
        flags=np.asarray(hdul['FLAGS'].data,dtype=np.uint64)
        if flags.shape!=data.shape:
            raise ValueError("FLAGS shape mismatch")
        flag_header=hdul['FLAGS'].header
        flag_wcs=WCS(flag_header,fobj=hdul,key=' ').celestial
        sample=np.array([[0,0],[data.shape[1]-1,0],[0,data.shape[0]-1],[x,y]])
        flag_sky=flag_wcs.all_pix2world(sample,0)
        image_sky=spatial.all_pix2world(sample,0)
        flag_separation=SkyCoord(flag_sky,unit='deg').separation(SkyCoord(image_sky,unit='deg')).arcsec
        if float(np.max(flag_separation))>1e-4:
            raise ValueError('FLAGS celestial WCS is not co-registered with IMAGE')
        flag_definitions={k[4:]:{"name":str(v).strip(),"mask":int(flag_header['MSKM'+k[4:]]),
                                "description":flag_header.get('MSKD'+k[4:])}
                          for k,v in flag_header.items() if k.startswith('MSKN')}
        if not flag_definitions:
            raise ValueError("Missing FLAGS definitions")
        informational=sum(v['mask'] for v in flag_definitions.values() if v['name'] in ('SOURCE','FULLSAMPLE'))
        rejected_bits=flags & np.uint64(((1<<64)-1)^informational)
        good=np.isfinite(data)&(rejected_bits==0)
        ix,iy=int(np.floor(x+.5)),int(np.floor(y+.5))
        center_finite=bool(inside and np.isfinite(data[iy,ix]))
        center_quality=bool(inside and good[iy,ix])
        result.update(date_obs=header.get('DATE-OBS'),mjd_obs=header.get('MJD-OBS'),
                      detector=header.get('DETECTOR'),pipeline_version=hdul[0].header.get('VERSION'),
                      bunit=header['BUNIT'],native_shape_yx=data.shape,target_native_xy=[x,y],
                      center_inside=bool(inside),center_finite=center_finite,center_quality_accepted=center_quality,
                      center_flags=int(flags[iy,ix]) if inside else None,
                      finite_fraction=float(np.isfinite(data).mean()),quality_fraction=float(good.mean()),
                      flags={"definitions":flag_definitions,"policy":"reject every bit except SOURCE and FULLSAMPLE; unknown bits rejected",
                             "wcs_max_separation_arcsec":float(np.max(flag_separation)),
                             "counts":{v['name']:int(((flags&v['mask'])!=0).sum()) for v in flag_definitions.values()}},
                      native_projection=list(spatial.wcs.ctype),
                      projection_plane_scale_arcsec=proj_plane_pixel_scales(spatial)*3600,
                      calibration_history=[str(v) for k,v in header.items() if k=='HISTORY' and '[CALIB]' in str(v)])
        try:
            result['spectral']=wavelength(header,hdul['WCS-WAVE'].data,x,y)
            # Core WCS bypasses spatial SIP inherited by the alternate W constructor.
            # Manual interpolation is cross-checked against wcslib -TAB, not all_pix2world.
            from astropy import log
            old=log.level
            try:
                log.setLevel('ERROR')
                spectral=WCS(header,fobj=hdul,key='W')
            finally:
                log.setLevel(old)
            check=spectral.wcs_pix2world([[x,y]],0)[0]
            manual=np.array([result['spectral']['wavelength_um'],result['spectral']['bandwidth_um']])
            check=np.array([check[i]*u.Unit(header[f'CUNIT{i+1}W']).to(u.um) for i in (0,1)])
            error=float(np.max(np.abs(check-manual)))
            result['spectral'].update(wcslib_core_check_um=check,max_check_error_um=error,status='pass' if error<1e-6 else 'crosscheck_failed')
        except Exception as exc:
            result['spectral']={"status":"failed","reason":repr(exc)}
        yy,xx=np.indices((SIZE,SIZE),dtype=float)
        target_grid=grid()
        ra,dec=target_grid.all_pix2world(xx,yy,0)
        sx,sy=spatial.all_world2pix(ra,dec,0,tolerance=1e-8,maxiter=100,adaptive=True)
        aligned,weight,geometric=bilinear(data,good,sx,sy)
        propagated=propagate_flags(flags,sx,sy)
        # Round-trip closure is mathematical consistency, not empirical astrometry.
        ra2,dec2=spatial.all_pix2world(sx,sy,0)
        gx,gy=target_grid.all_world2pix(ra2,dec2,0)
        closure=np.hypot(gx-xx,gy-yy)
        center=SIZE//2
        local_sky=SkyCoord(spatial.all_pix2world([[x,y],[x+1,y],[x,y+1]],0),unit='deg')
        result.update(target_grid_xy=target_grid.all_world2pix([[RA,DEC]],0)[0],
                      target_local_pixel_scale_arcsec=local_sky[0].separation(local_sky[1:]).arcsec,
                      geometry_roundtrip_max_pixels=float(np.nanmax(closure)),
                      geometry_roundtrip_status='pass' if np.isfinite(closure).all() and np.max(closure)<1e-5 else 'failed',
                      aligned_valid_fraction=float(np.isfinite(aligned).mean()),
                      geometric_covered_fraction=float((geometric>=1-1e-6).mean()),
                      aligned_center_valid=bool(np.isfinite(aligned[center,center])),
                      flags_center_or=int(propagated[center,center]),
                      detected_centroids=peaks(aligned),
                      status='reprojected' if center_finite and center_quality and np.isfinite(aligned[center,center]) else 'center_validation_failed')
        hdr=target_grid.to_header()
        hdr['BUNIT']=header['BUNIT'];hdr['OBSID']=row['obs_id'];hdr['DATE-OBS']=header.get('DATE-OBS','')
        fits.HDUList([fits.PrimaryHDU(),fits.ImageHDU(aligned,header=hdr,name='IMAGE'),
                      fits.ImageHDU(weight.astype(np.float32),name='VALID_WEIGHT'),
                      fits.ImageHDU((np.isfinite(aligned)).astype(np.uint8),name='VALID_MASK'),
                      fits.ImageHDU(propagated,name='FLAGS_OR')]).writeto(destination/'aligned.fits',overwrite=True)
        np.savez_compressed(destination/'arrays.npz',native=data,native_good=good,aligned=aligned,
                            valid_weight=weight,geometric_weight=geometric,flags_or=propagated)
        return result,data,good,aligned


def display(data,lo,hi):
    good=np.isfinite(data)
    scaled=np.arcsinh(10*np.clip(np.nan_to_num((data-lo)/max(hi-lo,1e-8)),0,1))/np.arcsinh(10)
    rgb=np.repeat(np.rint(scaled[...,None]*255).astype(np.uint8),3,axis=2)
    rgb[~good]=[110,35,100]
    return Image.fromarray(np.flipud(rgb)).resize((232,232),Image.Resampling.NEAREST)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true',help='Fetch only four selected missing Cutouts under durable budget')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    rows=json.loads((ROOT/'research/outputs/phase4-1/rows.json').read_text(encoding='utf-8'))
    selected=[next(r for r in rows if r['obs_id']==oid and r['detector']==1) for oid in [REUSE_ID]+NEW_IDS]
    save_json(OUT/'selection.json',{"created_utc":utc(),"metadata_sha256":digest(ROOT/'research/outputs/phase4-1/rows.json'),
              "policy":"reuse Phase 1, then highest footprint margin in four date bins; no fresh SIA queries","rows":selected})
    budget=LoggedBudget(OUT/'requests.json') if args.download else None
    prior_events=json.loads((OUT/'requests.json').read_text(encoding='utf-8')) if (OUT/'requests.json').exists() else []
    results=[];images=[];start=time.monotonic()
    for row in selected:
        directory=OUT/row['obs_id'];directory.mkdir(exist_ok=True)
        path=ROOT/'research/outputs/cutout.fits' if row['obs_id']==REUSE_ID else directory/'cutout.fits'
        source='phase1_reused' if row['obs_id']==REUSE_ID else 'phase4_2_cache'
        failure=None
        if not path.exists() and args.download:
            try:
                budget.fetch_one(spherex.build_cutout_url(row,RA,DEC),path,row['obs_id'])
                source='new_cutout'
            except Exception as exc:
                failure=repr(exc)
        if path.exists():
            try:
                result,native,good,aligned=inspect(path,row,directory)
                result['file_source']=source
                results.append(result);images.append((result,native,good,aligned,directory))
            except Exception as exc:
                results.append({"obs_id":row['obs_id'],"status":"validation_failed","reason":repr(exc),"path":str(path)})
        else:
            previous=[e for e in prior_events if e.get('obs_id')==row['obs_id']]
            if failure is None and previous:
                failure=previous[-1].get('error','Previous request did not produce a retained Cutout')
            results.append({"obs_id":row['obs_id'],"status":"download_failed" if failure else 'not_downloaded',"reason":failure})
        save_json(OUT/'progress.json',results)
    reference=next((r for r in results if r['obs_id']==REUSE_ID and 'detected_centroids' in r),None)
    for result in results:
        if 'detected_centroids' not in result:
            continue
        result['empirical_alignment']={"status":"reference_frame","matched_stars":None} if result is reference else (
            residuals(reference['detected_centroids'],result['detected_centroids']) if reference else {"status":"reference_unavailable"})
    # Pairwise spectral compatibility is an engineering screen, not proof of identical passbands.
    pairs=[]
    for i,a in enumerate(results):
        for b in results[i+1:]:
            sa,sb=a.get('spectral',{}),b.get('spectral',{})
            pair={"obs_ids":[a['obs_id'],b['obs_id']],"status":"unverified"}
            if sa.get('status')==sb.get('status')=='pass':
                delta=abs(sa['wavelength_um']-sb['wavelength_um'])
                narrow=min(sa['bandwidth_um'],sb['bandwidth_um'])
                width_delta=abs(sa['bandwidth_um']-sb['bandwidth_um'])/narrow
                # 0.1 of the narrower bandwidth, max 10% bandwidth mismatch.
                match=delta<=0.1*narrow and width_delta<=0.1
                pair.update(delta_wavelength_um=delta,delta_over_narrower_bandwidth=delta/narrow,
                            relative_bandwidth_difference=width_delta,
                            status='candidate_visual_band_match' if match else 'different_bandpass')
                if 'detected_centroids' in a and 'detected_centroids' in b:
                    pair['empirical_alignment']=residuals(a['detected_centroids'],b['detected_centroids'])
            pairs.append(pair)
    comparable=[]
    for pair in pairs:
        if pair['status']=='candidate_visual_band_match':
            chosen=[im for im in images if im[0]['obs_id'] in pair['obs_ids'] and im[0]['status']=='reprojected']
            if len(chosen)==2:
                common=np.logical_and.reduce([np.isfinite(im[3]) for im in chosen])
                if common.sum()>=30:
                    values=np.concatenate([im[3][common] for im in chosen])
                    lo,hi=np.percentile(values,[1,99])
                    comparable.append({"obs_ids":pair['obs_ids'],"common_pixels":int(common.sum()),"lo":lo,"hi":hi,
                                       "method":"common valid footprint pooled p1/p99 + asinh(10x)",
                                       "pair_alignment_status":pair.get('empirical_alignment',{}).get('status','unverified'),
                                       "scope":"target-wavelength matched display diagnostic; field-wide passbands not verified; no photometry claim"})
    # All-frame shared scale is explicitly a display diagnostic across wavelengths.
    if images:
        values=np.concatenate([im[3][np.isfinite(im[3])] for im in images if np.isfinite(im[3]).any()])
        lo,hi=np.percentile(values,[1,99])
        board=Image.new('RGB',(1000,90+len(images)*290),(15,20,30));draw=ImageDraw.Draw(board)
        draw.text((12,10),'PHASE 4.2 - DIFFERENT WAVELENGTHS: DISPLAY DIAGNOSTIC ONLY, NOT A LIGHT CURVE',fill='white')
        for x,label in [(12,'Native / individual'),(260,'Aligned / individual'),(508,'Native / shared scale'),(756,'Aligned / shared scale')]:
            draw.text((x,45),label,fill='white')
        for index,(result,native,good,aligned,directory) in enumerate(images):
            raw=np.where(good,native,np.nan)
            finite=aligned[np.isfinite(aligned)]
            alo,ahi=np.percentile(finite,[1,99]) if finite.size else (0,1)
            rn=raw[np.isfinite(raw)];nlo,nhi=np.percentile(rn,[1,99]) if rn.size else (0,1)
            result['display']={"aligned_individual":{"lo":float(alo),"hi":float(ahi)},
                               "native_individual":{"lo":float(nlo),"hi":float(nhi)},
                               "all_frame_shared":{"lo":float(lo),"hi":float(hi),"scope":"cross-wavelength diagnostic only"},
                               "aligned_median_mjy_sr":float(np.median(finite)) if finite.size else None}
            tiles=[display(raw,nlo,nhi),display(aligned,alo,ahi),display(raw,lo,hi),display(aligned,lo,hi)]
            for name,tile in zip(['native-individual','aligned-individual','native-shared','aligned-shared'],tiles):
                tile.save(directory/f'{name}.png')
            y=80+index*290
            for x,tile in zip([12,260,508,756],tiles):board.paste(tile,(x,y))
            s=result.get('spectral',{})
            label=f"{result['obs_id']}  {result.get('date_obs')}  lambda={s.get('wavelength_um',float('nan')):.6f} um  BW={s.get('bandwidth_um',float('nan')):.6f} um"
            draw.text((12,y+238),label,fill='white')
            draw.text((12,y+255),f"center={result['status']}  empirical={result['empirical_alignment']['status']}  purple=invalid/masked",fill='white')
        board.save(OUT/'comparison.png')
        shared={"lo":lo,"hi":hi,"method":"all-frame pooled p1/p99 + asinh(10x)",
                "scope":"cross-wavelength visual diagnostic ONLY; not same-band temporal brightness comparison"}
    else:shared=None
    for index,normal in enumerate(comparable):
        chosen=[im for im in images if im[0]['obs_id'] in normal['obs_ids']]
        pairboard=Image.new('RGB',(510,300),(15,20,30));draw=ImageDraw.Draw(pairboard)
        draw.text((10,5),'CANDIDATE VISUAL BAND MATCH - NOT PRECISION PHOTOMETRY',fill='white')
        for x,im in zip([10,265],chosen):
            pairboard.paste(display(im[3],normal['lo'],normal['hi']),(x,30))
            draw.text((x,268),im[0]['obs_id'],fill='white')
        draw.text((10,284),f"pair alignment: {normal['pair_alignment_status']}",fill='white')
        pairboard.save(OUT/f'candidate-band-pair-{index+1}.png')
    w=grid();header=w.to_header()
    summary={"generated_utc":utc(),"query":{"ra":RA,"dec":DEC},
             "grid":{"shape_yx":[SIZE,SIZE],"pixel_scale_arcsec":SCALE,"center_xy":[14,14],
                     "orientation":"north up east left after flipud for PNG","fits_header":dict(header)},
             "frames":results,"spectral_pairs":pairs,"matched_pair_normalizations":comparable,
             "display_diagnostic_normalization":shared,
             "empirical_threshold":{"minimum_matched_stars":3,"median_pixels_lt":0.5,"maximum_pixels_lt":1.0},
             "requests_ledger":"requests.json","processing_elapsed_seconds":time.monotonic()-start,
             "environment":{"python":sys.version,"numpy":np.__version__,"astropy":__import__('astropy').__version__,
                            "pillow":__import__('PIL').__version__,"psutil":psutil.__version__},
             "memory":{"process_peak_working_set_bytes":psutil.Process().memory_info().peak_wset,
                       "scope":"Windows local process; not 512MB-limited Render verification"}}
    save_json(OUT/'validation.json',summary)
    for r in results:
        save_json(OUT/r['obs_id']/'metadata.json',r)
    print(json.dumps(safe({"frames":[{k:r.get(k) for k in ['obs_id','status','date_obs','spectral','aligned_valid_fraction','empirical_alignment']} for r in results],
                           "matched_pair_normalizations":comparable,"memory":summary['memory']}),indent=2))


if __name__=='__main__':
    main()

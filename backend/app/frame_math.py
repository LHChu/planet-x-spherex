"""Phase 4.2 verified numerical kernels; visualization only, no photometry."""
import numpy as np
from astropy import units as u

SCALE = 6.15


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
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = np.where(finite, x, -2), np.where(finite, y, -2)
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



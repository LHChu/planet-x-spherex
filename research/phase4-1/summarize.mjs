// Offline research only. Mirrors the convex spherical footprint test in
// backend/app/candidates.py; this never replaces the FITS WCS/finite-pixel check.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = process.argv[3];
const rad = x => x * Math.PI / 180;
const dot = (a,b) => a.reduce((s,v,i) => s + v*b[i],0);
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const vector = (ra,dec) => [Math.cos(rad(dec))*Math.cos(rad(ra)),Math.cos(rad(dec))*Math.sin(rad(ra)),Math.sin(rad(dec))];
function margin(region) {
  const tokens = region.trim().split(/\s+/);
  if (tokens[0] !== 'POLYGON' || tokens[1] !== 'ICRS') return null;
  const numbers = tokens.slice(2).map(Number);
  if (numbers.length % 2 || numbers.some(x=>!Number.isFinite(x))) return null;
  const v = [];
  for(let i=0;i<numbers.length;i+=2) v.push(vector(numbers[i],numbers[i+1]));
  if(v.length>3 && v[0].every((x,i)=>Math.abs(x-v.at(-1)[i])<1e-12)) v.pop();
  if(v.length<3) return null;
  const centre = [0,1,2].map(i=>v.reduce((s,p)=>s+p[i],0));
  const normals = v.map((p,i)=>cross(p,v[(i+1)%v.length])).map(n=>{
    const length=Math.hypot(...n); if(length<1e-12) return null;
    const sign=dot(n,centre)>=0?1:-1; return n.map(x=>sign*x/length);
  });
  if(normals.some(n=>!n || v.some(p=>dot(n,p)<-1e-10)) || v.some(p=>dot(p,centre)<=0)) return null;
  const target=vector(input.query.ra,input.query.dec);
  return Math.min(...normals.map(n=>Math.asin(Math.max(-1,Math.min(1,dot(n,target))))))*180/Math.PI*3600;
}
const mjdUtc = x => new Date(Date.UTC(1858,10,17)+Number(x)*86400000).toISOString();
const count = (rows,key) => Object.fromEntries([...new Set(rows.map(key))].sort().map(k=>[k,rows.filter(r=>key(r)===k).length]));
const unique = (rows,key) => new Set(rows.map(key)).size;
const headerValue = (header,key) => {
  const line=header.split('\n').find(l=>l.slice(0,8).trim()===key);
  if(!line) return null;
  const value=line.slice(10).trim();
  return value.startsWith("'") ? value.slice(1,value.indexOf("'",1)).trim() : value.split('/')[0].trim();
};
const image = input.existing_cutout.hdu.find(h=>h.name==='IMAGE');
const rows = input.collections.flatMap(c=>c.rows.map(r=>{
  const d=Number(r.energy_bandpassname.match(/(?:SPHEREx-D|D)([1-6])(?:_|$)/)?.[1])||null;
  const version=r.access_url.match(/(l2b(?:_retry)?)-v(\d+)-(\d{4}-\d{3})/);
  const m=margin(r.s_region);
  const saved=r.obs_id===input.existing_cutout.sia.obs_id && r.access_url===input.existing_cutout.sia.access_url;
  return {obs_collection:c.collection,obs_id:r.obs_id,detector:d,energy_bandpassname:r.energy_bandpassname,
    t_min:Number(r.t_min),t_max:Number(r.t_max),t_min_utc:mjdUtc(r.t_min),t_max_utc:mjdUtc(r.t_max),
    date_obs:saved?headerValue(image.header,'DATE-OBS'):null,date_obs_source:saved?'existing Phase 1 FITS IMAGE header':'not downloaded',
    em_min:Number(r.em_min),em_max:Number(r.em_max),em_unit:'m',access_url:r.access_url,
    processing_flavor:version?.[1]??null,product_version:version?.[2]??null,processing_date:version?.[3]??null,
    pipeline_software_version:saved?input.existing_cutout.version:null,
    s_pixel_scale_arcsec:Number(r.s_pixel_scale),shape_yx:[Number(r.s_xel2),Number(r.s_xel1)],
    footprint_margin_arcsec:m,coverage_status:m===null?'unknown':m>=0?'metadata_contains_target':'metadata_outside_target',
    wcs_validated:saved,exposure_key:r.obs_id,product_key:`${r.obs_id}/D${d}`};
}));
rows.sort((a,b)=>a.t_min-b.t_min||a.detector-b.detector);
const groups=[];
for(const id of [...new Set(rows.map(r=>r.obs_id))]) {
  const g=rows.filter(r=>r.obs_id===id);
  groups.push({obs_id:id,t_min:Math.min(...g.map(r=>r.t_min)),t_min_utc:mjdUtc(Math.min(...g.map(r=>r.t_min))),
    t_max:Math.max(...g.map(r=>r.t_max)),detectors:g.map(r=>r.detector),collections:[...new Set(g.map(r=>r.obs_collection))],
    contains_target_detectors:g.filter(r=>r.coverage_status==='metadata_contains_target').map(r=>r.detector)});
}
const byCollection=input.collections.map(c=>{
  const g=rows.filter(r=>r.obs_collection===c.collection);
  return {collection:c.collection,status:c.status,rows:g.length,unique_exposures:unique(g,r=>r.obs_id),
    date_min:g[0]?.t_min_utc,date_max:g.at(-1)?.t_max_utc,detectors:count(g,r=>r.detector),
    contains_target_rows:g.filter(r=>r.coverage_status==='metadata_contains_target').length,
    contains_target_exposures:unique(g.filter(r=>r.coverage_status==='metadata_contains_target'),r=>r.obs_id),
    versions:count(g,r=>`v${r.product_version}-${r.processing_date}`)};
});
const summary={analyzed_utc:input.analyzed_utc,query:input.query,
  provenance:input.collections.map(({rows,columns,...rest})=>rest),collections:byCollection,
  total_rows:rows.length,unique_exposures:groups.length,unique_time_intervals:unique(rows,r=>`${r.t_min}/${r.t_max}`),
  duplicate_url_rows:rows.length-unique(rows,r=>r.access_url),duplicate_product_rows:rows.length-unique(rows,r=>r.product_key),
  cross_collection_exposure_ids:groups.filter(g=>g.collections.length>1).map(g=>g.obs_id),
  contains_target_exposures:groups.filter(g=>g.contains_target_detectors.length).length,
  outside_rows:rows.filter(r=>r.coverage_status==='metadata_outside_target').length,
  unknown_coverage_rows:rows.filter(r=>r.coverage_status==='unknown').length,
  pixel_scales:count(rows,r=>r.s_pixel_scale_arcsec),
  detectors:[1,2,3,4,5,6].map(d=>{const g=rows.filter(r=>r.detector===d);return {detector:d,rows:g.length,
    contains_target_rows:g.filter(r=>r.coverage_status==='metadata_contains_target').length,
    intervals_m:g.length?[g[0].em_min,g[0].em_max]:null,
    interval_variants:unique(g,r=>`${r.em_min}/${r.em_max}`)};}),
  existing_cutout:{obs_id:input.existing_cutout.sia.obs_id,detector:input.existing_cutout.sia.detector,
    date_obs:headerValue(image.header,'DATE-OBS'),mjd_obs:headerValue(image.header,'MJD-OBS'),
    bunit:headerValue(image.header,'BUNIT'),pipeline_software_version:input.existing_cutout.version,
    shape_yx:input.existing_cutout.shape,target_pixel_xy:input.existing_cutout.target_pixel_xy},
  dates:count(groups,g=>g.t_min_utc.slice(0,10))};
for(const [name,value] of Object.entries({rows,epochs:groups,summary})) writeFileSync(join(out,`${name}.json`),JSON.stringify(value,null,2)+'\n');
console.log(JSON.stringify(summary,null,2));

// Local Chromium acceptance. Generate fixtures: python -m backend.tests.preview_medium_probe
import http from 'node:http';
import { spawn } from 'node:child_process';
import { readFile, mkdir, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const root=new URL('../',import.meta.url), output=new URL('../coverage/preview-medium/',import.meta.url);
const fixtures=Object.fromEntries(await Promise.all(['small','medium'].map(async profile=>[
  profile,JSON.parse(await readFile(new URL(`../../backend/test-results/preview-medium/${profile}.json`,import.meta.url),'utf8'))
])));
await mkdir(output,{recursive:true});
const harness=`window.addEventListener('load',async()=>{
 const $=id=>document.getElementById(id),check=(v,m)=>{if(!v)throw Error(m);};
 const wait=async fn=>{for(let i=0;i<200;i++){if(fn())return;await new Promise(r=>setTimeout(r,25));}throw Error('Timed out');};
 const original=window.fetch;let posts=0;window.fetch=(url,options)=>{if(String(url).endsWith('/api/preview'))posts++;return original(url,options);};
 try{
  $('ra').value='359.999';$('dec').value='80';$('radius').value='0.6';
  $('search-form').requestSubmit();await wait(()=>$('status').dataset.state==='success');
  check($('preview').naturalWidth===29,'Legacy Small dimensions');
  $('cutout-profile').value='medium';$('cutout-profile').dispatchEvent(new Event('change'));
  await wait(()=>$('status').dataset.state==='success'&&$('preview').naturalWidth===65);
  await $('preview').decode();
  check(posts===2,'One fresh Medium request');
  check($('preview-cutout-details').textContent.includes('6.5 arcmin (medium)'),'Requested size visible');
  check($('preview-cutout-details').textContent.includes('65 × 65'),'Actual FITS shape visible');
  check($('preview-cutout-details').textContent.includes('sampled centre lines'),'Actual WCS span visible');
  for(const method of ['linear','asinh','log','sqrt']){
   $('stretch').value=method;$('stretch').dispatchEvent(new Event('change'));await $('preview').decode();
   const c=document.createElement('canvas');c.width=c.height=65;const ctx=c.getContext('2d');ctx.drawImage($('preview'),0,0);
   check(ctx.getImageData(0,0,1,1).data[3]===0,'NaN alpha preserved');
  }
  $('zoom').value='4';$('zoom').dispatchEvent(new Event('input'));
  check(parseFloat($('preview').style.width)===260,'Manual Zoom uses native size');
  $('fit-view').click();await new Promise(r=>setTimeout(r,150));
  const f=$('preview-frame').getBoundingClientRect(),v=$('viewport');
  check(f.width<=v.clientWidth+1&&f.height<=v.clientHeight+1,'Fit includes image and annotations');
  check($('preview-axes').textContent.includes('RA')&&$('preview-axes').textContent.includes('Dec'),'WCS labels');
  check($('preview-colorbar').textContent.includes('MJy/sr'),'Color Bar');
  check(posts===2,'Stretch/Fit/Zoom make no requests');
  check(document.documentElement.scrollWidth<=innerWidth,'No page horizontal overflow');
  document.body.dataset.mediumResult=JSON.stringify({width:innerWidth,height:innerHeight,posts,nativeWidth:$('preview').naturalWidth,
   fitWidth:f.width,fitHeight:f.height,viewportWidth:v.clientWidth,viewportHeight:v.clientHeight});
 }catch(e){document.body.dataset.mediumError=e.stack;}
});`;
const requests=[];
const server=http.createServer(async(req,res)=>{
 try{
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'");
  if(req.url==='/api/preview'){
   let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);requests.push(body);
   const f=fixtures[body.cutout_profile||'small'];if(!f){res.writeHead(422).end();return;}
   const {black_png_base64,white_png_base64,...payload}=f;
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify(payload));return;
  }
  for(const f of Object.values(fixtures))for(const [name,key]of [['image_url','black_png_base64'],['inverted_image_url','white_png_base64']]){
   if(req.url===new URL(f[name]).pathname){res.setHeader('Content-Type','image/png');res.end(Buffer.from(f[key],'base64'));return;}
  }
  const file=new URL(req.url,'http://localhost').pathname.slice(1)||'index.html';
  if(!['index.html','app.js','epochs.js','brightness.js','color-bar.js','wcs-axes.js','config.js','styles.css'].includes(file)){res.writeHead(404).end();return;}
  let data=await readFile(new URL(file,root));
  if(file==='index.html')data=Buffer.from(data.toString().replace('</body>',`<script>${harness}</script></body>`));
  res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(data);
 }catch(e){res.writeHead(500).end(e.message);}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const port=server.address().port,profile=await mkdtemp(path.join(tmpdir(),'spherex-medium-'));
const chrome=spawn(process.argv[2]||'C:/Program Files/Google/Chrome/Application/chrome.exe',[
 // Dedicated temporary browser, repository-owned HTML and local synthetic API
 // only. Windows restricted execution cannot start Chromium sandbox children.
 '--headless','--disable-gpu','--in-process-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--disable-background-networking',
 '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true});
let socket;const results=[],keepAlive=setInterval(()=>{},1000);
let chromeLog='';chrome.stderr.on('data',chunk=>{chromeLog+=chunk;});
try{
 const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(Error(`Chromium startup timed out: ${log}`)),20000);
  chrome.on('error',e=>{clearTimeout(timer);reject(e);});chrome.on('exit',code=>{clearTimeout(timer);reject(Error(`Chromium exited ${code}: ${log}`));});chrome.stderr.on('data',chunk=>{
  log+=chunk;const m=log.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(m){clearTimeout(timer);resolve(new URL(m[1]));}
 });});
 const target=await(await fetch(`http://${endpoint.host}/json/new?about:blank`,{method:'PUT'})).json();
 socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
 let id=0;const pending=new Map();socket.addEventListener('message',event=>{const d=JSON.parse(event.data);if(d.id){const p=pending.get(d.id);pending.delete(d.id);d.error?p.reject(Error(JSON.stringify(d.error))):p.resolve(d.result);}});
 function send(method,params={}){return new Promise((resolve,reject)=>{const current=++id,timer=setTimeout(()=>reject(Error(`CDP timeout ${method}`)),15000);pending.set(current,{resolve:r=>{clearTimeout(timer);resolve(r);},reject});socket.send(JSON.stringify({id:current,method,params}));});}
 async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
 for(const [width,height]of [[1366,768],[768,1024],[390,844]]){
  await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:`http://127.0.0.1:${port}/?devApiOrigin=http://127.0.0.1:${port}`});
  let result;
  for(let i=0;i<150;i++){
   const error=await evaluate('document.body?.dataset.mediumError');if(error)throw Error(error);
   result=await evaluate('document.body?.dataset.mediumResult');if(result)break;
   await new Promise(r=>setTimeout(r,100));
  }
  assert.ok(result,'Browser fixture did not complete');results.push(JSON.parse(result));
  await writeFile(new URL(`${width}x${height}.png`,output),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
 }
 assert.equal(requests.length,6);
 for(let i=0;i<requests.length;i+=2){assert.equal(requests[i].cutout_profile,undefined);assert.equal(requests[i+1].cutout_profile,'medium');assert.equal(requests[i+1].radius_deg,.01);}
 await writeFile(new URL('results.json',output),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results,null,2));
}finally{
 clearInterval(keepAlive);socket?.close();
 await writeFile(new URL('chromium.log',output),chromeLog);
 if(chrome.exitCode===null&&chrome.signalCode===null){const stopped=new Promise(r=>chrome.once('exit',r));chrome.kill();await stopped;}
 await new Promise(r=>{server.close(r);server.closeAllConnections();});
 const expected=path.join(path.resolve(tmpdir()),'spherex-medium-');
 assert.ok(path.isAbsolute(profile)&&path.resolve(profile).startsWith(expected),'Refuse cleanup outside generated profile');
 await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:200});
}

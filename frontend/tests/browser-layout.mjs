// Optional Chromium layout acceptance test; uses only the local offline fixture.
// First: node frontend/tools/serve.mjs --wcs-fixture --port=5507 --fixture-port=8007
// Then: node frontend/tests/browser-layout.mjs [path-to-Chromium]
import http from 'node:http';
import { spawn } from 'node:child_process';
import { readFile, mkdir, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),out=new URL('../coverage/round4/',import.meta.url);
await mkdir(out,{recursive:true});
const harness=mode=>`window.addEventListener('load',async()=>{
  window.uiRequestCount=0;const fetchOriginal=window.fetch;window.fetch=(...args)=>{window.uiRequestCount++;return fetchOriginal(...args);};
  const $=id=>document.getElementById(id),wait=async test=>{for(let i=0;i<200;i++){if(test())return;await new Promise(r=>setTimeout(r,50));}throw Error('Fixture timeout');};
  try{
    ${mode==='epochs'?`$('explorer-mode').value='epochs';$('explorer-mode').dispatchEvent(new Event('change'));`:''}
    $('search-form').requestSubmit();
    ${mode==='epochs'?`await wait(()=>!$('select-first-3').disabled);$('select-first-3').click();$('load-frames').click();await wait(()=>!$('epoch-player').hidden);`:`await wait(()=>$('status').dataset.state==='success');`}
    await new Promise(r=>setTimeout(r,500));
    const epoch=${mode==='epochs'},panel=$(epoch?'epoch-view-panel':'preview-panel'),viewport=$(epoch?'epoch-viewport':'viewport'),frame=$(epoch?'epoch-frame':'preview-frame'),f=frame.getBoundingClientRect();
    const result={mode:'${mode}',width:innerWidth,height:innerHeight,panelBottom:panel.getBoundingClientRect().bottom,searchBottom:$('search').getBoundingClientRect().bottom,viewportHeight:viewport.clientHeight,frameFits:f.width<=viewport.clientWidth&&f.height<=viewport.clientHeight,innerScroll:viewport.scrollWidth>viewport.clientWidth+1||viewport.scrollHeight>viewport.clientHeight+1,horizontalOverflow:document.documentElement.scrollWidth>innerWidth,axes:$(epoch?'epoch-axes':'preview-axes').textContent,playerBottom:epoch?$('epoch-player').getBoundingClientRect().bottom:null};
    document.body.setAttribute('data-layout-result',JSON.stringify(result));
  }catch(error){document.body.setAttribute('data-layout-error',error.message);}
});`;
const server=http.createServer(async(req,res)=>{
  try{
    if(req.url.startsWith('/api/')){
      const upstream=http.request({hostname:'127.0.0.1',port:8007,path:req.url,method:req.method,headers:req.headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res);});
      upstream.on('error',()=>res.writeHead(502).end());req.pipe(upstream);return;
    }
    const url=new URL(req.url,'http://127.0.0.1'),file=url.pathname==='/'?'index.html':url.pathname.slice(1);
    if(!['index.html','styles.css','app.js','epochs.js','brightness.js','color-bar.js','wcs-axes.js','config.js'].includes(file)){res.writeHead(404).end();return;}
    let body=await readFile(new URL(file,root));
    if(file==='index.html')body=Buffer.from(body.toString().replace('</body>',`<script>${harness(url.searchParams.get('mode'))}</script></body>`));
    res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html');res.end(body);
  }catch(error){res.writeHead(500).end(error.message);}
});
await new Promise(resolve=>server.listen(5508,'127.0.0.1',resolve));
const profile=await mkdtemp(path.join(tmpdir(),'spherex-layout-'));
const chrome=spawn(process.argv[2]||'C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true});
let socket;
const results=[],keepAlive=setInterval(()=>{},1000);
try{
  const endpoint=await new Promise((resolve,reject)=>{let log='';chrome.on('error',reject);chrome.stderr.on('data',chunk=>{log+=chunk;const match=log.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match)resolve(new URL(match[1]));});});
  const target=await(await fetch(`http://${endpoint.host}/json/new?about:blank`,{method:'PUT'})).json();
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  let nextId=0;const pending=new Map(),errors=[];
  socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(data.id){const task=pending.get(data.id);pending.delete(data.id);if(data.error)task.reject(Error(JSON.stringify(data.error)));else task.resolve(data.result);}if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails);});
  function send(method,params={}){return new Promise((resolve,reject)=>{const id=++nextId,timeout=setTimeout(()=>reject(Error(`CDP timeout: ${method}`)),15000);pending.set(id,{resolve:result=>{clearTimeout(timeout);resolve(result);},reject});socket.send(JSON.stringify({id,method,params}));});}
  async function evaluate(expression){const result=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;}
  await send('Runtime.enable');
  for(const mode of ['preview','epochs'])for(const [width,height]of [[1920,1080],[1536,864],[1440,900],[1366,768],[768,1024],[390,844]]){
    await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:`http://127.0.0.1:5508/?mode=${mode}&devApiOrigin=http://127.0.0.1:5508`});
    let metrics;
    for(let i=0;i<150;i++){metrics=await evaluate(`document.body?.getAttribute('data-layout-result')`);if(metrics)break;const error=await evaluate(`document.body?.getAttribute('data-layout-error')`);if(error)throw Error(error);await new Promise(r=>setTimeout(r,100));}
    assert.ok(metrics,'Browser did not finish fixture');metrics=JSON.parse(metrics);
    assert.equal(metrics.width,width);assert.equal(metrics.height,height);
    assert.equal(metrics.horizontalOverflow,false,`${mode} ${width}: page horizontal overflow`);
    assert.equal(metrics.frameFits,true,`${mode} ${width}: Fit frame overflow`);
    assert.equal(metrics.innerScroll,false,`${mode} ${width}: Fit scrollbars`);
    assert.ok(metrics.axes.includes('RA')&&metrics.axes.includes('Dec'),'WCS labels present');
    if(width>=1100){assert.ok(metrics.searchBottom<=height);assert.ok(metrics.panelBottom<=height || metrics.viewportHeight<=300,JSON.stringify(metrics));}
    if(mode==='epochs') {
      if(width>=1100) assert.equal(await evaluate(`(()=>{const a=document.getElementById('change-selection').getBoundingClientRect(),b=document.getElementById('epoch-fit-view').getBoundingClientRect();return Math.abs(a.top-b.top)<2&&b.left-a.right>=8&&b.left-a.right<=12;})()`),true,'Selection and Fit share a horizontal row');
      const requests=await evaluate('window.uiRequestCount');
      await evaluate(`document.getElementById('change-selection').focus();document.getElementById('change-selection').click()`);
      assert.equal(await evaluate(`document.activeElement.id`),'observations-title');
      assert.equal(await evaluate(`document.body.style.overflow`),'hidden');
      const modal=await evaluate(`(()=>{const d=document.getElementById('observations-modal'),r=d.getBoundingClientRect();return {inside:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,center:Math.abs((r.left+r.right)/2-innerWidth/2)<2};})()`);
      assert.equal(modal.inside,true,JSON.stringify(modal));assert.equal(modal.center,true);
      await evaluate(`(()=>{const body=document.getElementById('epoch-products');for(let i=0;i<40;i++){const row=body.children[0].cloneNode(true);row.dataset.clone='true';body.append(row);}})()`);
      assert.equal(await evaluate(`(()=>{const m=document.querySelector('.modal-content');return m.scrollHeight>m.clientHeight&&document.getElementById('observations-modal').getBoundingClientRect().bottom<=innerHeight;})()`),true,'Long list scrolls inside modal');
      assert.equal(await evaluate(`(()=>{const modal=document.getElementById('observations-modal'),footer=modal.querySelector('.modal-footer'),load=document.getElementById('load-frames'),cancel=document.getElementById('observations-cancel'),a=load.getBoundingClientRect(),b=cancel.getBoundingClientRect(),f=footer.getBoundingClientRect();return footer.contains(load)&&footer.contains(cancel)&&Math.abs((a.top+a.bottom-b.top-b.bottom)/2)<2&&b.right<a.left&&a.right<=innerWidth&&b.left>=0&&f.bottom<=innerHeight&&a.width<modal.clientWidth*.7;})()`),true,'Footer buttons share a bounded content-width row');
      await evaluate(`document.querySelector('.modal-content').scrollTop=100000`);
      assert.equal(await evaluate(`(()=>{const f=document.querySelector('.modal-footer').getBoundingClientRect();return f.top>=0&&f.bottom<=innerHeight;})()`),true,'Footer remains visible after long list scroll');
      await writeFile(new URL(`modal-${width}x${height}.png`,out),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false})).data,'base64'));
      await evaluate(`document.querySelectorAll('[data-clone]').forEach(n=>n.remove());document.getElementById('observations-close').focus()`);
      for(let i=0;i<22;i++) {
        await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
        await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
        assert.equal(await evaluate(`document.getElementById('observations-modal').contains(document.activeElement)`),true,'Tab remains within modal');
      }
      await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9,modifiers:8});
      await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9,modifiers:8});
      assert.equal(await evaluate(`document.getElementById('observations-modal').contains(document.activeElement)`),true,'Shift Tab remains within modal');
      await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
      await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
      await new Promise(r=>setTimeout(r,60));
      assert.equal(await evaluate(`document.getElementById('observations-modal').open`),false);
      assert.equal(await evaluate(`document.activeElement.id`),'change-selection');
      assert.equal(await evaluate(`document.body.style.overflow`),'');
      for(const close of ['observations-close','observations-cancel','load-frames']) {
        await evaluate(`document.getElementById('change-selection').click();document.getElementById('${close}').click()`);
        await new Promise(r=>setTimeout(r,60));
        assert.equal(await evaluate(`document.getElementById('observations-modal').open`),false);
      }
      assert.equal(await evaluate('window.uiRequestCount'),requests,'Reopen, Escape, X, Cancel, unchanged Load make no requests');
      console.log(`PASS modal ${width}: focus containment, Escape, return focus, scroll lock, long list, reopen and unchanged selection`);
    }
    // Exercise actual DOM image clicks at every desktop/tablet/mobile viewport.
    const prefix=mode==='epochs'?'epoch-':'', zoomId=mode==='epochs'?'epoch-zoom':'zoom';
    const imageSelector=mode==='epochs'?'#epoch-image img':'#preview';
    const requestsBeforeClick=await evaluate('window.uiRequestCount');
    if(mode==='epochs') await evaluate(`document.getElementById('epoch-time').value=0;document.getElementById('epoch-time').dispatchEvent(new Event('input'))`);
    const clickResult=await evaluate(`(()=>{const img=document.querySelector('${imageSelector}'),slider=document.getElementById('${zoomId}'),v=document.getElementById('${mode==='epochs'?'epoch-viewport':'viewport'}'),fit=Number(slider.value),r=img.getBoundingClientRect(),cursor=getComputedStyle(img).cursor;img.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:r.left+r.width*.8,clientY:r.top+r.height*.8}));const next=Number(slider.value),text=document.getElementById('${mode==='epochs'?'epoch-zoom-value':'zoom-value'}').textContent;return {fit,next,text,cursor,scroll:v.scrollLeft};})()`);
    assert.equal(clickResult.cursor,clickResult.fit>=32?'default':'zoom-in');
    assert.ok(Math.abs(clickResult.next-Math.min(32,clickResult.fit*1.5))<1e-7,JSON.stringify(clickResult));
    assert.ok(Math.abs(parseFloat(clickResult.text)-clickResult.next)<1e-7);
    await evaluate(`(()=>{const img=document.querySelector('${imageSelector}');for(let i=0;i<30;i++){const r=img.getBoundingClientRect();img.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:r.left+r.width*.6,clientY:r.top+r.height*.6}));}})()`);
    assert.equal(await evaluate(`Number(document.getElementById('${zoomId}').value)`),32);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('${imageSelector}')).cursor`),'default');
    const alignment=await evaluate(`(()=>{const img=document.querySelector('${imageSelector}').getBoundingClientRect(),axes=document.getElementById('${mode==='epochs'?'epoch-axes':'preview-axes'}'),x=axes.querySelector('.wcs-x-line').getBoundingClientRect(),y=axes.querySelector('.wcs-y-line').getBoundingClientRect();return {bottom:Math.abs(x.top-img.bottom),left:Math.abs(y.left-img.left),width:Math.abs(x.width-img.width),height:Math.abs(y.height-img.height)};})()`);
    assert.ok(Object.values(alignment).every(delta=>delta<1.1),JSON.stringify(alignment));
    await evaluate(`document.getElementById('${mode==='epochs'?'epoch-fit-view':'fit-view'}').click()`);
    await new Promise(r=>setTimeout(r,100));
    assert.equal(await evaluate('window.uiRequestCount'),requestsBeforeClick,'Image click zoom is request-free');
    await writeFile(new URL(`${mode}-${width}x${height}.png`,out),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false})).data,'base64'));
    if(width===1920 || width===390) {
      await evaluate(`document.getElementById('${mode==='epochs'?'epoch-advanced':'preview-advanced'}').open=true;document.getElementById('${mode==='epochs'?'epoch-information':'preview-summary'}').scrollIntoView()`);
      await writeFile(new URL(`${mode}-details-${width}.png`,out),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false})).data,'base64'));
      await evaluate(`document.getElementById('${mode==='epochs'?'epoch-advanced':'preview-advanced'}').open=false;document.querySelector('footer').scrollIntoView()`);
      assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth`),false,'Details and footer have no page overflow');
      await writeFile(new URL(`${mode}-footer-${width}.png`,out),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false})).data,'base64'));
      await evaluate('window.scrollTo(0,0)');
    }
    if(width===390){
      await evaluate(`document.getElementById('${mode==='epochs'?'epoch-view-panel':'preview-panel'}').scrollIntoView()`);
      await writeFile(new URL(`${mode}-390-viewer.png`,out),Buffer.from((await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false})).data,'base64'));
      await evaluate('window.scrollTo(0,0)');
    }
    results.push(metrics);console.log(`PASS ${mode} ${width}x${height}: viewer bottom ${metrics.panelBottom}`);
    if(width===1536){
      const before=await evaluate('window.uiRequestCount');
      if(mode==='preview'){
        const originalHeight=await evaluate(`document.getElementById('preview-panel').getBoundingClientRect().height`);
        await evaluate(`document.getElementById('brightness-controls').open=true; document.getElementById('stretch').value='asinh'; document.getElementById('stretch').dispatchEvent(new Event('change'));document.getElementById('quality-overlay').click()`);
        await new Promise(r=>setTimeout(r,200));
        assert.equal(await evaluate(`document.getElementById('preview-panel').getBoundingClientRect().height`),originalHeight,'Brightness stretched viewer');
        await writeFile(new URL('preview-brightness.png',out),Buffer.from((await send('Page.captureScreenshot')).data,'base64'));
        await evaluate(`document.getElementById('brightness-controls').open=false`);
      }else{
        await evaluate(`document.getElementById('epoch-next').click()`);
        assert.match(await evaluate(`document.getElementById('epoch-frame-status').textContent`),/failed/);
        await evaluate(`document.getElementById('epoch-play').click()`);
        await new Promise(r=>setTimeout(r,1100));
        await evaluate(`document.getElementById('epoch-time').value=2;document.getElementById('epoch-time').dispatchEvent(new Event('input'));document.getElementById('epoch-prev').click()`);
      }
      const zoom=mode==='epochs'?'epoch-zoom':'zoom',image=mode==='epochs'?'epoch-image':'preview',viewport=mode==='epochs'?'epoch-viewport':'viewport',fit=mode==='epochs'?'epoch-fit-view':'fit-view';
      await evaluate(`document.getElementById('${zoom}').value=32;document.getElementById('${zoom}').dispatchEvent(new Event('input'))`);
      const manual=await evaluate(`document.getElementById('${image}').style.width`);
      await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
      await new Promise(r=>setTimeout(r,200));
      assert.equal(await evaluate(`document.getElementById('${image}').style.width`),manual);
      assert.ok(await evaluate(`document.getElementById('${viewport}').scrollWidth>document.getElementById('${viewport}').clientWidth`),'Manual zoom needs internal scrolling');
      assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
      await evaluate(`document.getElementById('${fit}').click()`);
      await new Promise(r=>setTimeout(r,200));
      assert.ok(await evaluate(`document.getElementById('${viewport}').scrollWidth<=document.getElementById('${viewport}').clientWidth+1`));
      assert.equal(await evaluate('window.uiRequestCount'),before,'Interaction made extra API requests');
      await send('Emulation.setDeviceMetricsOverride',{width:1536,height:500,deviceScaleFactor:1,mobile:false});
      await new Promise(r=>setTimeout(r,200));
      assert.ok(await evaluate(`document.getElementById('${viewport}').clientHeight>=298`),'Short windows retain readable viewport');
      assert.ok(await evaluate(`document.getElementById('${mode==='epochs'?'epoch-view-panel':'preview-panel'}').getBoundingClientRect().bottom>innerHeight`),'Short windows scroll normally');
      console.log(`PASS ${mode}: brightness/player, failed slots, manual 32x, resize, Fit and zero interaction requests`);
    }
  }
  assert.deepEqual(errors,[]);
  await writeFile(new URL('metrics.json',out),JSON.stringify(results,null,2));
  console.log(`PASS: ${results.length} real Chromium layouts. Screenshots: ${out.pathname}`);
}finally{
  clearInterval(keepAlive);socket?.close();chrome.kill();server.close();
  await new Promise(r=>setTimeout(r,500));await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:300});
}


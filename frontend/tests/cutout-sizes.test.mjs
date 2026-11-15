// Cross-language synthetic fixtures: run backend.tests.cutout_size_probe first.
// Reuse the existing DOM mocks to exercise the actual preview/player handlers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { existsSync, readFileSync } from 'node:fs';
import { axesFixture } from './axes-fixture.mjs';

function setupFactory(file, size) {
  const url = new URL(file, import.meta.url);
  let source = readFileSync(url, 'utf8').split('\ntest(')[0];
  source = source.replace(/^import .*;\r?$/gm, '')
    .replaceAll('import.meta.url', JSON.stringify(url.href))
    .replaceAll('naturalWidth = this.naturalHeight = 29', `naturalWidth = this.naturalHeight = ${size}`)
    .replaceAll('naturalWidth = 29; this.naturalHeight = 29', `naturalWidth = ${size}; this.naturalHeight = ${size}`);
  const context = { vm, readFileSync, assert, axesFixture, URL, URLSearchParams, AbortController, queueMicrotask };
  vm.runInNewContext(source+'\nglobalThis.factory = setup;', context);
  return context.factory;
}

for (const size of [29,64,128]) {
  const fixture = mode => new URL(`../../backend/test-results/cutout-sizes/${mode}-${size}.json`, import.meta.url);
  const missing = !existsSync(fixture('preview')) || !existsSync(fixture('epochs'));
  test(`${size}: synthetic FITS Preview/player, stretches, histogram, color bar, Fit, Zoom, axes`,
    { skip: missing ? 'Generate synthetic FITS fixtures with backend.tests.cutout_size_probe' : false }, async () => {
    const metadata = JSON.parse(readFileSync(fixture('preview'),'utf8'));
    const sequence = JSON.parse(readFileSync(fixture('epochs'),'utf8'));
    const context = { window: {} };
    for (const name of ['brightness.js','wcs-axes.js','color-bar.js']) {
      const code = readFileSync(new URL(`../${name}`, import.meta.url),'utf8');
      vm.runInNewContext(code,context);
    }
    vm.runInNewContext(readFileSync(new URL('../app.js',import.meta.url),'utf8').split('/* Existing preview/PNG endpoints')[0],context);
    const { SpherexBrightness: brightness, SpherexAxes: axes, SpherexColorBar: bar, SpherexView: view } = context.window;
    for (const d of [metadata.display, ...sequence.frames.map(f=>f.display)]) {
      const before = JSON.stringify(d);
      // Epoch histogram intentionally counts native valid samples, not resampled pixels.
      assert.equal(brightness.histogramModel(d.histogram).total,
        d.histogram_source ? size*size-5 : d.valid.filter(Boolean).length);
      for (const method of ['linear','asinh','log','sqrt']) for (const inverse of [false,true]) {
        const rgba = brightness.rgba(d,d.lo,d.hi,method,inverse,false);
        const scale = bar.mapping({ lo:d.lo,hi:d.hi,denominator:d.hi-d.lo,stretch:method,a:10,unit:d.unit,inverse });
        assert.ok(scale);
        for (let i=0;i<d.values.length;i++) {
          const offset = ((size-1-Math.floor(i/size))*size+i%size)*4;
          if (!d.valid[i] || !Number.isFinite(d.values[i])) assert.equal(rgba[offset+3],0);
          else { assert.equal(rgba[offset],bar.gray(scale,d.values[i])); assert.equal(rgba[offset+3],255); }
        }
      }
      assert.equal(JSON.stringify(d),before);
    }
    for (const wcs of [metadata.wcs_axes, sequence.wcs_axes]) {
      for (const [width,height] of [[280,340],[900,600]]) {
        const plan=view.fit(size,size,width,height,width<500);
        const layout=axes.layout(wcs,size,size,plan.factor);
        const extent=bar.measure(layout,false,width<500);
        assert.ok(extent.width*plan.stageScale<=width+1e-7);
        assert.ok(extent.height*plan.stageScale<=height+1e-7);
      }
      for (const factor of [.5,1,12,32]) {
        const model=axes.layout(wcs,size,size,factor);
        assert.ok(model.available);
        for (const tick of model.ra) assert.equal(tick.position,(tick.pixel+.5)*factor);
        for (const tick of model.dec) assert.equal(tick.position,(size-.5-tick.pixel)*factor);
      }
    }
    const previewSetup=setupFactory('./app.test.mjs',size);
    const s=previewSetup({ response: { ok:true,status:200,json:async()=>({image_url:`/api/images/${'a'.repeat(32)}.png`,inverted_image_url:`/api/images/${'a'.repeat(32)}-inverse.png`,metadata}) } });
    await s.submit();
    assert.equal(s.e.status.dataset.state,'success',s.e.status.textContent);
    s.e.zoom.value='4'; s.e.zoom.events.input();
    assert.equal(s.e.preview.style.width,`${size*4}px`);
    s.e['fit-view'].events.click(); assert.match(s.e['zoom-value'].textContent,/Fit/);
    const count=s.calls.length;
    for (const method of ['linear','asinh','log','sqrt']) { s.e.stretch.value=method; s.e.stretch.events.change(); }
    assert.equal(s.calls.length,count);

    const epochSetup=setupFactory('./epochs.test.mjs',size);
    const e=epochSetup({wcsAxes:sequence.wcs_axes,frameDisplay:i=>sequence.frames[i].display,
      frameNormalization:i=>sequence.frames[i].normalization,
      sequenceInfo:{normalization:sequence.normalization}, mode:sequence.mode,
      frameInfo:{bunit:'MJy/sr'} });
    await e.submit(); e.quick(2); await e.load();
    const fetches=e.calls.length;
    for (const position of [1,0,1,0]) { e.e['epoch-time'].value=String(position); e.e['epoch-time'].events.input(); }
    e.e['epoch-zoom'].value='4'; e.e['epoch-zoom'].events.input();
    assert.equal(e.e['epoch-image'].style.width,`${size*4}px`);
    e.e['epoch-fit-view'].events.click();
    assert.match(e.e['epoch-zoom-value'].textContent,/Fit/);
    assert.equal(e.calls.length,fetches,'Frame switching and display controls stay local');
  });
}

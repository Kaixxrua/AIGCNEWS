const { chromium } = require('/home/kaixxrua/AIGCNEWS/frontend/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const output = process.env.EVIDENCE_DIR;
  assert(output && process.env.PREVIEW_URL);
  const browser = await chromium.launch({headless: true,
    executablePath: '/home/kaixxrua/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',
    args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const messages = [];
  const measurements = [];
  try {
    const page = await browser.newPage({viewport: {width: 720, height: 480}, deviceScaleFactor: 1});
    page.setDefaultTimeout(180000);
    page.on('console', message => {
      messages.push(message.text());
      if (/SCRIPT ERROR|WIDE_LANDSCAPE|DETAIL_APPLIED/.test(message.text())) console.log(message.text());
    });
    page.on('pageerror', error => messages.push(`PAGE_ERROR ${error.message}`));
    await page.addInitScript(() => localStorage.setItem('meadow-texture-quality-v1', 'lite'));
    await page.goto(process.env.PREVIEW_URL, {waitUntil: 'domcontentloaded'});
    await page.waitForTimeout(2500);
    const frame = page.frames().find(candidate => candidate.url().includes('/camp-scene/'));
    assert(frame);
    await frame.evaluate(() => {
      window.fpsEvidence = [];
      new MutationObserver(() => {
        window.fpsEvidence.push({text: document.getElementById('scene-fps').textContent, at: performance.now()});
      }).observe(document.getElementById('scene-fps'), {childList: true});
    });
    const enter = frame.getByRole('button', {name: '进入原野', exact: true});
    if (await enter.isVisible()) await enter.click();
    await frame.waitForFunction(() => document.getElementById('canvas')?.dataset.wideLandscape === 'complete', null, {timeout: 600000});
    await frame.waitForFunction(() => window.fpsEvidence.length >= 3);
    for (const [label, width, height] of [['wide',1940,735], ['contact',1600,735], ['portrait',390,844], ['wide-return',1940,735]]) {
      await page.setViewportSize({width,height});
      const before = await frame.evaluate(() => window.fpsEvidence.length);
      await frame.waitForFunction(count => window.fpsEvidence.length >= count + 3, before);
      const result = await frame.evaluate(() => {
        const readout = document.getElementById('scene-fps');
        const rectangle = readout.getBoundingClientRect();
        const canvas = document.getElementById('canvas');
        const controls = document.getElementById('scene-controls').getBoundingClientRect();
        return {text: readout.textContent, hidden: readout.hidden, rectangle: rectangle.toJSON(),
          viewport: {width: innerWidth, height: innerHeight}, canvas: canvas.getBoundingClientRect().toJSON(),
          dataset: {...canvas.dataset}, pointerEvents: getComputedStyle(readout).pointerEvents,
          hit: document.elementFromPoint(rectangle.x + rectangle.width / 2, rectangle.y + rectangle.height / 2)?.id,
          controlsOverlap: rectangle.left < controls.right && rectangle.right > controls.left && rectangle.top < controls.bottom && rectangle.bottom > controls.top,
          samples: window.fpsEvidence.slice(-3)};
      });
      assert.match(result.text, /^\d+ FPS$/);
      assert.equal(result.hidden, false);
      assert.equal(result.pointerEvents, 'none');
      assert.equal(result.hit, 'canvas');
      assert.equal(result.controlsOverlap, false);
      assert(result.rectangle.x >= 0 && result.rectangle.right <= result.viewport.width);
      assert(result.rectangle.y >= 0 && result.rectangle.bottom <= result.viewport.height);
      assert.equal(result.canvas.width, result.viewport.width);
      assert.equal(result.canvas.height, result.viewport.height);
      measurements.push({label, ...result});
      await page.screenshot({path: path.join(output, `${label}.png`)});
      console.log(label, result.text, JSON.stringify(result.samples));
    }
    const samples = await frame.evaluate(() => window.fpsEvidence);
    assert(new Set(samples.map(sample => sample.text)).size > 1, 'Native numeric FPS must change');
    const errors = messages.filter(message => /SCRIPT ERROR|Shader compilation failed|PAGE_ERROR/.test(message));
    fs.writeFileSync(path.join(output, 'browser-measurements.json'), JSON.stringify({measurements,samples,errors}, null, 2));
    assert.deepEqual(errors, []);
  } finally {
    fs.writeFileSync(path.join(output, 'browser-console.log'), messages.join('\n'));
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});

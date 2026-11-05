// Real DOM regression tests; reuses the extension's existing Playwright dependency.
// Run: node --test scripts/mobile-overlay.test.cjs
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../extension/node_modules/@playwright/test');
const ts = require('../mobile/node_modules/typescript');
const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../mobile/src/utils/injectedScript.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const output = {};
new Function('exports', compiled)(output);
let browser;
before(async () => { browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }); });
after(async () => { await browser?.close(); });

async function fixture(width = 390) {
  const page = await browser.newPage({ viewport: { width, height: 844 } });
  await page.route('https://fonts.googleapis.com/**', route => route.abort());
  // Thumbnail is half the resolution of the image uploaded to the server.
  const src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="500" height="1000"><rect width="500" height="1000" fill="#eee"/></svg>');
  await page.setContent(`<style>body {margin:0} #pages {border:3px solid black;padding:7px} img {display:block;width:100%;height:auto}</style><main id="pages"><img id="first" src="${src}"><img id="second" src="${src}"></main>`);
  await page.waitForFunction(() => [...document.images].every(img => img.complete));
  await page.evaluate(() => {
    window.messages = [];
    window.ReactNativeWebView = { postMessage: raw => window.messages.push(JSON.parse(raw)) };
  });
  await page.addScriptTag({ content: output.MANGA_INJECTED_JS });
  // Wait for base styling and font/layout callbacks before measuring.
  await page.evaluate(() => {
    const probe = document.createElement('div');
    probe.id = 'style-probe';
    probe.className = 'ctvn-bubble-box';
    document.body.appendChild(probe);
  });
  await page.waitForFunction(() => getComputedStyle(document.querySelector('#style-probe')).paddingLeft === '2px');
  await page.evaluate(async () => {
    document.querySelector('#style-probe').remove();
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  return page;
}
async function translate(page, blocks) {
  await page.evaluate(blocks => {
    window.__triggerTranslateActivePage();
    const request = window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').at(-1);
    window.__renderRealTranslatedBlocks(blocks, false, { image_width: 1000, image_height: 2000 }, request.targetId);
  }, blocks);
}
const paragraph = 'Theo lệnh truyền xuống, vạn đại quân hùng hậu rầm rộ tiến về phía Nam, hướng thẳng tới chiến trường nước Nam Âu.';

test('xy coordinates and source dimensions stay aligned at phone widths and after resize', async () => {
  const page = await fixture();
  try {
    await translate(page, [{ id: 0, bbox: [120, 800, 850, 1050], translation: paragraph }]);
    for (const width of [390, 320, 430, 780]) {
      await page.setViewportSize({ width, height: 844 });
      await page.waitForFunction(() => {
        const img = document.querySelector('#first').getBoundingClientRect();
        const box = document.querySelector('.ctvn-bubble-box').getBoundingClientRect();
        return Math.abs(box.left - (img.left + img.width * .12)) < 1;
      });
      const result = await page.evaluate(() => {
        const img = document.querySelector('#first').getBoundingClientRect();
        const box = document.querySelector('.ctvn-bubble-box');
        const rect = box.getBoundingClientRect();
        const text = box.firstElementChild;
        return { top: rect.top - img.top, width: rect.width, height: rect.height, imageWidth: img.width, imageHeight: img.height, overflow: box.dataset.overflow, textFits: text.scrollHeight <= box.clientHeight - 4 && text.scrollWidth <= box.clientWidth - 4 };
      });
      assert.ok(Math.abs(result.top - result.imageHeight * .4) < 1);
      assert.ok(Math.abs(result.width - result.imageWidth * .73) < 1);
      assert.ok(Math.abs(result.height - result.imageHeight * .125) < 1);
      assert.equal(result.overflow, 'false');
      assert.ok(result.textFits);
    }
  } finally { await page.close(); }
});

test('font responds to text length; impossible text opens in full without growing the box', async () => {
  const page = await fixture();
  try {
    await translate(page, [
      { id: 0, bbox: [50, 100, 450, 250], translation: 'Đi thôi!' },
      { id: 1, bbox: [500, 100, 900, 250], translation: paragraph },
      { id: 2, bbox: [50, 300, 100, 340], translation: paragraph.repeat(4), source_text: '原文' },
    ]);
    const boxes = page.locator('.ctvn-bubble-box');
    const sizes = await boxes.evaluateAll(elements => elements.map(el => parseFloat(getComputedStyle(el).fontSize)));
    assert.ok(sizes[0] > sizes[1], `Expected smaller type for longer text; sizes: ${sizes}`);
    assert.equal(await boxes.nth(2).getAttribute('data-overflow'), 'true');
    assert.equal(await boxes.nth(2).textContent(), '…');
    await boxes.nth(2).click();
    const detail = await page.evaluate(() => window.messages.at(-1));
    assert.equal(detail.type, 'SHOW_TRANSLATION_DETAIL');
    assert.equal(detail.translation, paragraph.repeat(4));
    assert.equal(detail.sourceText, '原文');
  } finally { await page.close(); }
});

test('mid-image selection, multiple images in one parent, and true original toggle', async () => {
  const page = await fixture();
  try {
    await translate(page, [{ id: 0, bbox: [50, 100, 450, 250], translation: 'Trang một' }]);
    await page.evaluate(() => window.scrollTo(0, document.querySelector('#second').offsetTop + 200));
    await translate(page, [{ id: 0, bbox: [500, 700, 900, 900], translation: 'Trang hai' }]);
    assert.equal(await page.locator('.ctvn-overlay-layer').count(), 2);
    assert.equal(await page.locator('.ctvn-bubble-box').count(), 2);
    assert.equal(await page.evaluate(() => document.querySelector('img[data-ctvn-active-target]').id), 'second');
    await page.evaluate(() => window.__setTranslationOriginal(true));
    assert.equal(await page.locator('.ctvn-overlay-layer:visible').count(), 0);
    await page.evaluate(() => window.__setTranslationOriginal(false));
    assert.equal(await page.locator('.ctvn-bubble-box').count(), 2);
    await page.evaluate(() => window.__setTranslationOriginal(true));
    await translate(page, [{ id: 0, bbox: [500, 700, 900, 900], translation: 'Dịch mới phải hiện' }]);
    assert.ok(await page.locator('.ctvn-bubble-box').last().isVisible());
  } finally { await page.close(); }
});

test('stale target IDs and invalid/outside boxes cannot draw on a different page', async () => {
  const page = await fixture();
  try {
    await page.evaluate(() => window.__renderRealTranslatedBlocks([{ id: 0, bbox: [0, 0, 100, 100] }], false, {}, 'old-document'));
    assert.equal(await page.locator('.ctvn-overlay-layer').count(), 0);
    await translate(page, [
      { id: 0, bbox: [200, 200, 100, 100] },
      { id: 1, bbox: [0, 0, null, 20] },
      { id: 2, bbox: [-50, -50, 1100, 2100], translation: 'Giới hạn trong ảnh' },
    ]);
    assert.equal(await page.locator('.ctvn-bubble-box').count(), 1);
    const inside = await page.evaluate(() => {
      const a = document.querySelector('#first').getBoundingClientRect();
      const b = document.querySelector('.ctvn-bubble-box').getBoundingClientRect();
      return b.left >= a.left && b.top >= a.top && b.right <= a.right + 1 && b.bottom <= a.bottom + 1;
    });
    assert.ok(inside);
  } finally { await page.close(); }
});

test('AMP image rules cannot hide the translated overlay', async () => {
  const page = await fixture();
  try {
    await page.addStyleTag({ content: '#pages > :not(img) { display:none !important }' });
    await translate(page, [{ id: 0, bbox: [50, 100, 450, 250], translation: 'Bản dịch phải hiện' }]);
    assert.ok(await page.locator('.ctvn-bubble-box').isVisible());
  } finally { await page.close(); }
});

test('lazy-loader replacing an image during translation keeps its result attached', async () => {
  const page = await fixture();
  try {
    await page.evaluate(() => {
      window.__triggerTranslateActivePage();
      const img = document.querySelector('#first');
      img.replaceWith(img.cloneNode(true));
      const request = window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').at(-1);
      window.__renderRealTranslatedBlocks([{ id: 0, bbox: [50, 100, 450, 250], translation: 'Đã dịch' }], false, { image_width: 1000, image_height: 2000 }, request.targetId);
    });
    assert.equal(await page.locator('.ctvn-bubble-box').count(), 1);
    const ack = await page.evaluate(() => window.messages.at(-1));
    assert.equal(ack.type, 'TRANSLATION_RENDER_RESULT');
    assert.equal(ack.count, 1);
  } finally { await page.close(); }
});

test('overlay follows document scrolling without refitting/replacing text each frame', async () => {
  const page = await fixture();
  try {
    await translate(page, [{ id: 0, bbox: [120, 800, 850, 1050], translation: paragraph }]);
    const initial = await page.locator('.ctvn-bubble-box').boundingBox();
    await page.evaluate(() => {
      window.savedBubble = document.querySelector('.ctvn-bubble-box');
      window.scrollTo(0, 100);
    });
    await page.waitForFunction(top => Math.abs(document.querySelector('.ctvn-bubble-box').getBoundingClientRect().top - (top - 100)) < 1, initial.y);
    assert.ok(await page.evaluate(() => window.savedBubble === document.querySelector('.ctvn-bubble-box')));
  } finally { await page.close(); }
});

test('auto translation queues nearby images serially, skips completed images and can stop', async () => {
  const page = await fixture();
  try {
    await page.evaluate(() => {
      const second = document.querySelector('#second');
      second.src += '#second';
      const third = second.cloneNode(true);
      third.id = 'third';
      third.src += '-third';
      second.after(third);
      window.__setAutoTranslate(true);
    });
    const requests = () => page.evaluate(() => window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST'));
    await page.waitForFunction(() => window.messages.some(x => x.type === 'TRANSLATE_PAGE_REQUEST'));
    assert.equal((await requests()).length, 1);
    await page.evaluate(() => window.scrollTo(0, document.querySelector('#second').offsetTop + 200));
    await page.waitForTimeout(400);
    assert.equal((await requests()).length, 1, 'Only one request may be in flight');
    await page.evaluate(() => {
      const request = window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').at(-1);
      window.__releaseTranslationTarget(request.targetId, true);
    });
    await page.waitForFunction(() => window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').length === 2);
    const queued = await requests();
    assert.notEqual(queued[0].imageUrl, queued[1].imageUrl);
    await page.evaluate(() => {
      window.__setAutoTranslate(false);
      const request = window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').at(-1);
      window.__releaseTranslationTarget(request.targetId, true);
      window.scrollTo(0, document.querySelector('#third').offsetTop);
    });
    await page.waitForTimeout(400);
    assert.equal((await requests()).length, 2, 'Stopping prevents further images being charged');
    await page.evaluate(() => { window.scrollTo(0, 0); window.__setAutoTranslate(true); });
    await page.waitForTimeout(400);
    assert.equal((await requests()).length, 2, 'Scrolling back must not request completed URLs');
    await page.evaluate(() => window.scrollTo(0, document.querySelector('#third').offsetTop));
    await page.waitForFunction(() => window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').length === 3);
  } finally { await page.close(); }
});

test('a failed auto translation pauses the queue instead of repeatedly retrying', async () => {
  const page = await fixture();
  try {
    await page.evaluate(() => window.__setAutoTranslate(true));
    await page.waitForFunction(() => window.messages.some(x => x.type === 'TRANSLATE_PAGE_REQUEST'));
    await page.evaluate(() => {
      const request = window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').at(-1);
      window.__releaseTranslationTarget(request.targetId, false);
      window.dispatchEvent(new Event('scroll'));
    });
    await page.waitForTimeout(500);
    assert.equal(await page.evaluate(() => window.messages.filter(x => x.type === 'TRANSLATE_PAGE_REQUEST').length), 1);
  } finally { await page.close(); }
});

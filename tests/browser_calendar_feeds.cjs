#!/usr/bin/env node
'use strict';

// Exercise the real subscription UI with deterministic API fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const FEED_ID = '10000000-0000-4000-8000-000000000001';
const STAGES = [
  {id: 71, name: 'Inbox', board_id: 7, board_name: 'Research & reports'},
  {id: 72, name: 'In progress', board_id: 7, board_name: 'Research & reports'},
  {id: 73, name: '<img src=x> Later', board_id: 7, board_name: 'Research & reports'},
  {id: 81, name: 'Inbox', board_id: 8, board_name: '<img src=x> Hub'},
  {id: 82, name: 'Waiting', board_id: 8, board_name: '<img src=x> Hub'},
];

async function main() {
  let feeds = [];
  let generation = 0;
  let submitted = null;
  let updated = null;
  const errors = [];
  const server = http.createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url, 'http://fixture').pathname;
      if (request.method === 'GET' && pathname === '/') {
        const modal = await fs.readFile(path.join(ROOT, 'templates/calendar_feeds.html'), 'utf8');
        response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
        response.end(`<!doctype html><html><head><meta charset="utf-8">
          <link rel="stylesheet" href="/static/tailwind.css">
          <link rel="stylesheet" href="/static/style.css">
          <script src="/static/base.js"></script><script src="/static/calendars.js"></script>
          </head><body class="bg-gray-100 p-6">
          <button id="open-all" data-open-calendar-feeds>Calendar subscriptions</button>
          <button id="open-hub" data-open-calendar-feeds data-board-id="7">Subscribe to this hub</button>
          ${modal}</body></html>`);
        return;
      }
      if (pathname.startsWith('/static/')) {
        const file = path.resolve(ROOT, `.${pathname}`);
        assert.ok(file.startsWith(`${ROOT}${path.sep}static${path.sep}`));
        response.writeHead(200, {'Content-Type': pathname.endsWith('.css') ? 'text/css' : 'text/javascript'});
        response.end(await fs.readFile(file));
        return;
      }
      response.setHeader('Content-Type', 'application/json');
      if (request.method === 'GET' && pathname === '/api/boards') {
        response.end(JSON.stringify([{id: 7, name: 'Research & reports'}, {id: 8, name: '<img src=x> Hub'}]));
        return;
      }
      if (request.method === 'GET' && pathname === '/api/calendar-feeds') {
        response.end(JSON.stringify(feeds));
        return;
      }
      if (request.method === 'GET' && pathname === '/api/calendar-feeds/stages') {
        response.end(JSON.stringify(STAGES));
        return;
      }
      if (pathname.startsWith('/api/calendar-feeds')) {
        assert.equal(request.headers['x-requested-with'], 'XMLHttpRequest');
        assert.equal(request.headers['x-csrf-token'], 'browser-calendar-csrf');
        if (request.method === 'POST') {
          if (!pathname.endsWith('/rotate')) {
            const chunks = [];
            for await (const chunk of request) chunks.push(chunk);
            submitted = JSON.parse(Buffer.concat(chunks).toString());
            feeds = [{id: FEED_ID, ...submitted,
                      stages: STAGES.filter(stage => submitted.stage_ids?.includes(stage.id)), board_name: 'Research & reports',
                      available: true, last_four: 'test'}];
          }
          generation++;
          response.statusCode = pathname.endsWith('/rotate') ? 200 : 201;
          response.end(JSON.stringify({...feeds[0], subscription_url:
            `http://127.0.0.1:${server.address().port}/calendar/${FEED_ID}.ics?token=test-secret-${generation}`}));
          return;
        }
        if (request.method === 'PATCH') {
          const chunks = [];
          for await (const chunk of request) chunks.push(chunk);
          updated = JSON.parse(Buffer.concat(chunks).toString());
          feeds[0] = {...feeds[0], ...updated,
                      stages: STAGES.filter(stage => updated.stage_ids?.includes(stage.id))};
          response.end(JSON.stringify(feeds[0]));
          return;
        }
        if (request.method === 'DELETE') {
          feeds = [];
          response.end(JSON.stringify({ok: true}));
          return;
        }
      }
      response.statusCode = 404;
      response.end(JSON.stringify({detail: 'Not found'}));
    } catch (error) {
      errors.push(error.message);
      response.statusCode = 500;
      response.end(JSON.stringify({detail: error.message}));
    }
  });

  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1100, height: 850}});
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.evaluate(() => { document.cookie = 'questline_csrf=browser-calendar-csrf; path=/'; });
    await page.locator('#open-hub').click();
    await page.locator('#calendar-feed-submit').waitFor();
    await page.waitForFunction(() => !document.getElementById('calendar-feed-fields').disabled);
    assert.equal(await page.locator('#calendar-feed-board').inputValue(), '7');
    assert.equal(await page.locator('#calendar-feed-board option').count(), 3);
    assert.equal(await page.locator('#calendar-feed-board img').count(), 0);
    const createStages = page.locator('#calendar-feed-stages');
    assert.equal(await createStages.locator('[data-calendar-all-stages]').isChecked(), true);
    assert.equal(await createStages.locator('[data-calendar-stage-id]:checked').count(), 3);
    assert.equal(await createStages.locator('img').count(), 0);
    const dialogBox = await page.locator('#calendar-feeds-modal > div').boundingBox();
    assert.ok(dialogBox.width <= 600, 'Subscription dialog must stay compact on desktop');
    const firstStageBox = await createStages.locator('label').nth(1).boundingBox();
    const secondStageBox = await createStages.locator('label').nth(2).boundingBox();
    assert.ok(secondStageBox.x > firstStageBox.x && Math.abs(secondStageBox.y - firstStageBox.y) < 1,
      'Stages must use two columns on desktop');
    await createStages.locator('[data-calendar-stage-id="72"]').uncheck();
    assert.equal(await createStages.locator('[data-calendar-all-stages]').isChecked(), false);
    await page.locator('#calendar-feed-name').fill('Thunderbird <img src=x>');
    await page.locator('#calendar-feed-assigned').check();
    await page.locator('#calendar-feed-submit').click();
    await page.locator('#calendar-feed-created:not(.hidden)').waitFor();
    assert.deepEqual(submitted, {name: 'Thunderbird <img src=x>', board_id: 7, assigned_only: true, stage_ids: [71, 73]});
    const original = await page.locator('#calendar-feed-url').inputValue();
    assert.match(original, /token=test-secret-1$/);
    assert.equal(await page.locator('#calendar-feeds-list img').count(), 0);
    await page.locator('#calendar-feed-copy').click();
    await page.waitForFunction(() => document.getElementById('calendar-feeds-feedback').textContent.includes('copied'));
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), original);
    if (process.env.QUESTLINE_BROWSER_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_BROWSER_SCREENSHOT, fullPage: true});
    }
    await page.locator('#calendar-feed-saved').click();
    assert.equal(await page.locator('#calendar-feed-url').inputValue(), '');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'calendar-feeds-close');
    await page.locator('[data-calendar-action="stages"]').click();
    const editStages = page.locator('#calendar-feed-edit-stages');
    assert.equal(await editStages.locator('[data-calendar-all-stages]').isChecked(), false);
    assert.equal(await editStages.locator('[data-calendar-stage-id="71"]').isChecked(), true);
    assert.equal(await editStages.locator('[data-calendar-stage-id="72"]').isChecked(), false);
    await editStages.locator('[data-calendar-all-stages]').check();
    assert.equal(await editStages.locator('[data-calendar-stage-id]:checked').count(), 3);
    await page.getByRole('button', {name: 'Save stages', exact: true}).click();
    await page.waitForFunction(() => document.getElementById('calendar-feed-edit-form').classList.contains('hidden'));
    assert.deepEqual(updated, {stage_ids: null});
    assert.equal(generation, 1, 'Changing stages must preserve the subscription credential');
    assert.equal(await page.locator('#calendar-feed-url').inputValue(), '');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.calendarAction), 'stages');
    await page.locator('[data-calendar-action="stages"]').click();
    await editStages.locator('[data-calendar-all-stages]').uncheck();
    assert.equal(await editStages.locator('[data-calendar-stage-id]:checked').count(), 0);
    await page.getByRole('button', {name: 'Save stages', exact: true}).click();
    assert.match(await page.locator('#calendar-feeds-error').innerText(), /Select at least one stage/);
    await editStages.locator('[data-calendar-stage-id="72"]').check();
    await page.getByRole('button', {name: 'Save stages', exact: true}).click();
    await page.waitForFunction(() => document.getElementById('calendar-feed-edit-form').classList.contains('hidden'));
    assert.deepEqual(updated, {stage_ids: [72]});
    assert.match(await page.locator('#calendar-feeds-list').innerText(), /Stages: In progress/);
    await page.locator('[data-calendar-action="stages"]').click();
    await editStages.locator('[data-calendar-all-stages]').check();
    await page.getByRole('button', {name: 'Cancel', exact: true}).click();
    assert.deepEqual(feeds[0].stage_ids, [72], 'Cancel must leave the saved selection intact');
    await page.locator('#calendar-feed-board').selectOption('8');
    assert.equal(await createStages.locator('[data-calendar-all-stages]').isChecked(), true);
    assert.equal(await createStages.locator('[data-calendar-stage-id]').count(), 2);
    await page.locator('#calendar-feed-board').selectOption('');
    assert.equal(await createStages.locator('[data-calendar-stage-id]').count(), 5);
    assert.equal(await createStages.locator('legend').count(), 2);
    assert.equal(await createStages.locator('img').count(), 0);
    await page.locator('[data-calendar-action="rotate"]').click();
    await page.waitForFunction(() => document.getElementById('calendar-feed-url').value.endsWith('test-secret-2'));
    assert.notEqual(await page.locator('#calendar-feed-url').inputValue(), original);
    await page.locator('#calendar-feeds-close').click();
    assert.equal(await page.locator('#calendar-feed-url').inputValue(), '');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'open-hub');
    await page.locator('#open-all').click();
    await page.waitForFunction(() => !document.getElementById('calendar-feed-fields').disabled);
    assert.equal(await page.locator('#calendar-feed-board').inputValue(), '');
    assert.equal(await createStages.locator('[data-calendar-all-stages]').isChecked(), true);
    await page.locator('[data-calendar-action="stages"]').click();
    assert.equal(await editStages.locator('[data-calendar-stage-id="72"]').isChecked(), true);
    assert.equal(await editStages.locator('[data-calendar-stage-id]:checked').count(), 1);
    await page.getByRole('button', {name: 'Cancel', exact: true}).click();
    assert.equal(await page.locator('#calendar-feed-url').inputValue(), '');
    assert.equal(await page.locator('#calendar-feeds-list').textContent().then(text => text.includes('test-secret')), false);
    await page.locator('[data-calendar-action="revoke"]').click();
    await page.waitForFunction(() => document.getElementById('calendar-feeds-list').textContent.includes('No calendar subscriptions'));
    assert.equal(await page.evaluate(() => document.activeElement.id), 'calendar-feeds-close');
    await page.setViewportSize({width: 375, height: 812});
    await page.locator('#calendar-feed-name').fill('Phone calendar');
    const box = await page.locator('#calendar-feed-form').boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 375, 'Subscription form must fit a phone viewport');
    const firstMobileStageBox = await createStages.locator('label').nth(1).boundingBox();
    const secondMobileStageBox = await createStages.locator('label').nth(2).boundingBox();
    assert.ok(secondMobileStageBox.y > firstMobileStageBox.y && Math.abs(secondMobileStageBox.x - firstMobileStageBox.x) < 1,
      'Stages must use one column on mobile');
    if (process.env.QUESTLINE_BROWSER_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_BROWSER_SCREENSHOT.replace(/\.png$/, '-mobile.png'), fullPage: true});
    }
    await page.keyboard.press('Escape');
    assert.ok(await page.locator('#calendar-feeds-modal').evaluate(element => element.classList.contains('hidden')));
    assert.deepEqual(errors, []);
    console.log('Calendar subscription browser checks passed.');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => { console.error(error); process.exit(1); });

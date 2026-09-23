#!/usr/bin/env node
'use strict';

/* Optional, standalone real-browser regression suite (no app/DB required).
 * Run: node tests/browser_stage_drag.cjs
 * Requires the already-installed playwright package and Chromium. Override its
 * executable with PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH; HEADLESS=0 shows the UI.
 * Fetches the exact Sortable CDN asset pinned in templates/base.html once via
 * Playwright's request client, then fulfills that same URL from memory. Nothing
 * is vendored or written to disk. CDN/setup failures fail rather than skip.
 * All gestures use browser input; no controller callbacks are invoked/mocked.
 */
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium, request } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const BOUNDARY = '[data-stage-insert-position="1"]';
const stage = id => `[data-stage-column-id="${id}"]`;
const grip = id => `${stage(id)} [data-stage-drag-handle] .stage-drag-grip`;
const task = id => `.board-task-card[data-task-id="${id}"]`;
const slot = (row, position) => `[data-stage-slot][data-stage-row="${row}"][data-stage-slot-position="${position}"]`;
const placement = (id, row, position) => ({ id, row, position });
const INSERTED = [placement(1, 0, 0), placement(2, 1, 0), placement(5, 0, 1),
  placement(3, 0, 2), placement(4, 1, 2), placement(6, 0, 3)];
const OCCUPIED = [placement(1, 0, 0), placement(2, 1, 0), placement(5, 0, 1),
  placement(4, 1, 1), placement(6, 0, 2), placement(3, 1, 2)];
const SAVE_ALERT = 'Unable to save or refresh the stage layout. Please reload the board before trying again.';
const COLLAPSE_KEY = 'questline-board-1-collapsed-stages';
const calendarDay = date => `[data-calendar-date="${date}"]`;
const calendarDropzone = date => `${calendarDay(date)} [data-calendar-dropzone]`;
const calendarTask = (date, id = 101) => `${calendarDay(date)} [data-calendar-task][data-task-id="${id}"]`;
const placementsOf = stages => stages.map(({ id, row, position }) => ({ id, row, position }));

function initialStages() {
  return [
    [1, 0, 0, [101, 102, 103]], [2, 1, 0, [201]],
    [3, 0, 1, [301, 302]], [4, 1, 1, [401]],
    [5, 0, 2, [501]], [6, 1, 2, [601]],
  ].map(([id, row, position, ids]) => ({
    id, board_id: 1, name: id === 6 ? 'Filtered log' : `Stage ${id}`,
    row, position, is_log: id === 6, filter_id: null,
    tasks: ids.map((taskId, index) => ({
      id: taskId, board_id: 1, stage_id: id, position: index,
      title: `Objective ${taskId}`, done: false, description: '', checklist: [],
      custom_field_values: {}, due_date: null, recurrence: null,
    })),
  }));
}

function calendarStages() {
  const stages = initialStages();
  stages[0].tasks[0].due_date = '2026-09-01';
  stages[0].tasks[0].recurrence = { frequency: 'daily', next_run_on: '2026-09-04' };
  stages[0].tasks[1].due_date = '2026-09-01';
  return stages;
}

async function fixtureHtml(sortableUrl, role) {
  // Keep the actual template's data attributes, surface nodes, and script order.
  const template = await fs.readFile(path.join(ROOT, 'templates/board.html'), 'utf8');
  const content = template.split('{% block content %}')[1].split('{% endblock %}')[0]
    .replace('{{ board.id }}', '1')
    .replace('{{ boards | tojson }}', '[{"id":1,"name":"Browser fixture"}]')
    .replace('{{ board.name | tojson }}', '"Browser fixture"')
    .replace('{{ (board.color or "") | tojson }}', '"#3b82f6"')
    .replace('{{ board_role | tojson }}', JSON.stringify(role));
  assert.ok(!content.includes('{{'), 'Unresolved board template expression');
  return `<!doctype html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/static/tailwind.css">
    <link rel="stylesheet" href="/static/style.css">
    <script src="/static/base.js"></script><script src="${sortableUrl}"></script>
    </head><body class="min-h-screen text-gray-900">
    <nav class="h-16">Isolated browser regression fixture</nav>${content}</body></html>`;
}

async function createFixture(html) {
  const state = { stages: initialStages(), writes: [], errors: [], role: 'owner', reorderFailure: null };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const json = (data, status = 200) => {
      res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      res.end(JSON.stringify(data));
    };
    try {
      if (req.method === 'GET' && url.pathname === '/') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(html[state.role]);
      } else if (req.method === 'GET' && url.pathname.startsWith('/static/')) {
        const file = path.resolve(ROOT, `.${url.pathname}`);
        assert.ok(file.startsWith(`${ROOT}${path.sep}static${path.sep}`));
        const bytes = await fs.readFile(file);
        res.writeHead(200, { 'Content-Type': file.endsWith('.css') ? 'text/css' : 'text/javascript' });
        res.end(bytes);
      } else if (req.method === 'GET' && url.pathname === '/api/stages') {
        json(state.stages);
      } else if (req.method === 'GET' && ['/api/task-types', '/api/filters'].includes(url.pathname)) {
        json([]);
      } else if (req.method === 'GET' && url.pathname === '/api/boards/1/members') {
        json({ current_role: state.role, members: [] });
      } else if (req.method !== 'GET' && url.pathname.startsWith('/api/')) {
        let raw = '';
        for await (const chunk of req) raw += chunk;
        const body = JSON.parse(raw || '{}');
        state.writes.push({ method: req.method, path: url.pathname, body });
        if (req.method === 'PUT' && url.pathname === '/api/stages/reorder') {
          if (state.reorderFailure === 'http') {
            json({ detail: 'Intentional fixture reorder failure' }, 503);
            return;
          }
          assert.equal(body.stages.length, state.stages.length);
          assert.equal(new Set(body.stages.map(p => p.id)).size, state.stages.length);
          state.stages = body.stages.map(p => {
            const original = state.stages.find(s => s.id === p.id);
            assert.ok(original, `Unknown stage ${p.id}`);
            return { ...original, ...p };
          });
          json({ ok: true });
        } else if (req.method === 'PUT' && url.pathname === '/api/tasks/reorder') {
          const tasks = new Map(state.stages.flatMap(s => s.tasks).map(t => [t.id, t]));
          state.stages.forEach(s => {
            s.tasks = s.id === body.stage_id
              ? body.ids.map((id, position) => ({ ...tasks.get(id), stage_id: s.id, position }))
              : s.tasks.filter(t => !body.ids.includes(t.id));
          });
          json({ ok: true });
        } else if (req.method === 'PUT' && /^\/api\/tasks\/\d+$/.test(url.pathname)) {
          const current = state.stages.flatMap(s => s.tasks).find(t => t.id === Number(url.pathname.split('/').pop()));
          assert.ok(current, 'Updated task exists');
          Object.assign(current, body);
          json(current);
        } else if (req.method === 'PUT' && /^\/api\/stages\/\d+$/.test(url.pathname)) {
          // Title blur legitimately saves the unchanged title; it isn't a drag.
          const current = state.stages.find(s => s.id === Number(url.pathname.split('/').pop()));
          Object.assign(current, body);
          json(current);
        } else {
          throw new Error(`Unexpected API write: ${req.method} ${url.pathname}`);
        }
      } else if (url.pathname === '/favicon.ico') {
        res.writeHead(204); res.end();
      } else {
        throw new Error(`Unexpected request: ${req.method} ${url.pathname}`);
      }
    } catch (error) {
      state.errors.push(error.message);
      json({ detail: error.message }, 500);
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { state, server, url: `http://127.0.0.1:${server.address().port}` };
}

async function ready(page, role = 'owner') {
  await page.waitForFunction(role => {
    if (!document.querySelector('#board-calendar-view').classList.contains('hidden')) {
      const targets = [...document.querySelectorAll('[data-calendar-dropzone]')];
      return window.Sortable && targets.length === 42 && targets.every(el => {
        const sortable = Sortable.get(el);
        return role === 'viewer' ? !sortable : sortable && !sortable.option('disabled');
      });
    }
    if (!document.querySelector('[data-stage-column-id]')) return false;
    if (role === 'viewer') {
      return window.Sortable && [...document.querySelectorAll('[data-stage-slot], [data-stage-insert-position], .board-stage-body')]
        .every(el => !Sortable.get(el));
    }
    const targets = [...document.querySelectorAll('[data-stage-slot], [data-stage-insert-position]')];
    return targets.length > 0 && targets.every(el => {
      const s = window.Sortable?.get(el);
      return s && !s.option('disabled');
    }) && !document.querySelector('#board-stages-view.stage-dragging');
  }, role);
}

async function point(page, selector, xFraction = 0.5, yFraction = 0.5) {
  const box = await page.locator(selector).boundingBox();
  assert.ok(box && box.width && box.height, `Visible target required: ${selector}`);
  return { x: box.x + box.width * xFraction, y: box.y + box.height * yFraction };
}

async function move(page, to) {
  await page.mouse.move(to.x, to.y, { steps: 18 });
  // Native dragover is delivered on subsequent movements after dragstart.
  await page.mouse.move(to.x + 1, to.y);
  await page.mouse.move(to.x, to.y);
  await page.waitForTimeout(180);
}

async function startDrag(page, selector) {
  const from = await point(page, selector);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 9, from.y + 3, { steps: 4 });
  await page.waitForTimeout(80);
}

async function stageHover(page, id, target, active = true) {
  const source = await page.locator(stage(id)).elementHandle();
  const before = await source.boundingBox();
  const parent = await source.evaluate(el => ({ ...el.parentElement.dataset }));
  const destination = await point(page, target);
  await startDrag(page, grip(id));
  await page.waitForSelector('#board-stages-view.stage-dragging');
  await move(page, destination);
  if (active) await page.waitForSelector(`${target}.stage-drop-active`);
  else assert.equal(await page.locator('.stage-drop-active').count(), 0, 'Invalid target is not highlighted');
  assert.equal(await source.evaluate(el => el.isConnected), true, 'Source stays connected during drag');
  assert.deepEqual(await source.evaluate(el => ({ ...el.parentElement.dataset })), parent,
    'Rejected Sortable move keeps source in original slot');
  const after = await source.boundingBox();
  for (const key of ['x', 'y', 'width', 'height']) {
    assert.ok(Math.abs(after[key] - before[key]) < 1, `Stable source geometry: ${key}`);
  }
  await source.dispose();
}

async function settled(page) {
  await page.waitForFunction(() => !window.Sortable.active);
  await ready(page);
  // Bounded negative-assertion window also covers deferred two-frame saves.
  await page.waitForTimeout(250);
}

async function expectStageWrite(page, state, expected) {
  await page.waitForResponse(r => r.url().endsWith('/api/stages/reorder') && r.request().method() === 'PUT',
    { timeout: 4000 });
  await settled(page);
  assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/stages/reorder', body: { stages: expected } }]);
  await assertLayout(page, expected);
}

async function assertLayout(page, expected) {
  assert.equal(await page.locator('[data-stage-column-id]').count(), expected.length);
  for (const p of expected) {
    assert.equal(await page.locator(`${slot(p.row, p.position)} > ${stage(p.id)}`).count(), 1,
      `Rerendered stage ${p.id} at row ${p.row}, position ${p.position}`);
  }
}

async function assertCollapsed(page, id, collapsed) {
  const toggle = page.locator(`${stage(id)} .stage-collapse-toggle`);
  assert.equal(await toggle.getAttribute('aria-expanded'), String(!collapsed));
  assert.equal(await page.locator(`${stage(id)} .board-stage-body`).count(), collapsed ? 0 : 1);
  assert.equal(await page.locator(`${stage(id)} .stage-collapsed-title`).count(), collapsed ? 1 : 0);
  const box = await page.locator(stage(id)).boundingBox();
  assert.equal(box.width, collapsed ? 48 : 288);
  if (collapsed) {
    assert.equal(await page.locator(`${stage(id)} .stage-collapsed-title`).evaluate(el => getComputedStyle(el).writingMode), 'vertical-rl');
    assert.equal(await page.locator(`${stage(id)} [data-action="toggle-stage-menu"], ${stage(id)} .board-task-card`).count(), 0);
  }
}

async function assertTaskHighlight(page, selector) {
  assert.equal(await page.locator('.task-drop-active').count(), 1);
  assert.equal(await page.locator(`${selector}.task-drop-active`).count(), 1);
  const style = await page.locator(selector).evaluate(el => ({
    color: getComputedStyle(el).outlineColor,
    width: getComputedStyle(el).outlineWidth,
    style: getComputedStyle(el).outlineStyle,
  }));
  assert.deepEqual(style, { color: 'rgb(125, 211, 252)', width: '3px', style: 'solid' });
  assert.equal(await page.locator('.task-ghost').first().evaluate(el => getComputedStyle(el).opacity), '0.4');
  assert.equal(await page.locator('.stage-drop-active, #board-stages-view.stage-dragging').count(), 0);
}

function touchEvent(cdp, type, point) {
  return cdp.send('Input.dispatchTouchEvent', {
    type, touchPoints: point ? [{ ...point, id: 1, radiusX: 2, radiusY: 2, force: 1 }] : [],
  });
}

async function touchHover(page, cdp, id, target) {
  const handle = page.locator(grip(id));
  assert.equal(await handle.evaluate(el => el.tagName), 'BUTTON');
  const box = await handle.boundingBox();
  assert.equal(box.width, 32);
  assert.equal(box.height, 32);
  const from = await point(page, grip(id));
  const to = await point(page, target);
  await touchEvent(cdp, 'touchStart', from);
  assert.equal(await page.evaluate(() => window.dragEvents.some(e =>
    e.type === 'pointerdown' && e.pointerType === 'touch' && e.target.includes('stage-drag-grip'))), true,
  'Touch at the actual grip center reaches the grip, not the title');
  for (let i = 1; i <= 20; i++) {
    await touchEvent(cdp, 'touchMove', {
      x: from.x + (to.x - from.x) * i / 20, y: from.y + (to.y - from.y) * i / 20,
    });
    await page.waitForTimeout(25);
  }
  await page.waitForSelector(`${target}.stage-drop-active`);
}

async function dropStage(page, state, expected) {
  // Install the response waiter before releasing the mouse.
  await Promise.all([expectStageWrite(page, state, expected), page.mouse.up()]);
}

async function assertNoStageStart(page) {
  assert.equal(await page.evaluate(() => window.dragEvents.filter(e => e.type === 'start' && e.kind === 'stage').length), 0);
  assert.equal(await page.locator('.stage-drop-active, #board-stages-view.stage-dragging').count(), 0);
}

async function main() {
  let browser, api, fixture;
  let failures = 0;
  let passes = 0;
  try {
    const base = await fs.readFile(path.join(ROOT, 'templates/base.html'), 'utf8');
    const sortableUrl = base.match(/<script src="(https:\/\/[^\"]+\/sortablejs@[^\"]+\/Sortable\.min\.js)"/)[1];
    api = await request.newContext();
    const asset = await api.get(sortableUrl, { timeout: 30000 });
    assert.equal(asset.status(), 200, `Fetch pinned Sortable: ${sortableUrl}`);
    const sortableBytes = await asset.body();
    fixture = await createFixture({
      owner: await fixtureHtml(sortableUrl, 'owner'),
      viewer: await fixtureHtml(sortableUrl, 'viewer'),
    });
    browser = await chromium.launch({
      headless: process.env.HEADLESS !== '0',
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
        ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
    });
    console.log(`Chromium ${browser.version()}; ${sortableUrl}; in-memory fixture ${fixture.url}`);

    async function test(name, run, options = {}) {
      const { touch = false, role = 'owner', stages = initialStages(), expectedDialogs = [],
        viewport = { width: 1600, height: 1000 }, reorderFailure = null, view = 'stages' } = options;
      fixture.state.stages = structuredClone(stages);
      fixture.state.writes = [];
      fixture.state.errors = [];
      fixture.state.role = role;
      fixture.state.reorderFailure = reorderFailure;
      const context = await browser.newContext({ viewport, hasTouch: touch });
      const page = await context.newPage();
      page.setDefaultTimeout(5000);
      const errors = [];
      const dialogs = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', async dialog => {
        dialogs.push({ type: dialog.type(), message: dialog.message() });
        await dialog.dismiss();
      });
      await context.route(sortableUrl, route => route.fulfill({ contentType: 'text/javascript', body: sortableBytes }));
      if (reorderFailure === 'network') {
        await context.route('**/api/stages/reorder', async route => {
          if (fixture.state.reorderFailure !== 'network') return route.continue();
          const req = route.request();
          fixture.state.writes.push({ method: req.method(), path: '/api/stages/reorder', body: req.postDataJSON() });
          // An explicit browser network abort avoids Chromium transparently
          // retrying idempotent PUTs when a fixture server closes its socket.
          await route.abort('failed');
        });
      }
      await page.addInitScript(() => {
        window.dragEvents = [];
        for (const type of ['choose', 'unchoose', 'start', 'end', 'dragstart', 'drop', 'dragend', 'pointerdown', 'pointercancel', 'touchstart', 'touchcancel']) {
          document.addEventListener(type, event => {
            const item = event.item || event.target;
            window.dragEvents.push({ type, kind: item.matches?.('[data-stage-column-id]') ? 'stage' : 'task',
              id: item.dataset?.stageColumnId || item.dataset?.taskId,
              originalType: event.originalEvent?.type, x: event.clientX, y: event.clientY,
              target: item.className, pointerType: event.pointerType });
          }, true);
        }
      });
      try {
        await page.goto(fixture.url + (view === 'calendar' ? '/?view=calendar&month=2026-09' : ''));
        await ready(page, role);
        // Initial metadata requests each render the surface; await their completion.
        await page.waitForLoadState('networkidle');
        await ready(page, role);
        await run(page, fixture.state, context);
        assert.deepEqual(errors, [], 'Browser errors');
        assert.deepEqual(dialogs, expectedDialogs.map(message => ({ type: 'alert', message })), 'Expected alerts');
        assert.deepEqual(fixture.state.errors, [], 'Fixture errors');
        passes++;
        console.log(`PASS ${name}`);
      } catch (error) {
        failures++;
        console.error(`FAIL ${name}\n${error.stack}`);
        console.error(JSON.stringify({ writes: fixture.state.writes, browserErrors: errors, dialogs,
          fixtureErrors: fixture.state.errors, browser: await page.evaluate(() => ({
            events: window.dragEvents,
            sortableActive: !!window.Sortable?.active,
            sortableDraggedId: window.Sortable?.dragged?.dataset.stageColumnId || null,
            chosenStageIds: [...document.querySelectorAll('.sortable-chosen')].map(el => el.dataset.stageColumnId),
            stageDragging: !!document.querySelector('#board-stages-view.stage-dragging'),
            highlightedTargets: [...document.querySelectorAll('.stage-drop-active')].map(el => ({ ...el.dataset })),
            scrollLeft: document.querySelector('#board-stages-view')?.scrollLeft,
          })).catch(() => null) }, null, 2));
      } finally {
        await context.close();
      }
    }

    await test('double-click either grip collapses and expands the pair without writing or dragging', async (page, state) => {
      const original = structuredClone(state.stages);
      const before = await page.locator(stage(3)).boundingBox();
      await page.locator(grip(1)).click();
      await assertCollapsed(page, 1, false);
      await page.locator(grip(1)).dblclick();
      await settled(page);
      await assertCollapsed(page, 1, true);
      await assertCollapsed(page, 2, true);
      await assertCollapsed(page, 3, false);
      const after = await page.locator(stage(3)).boundingBox();
      assert.equal(before.x - after.x, 240, 'The entire column shrinks, not just its header');
      await page.locator(grip(2)).dblclick();
      await settled(page);
      await assertCollapsed(page, 1, false);
      await assertCollapsed(page, 2, false);
      assert.equal(await page.locator('#stage-1 .board-task-card').count(), 3);
      assert.deepEqual(state.stages, original);
      assert.deepEqual(state.writes, []);
      await assertNoStageStart(page);
      assert.equal(await page.locator('#stage-1').evaluate(el => !!Sortable.get(el)), true);
    });

    await test('collapse works with an open menu, keyboard activation, calendar switches, and log stages', async (page, state) => {
      await page.locator(`${stage(3)} [data-action="toggle-stage-menu"]`).click();
      await ready(page);
      await page.locator(grip(6)).dblclick();
      await settled(page);
      await assertCollapsed(page, 5, true);
      await assertCollapsed(page, 6, true);
      assert.equal(await page.locator('[data-action="delete-stage"]').count(), 0, 'Menu closes during collapse');
      assert.equal(await page.locator(grip(6)).evaluate(el => el === document.activeElement), true);
      await page.keyboard.press('Space');
      await settled(page);
      await assertCollapsed(page, 5, false);
      await assertCollapsed(page, 6, false);
      await page.keyboard.press('Enter');
      await settled(page);
      await assertCollapsed(page, 6, true);
      await page.locator('[data-action="toggle-board-view"]').click();
      await page.locator('[data-action="toggle-board-view"]').click();
      await settled(page);
      await assertCollapsed(page, 5, true);
      await assertCollapsed(page, 6, true);
      assert.deepEqual(state.writes, []);
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertCollapsed(page, 5, true);
      await assertCollapsed(page, 6, true);
      await page.locator(grip(5)).dblclick();
      await settled(page);
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertCollapsed(page, 5, false);
      await assertCollapsed(page, 6, false);
      assert.deepEqual(state.writes, []);
    });

    await test('restored collapse survives metadata arriving before stages and prunes stale IDs', async (page, state) => {
      await page.evaluate(key => localStorage.setItem(key, '[1,999999,"3",null,-1,1.5]'), COLLAPSE_KEY);
      await page.route('**/api/stages?*', async route => {
        await new Promise(resolve => setTimeout(resolve, 400));
        await route.continue();
      });
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertCollapsed(page, 1, true);
      await assertCollapsed(page, 2, true);
      await assertCollapsed(page, 3, false);
      assert.deepEqual(await page.evaluate(key => JSON.parse(localStorage.getItem(key)), COLLAPSE_KEY), [1, 2]);
      state.stages = state.stages.filter(s => s.id !== 1 && s.id !== 2);
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      assert.equal(await page.evaluate(key => localStorage.getItem(key), COLLAPSE_KEY), null);
      assert.deepEqual(state.writes, []);
    });

    await test('collapse preferences are isolated per board in the same browser', async (page, state) => {
      await page.locator(grip(1)).dblclick();
      await settled(page);
      await page.route(fixture.url + '/', async route => {
        const response = await route.fetch();
        await route.fulfill({ response, body: (await response.text()).replace('data-board-id="1"', 'data-board-id="2"') });
      });
      await page.route('**/api/boards/2/members', route => route.fulfill({
        json: { current_role: 'owner', members: [] },
      }));
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertCollapsed(page, 1, false);
      await page.locator(grip(3)).dblclick();
      await settled(page);
      await page.unroute(fixture.url + '/');
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertCollapsed(page, 1, true);
      await assertCollapsed(page, 3, false);
      assert.deepEqual(state.writes, []);
    });

    for (const stored of ['not json', 'null', '{}']) {
      await test(`invalid collapse preference (${stored}) does not break the board`, async (page, state) => {
        await page.evaluate(({ key, stored }) => localStorage.setItem(key, stored), { key: COLLAPSE_KEY, stored });
        await page.reload();
        await page.waitForLoadState('networkidle');
        await ready(page);
        await assertCollapsed(page, 1, false);
        await page.locator(grip(1)).dblclick();
        await settled(page);
        await assertCollapsed(page, 1, true);
        assert.deepEqual(await page.evaluate(key => JSON.parse(localStorage.getItem(key)), COLLAPSE_KEY), [1, 2]);
        assert.deepEqual(state.writes, []);
      });
    }

    await test('unavailable collapse storage falls back to in-memory toggles', async (page, state) => {
      await page.addInitScript(key => {
        for (const method of ['getItem', 'setItem', 'removeItem']) {
          const original = Storage.prototype[method];
          Storage.prototype[method] = function(storageKey, ...args) {
            if (storageKey === key) throw new DOMException('Storage unavailable', 'SecurityError');
            return original.call(this, storageKey, ...args);
          };
        }
      }, COLLAPSE_KEY);
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await page.locator(grip(1)).dblclick();
      await settled(page);
      await assertCollapsed(page, 1, true);
      await page.locator(grip(2)).dblclick();
      await settled(page);
      await assertCollapsed(page, 1, false);
      assert.deepEqual(state.writes, []);
    });

    await test('collapsed stage insertion preserves collapse through promotion and column shifts', async (page, state) => {
      await page.locator(grip(5)).dblclick();
      await settled(page);
      await page.locator(grip(3)).dblclick();
      await settled(page);
      await stageHover(page, 5, BOUNDARY);
      await dropStage(page, state, INSERTED);
      for (const id of [3, 4, 5, 6]) await assertCollapsed(page, id, true);
      await assertCollapsed(page, 1, false);
      await page.locator(grip(5)).dblclick();
      await settled(page);
      await assertCollapsed(page, 5, false);
      await assertCollapsed(page, 6, true);
    });

    await test('moving a collapsed stage collapses its new companion and displacement column', async (page, state) => {
      await page.locator(grip(5)).dblclick();
      await settled(page);
      await stageHover(page, 5, slot(0, 1));
      await dropStage(page, state, OCCUPIED);
      for (const id of [3, 4, 5, 6]) await assertCollapsed(page, id, true);
      await page.locator(grip(4)).dblclick();
      await settled(page);
      await assertCollapsed(page, 4, false);
      await assertCollapsed(page, 5, false);
      await assertCollapsed(page, 3, true);
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertCollapsed(page, 5, false);
      await assertCollapsed(page, 4, false);
      await assertCollapsed(page, 3, true);
      await assertCollapsed(page, 6, true);
    });

    await test('single collapsed stage hides creation controls but keeps the empty lower drop slot', async (page, state) => {
      await page.locator(grip(5)).dblclick();
      await settled(page);
      assert.equal(await page.locator(`${slot(1, 2)} [data-action="open-new-stage"]`).count(), 0);
      await page.locator(grip(5)).dblclick();
      await settled(page);
      assert.equal(await page.locator(`${slot(1, 2)} [data-action="open-new-stage"]`).count(), 1);
      await page.locator(grip(5)).dblclick();
      await settled(page);
      await stageHover(page, 3, slot(1, 2));
      await dropStage(page, state, [placement(1, 0, 0), placement(2, 1, 0), placement(4, 0, 1), placement(5, 0, 2), placement(3, 1, 2)]);
      await assertCollapsed(page, 5, true);
      await assertCollapsed(page, 3, true);
      await assertCollapsed(page, 4, false);
    }, { stages: initialStages().filter(s => s.id !== 6) });

    await test('viewers can collapse pairs without enabling editing or Sortables', async (page, state) => {
      await page.locator(`${stage(1)} .stage-collapse-toggle`).dblclick();
      await ready(page, 'viewer');
      await assertCollapsed(page, 1, true);
      await assertCollapsed(page, 2, true);
      await page.keyboard.press('Enter');
      await ready(page, 'viewer');
      await assertCollapsed(page, 1, false);
      assert.equal(await page.locator('.stage-drag-grip, [data-action="toggle-stage-menu"]').count(), 0);
      assert.equal(await page.locator(`${stage(1)} [data-field="stage-name"]`).isDisabled(), true);
      assert.deepEqual(state.writes, []);
    }, { role: 'viewer' });

    await test('touch double-tap toggles a pair without starting a drag', async (page, state) => {
      await page.locator(grip(1)).tap();
      await page.locator(grip(1)).tap();
      await settled(page);
      await assertCollapsed(page, 1, true);
      await assertCollapsed(page, 2, true);
      await page.locator(grip(2)).tap();
      await page.locator(grip(2)).tap();
      await settled(page);
      await assertCollapsed(page, 1, false);
      await assertNoStageStart(page);
      assert.deepEqual(state.writes, []);
    }, { touch: true });

    await test('failed stage save retains collapsed source and leaves other columns expanded', async (page, state) => {
      const original = placementsOf(state.stages);
      await page.locator(grip(5)).dblclick();
      await settled(page);
      await stageHover(page, 5, slot(0, 1));
      await page.mouse.up();
      await settled(page);
      await assertLayout(page, original);
      await assertCollapsed(page, 5, true);
      await assertCollapsed(page, 6, true);
      await assertCollapsed(page, 3, false);
      await assertCollapsed(page, 4, false);
      assert.equal(state.writes.length, 1);
    }, { reorderFailure: 'http', expectedDialogs: [SAVE_ALERT] });

    await test('collapsed titles show each stage task count, including zero and completed tasks', async (page, state) => {
      await page.locator(grip(1)).dblclick();
      await settled(page);
      await page.locator(grip(6)).dblclick();
      await settled(page);
      for (const [id, expected] of [[1, 'Stage 1 (3)'], [2, 'Stage 2 (0)'], [6, 'Filtered log (1)']]) {
        const title = page.locator(`${stage(id)} .stage-collapsed-title`);
        assert.equal(await title.textContent(), expected);
        assert.equal(await title.getAttribute('title'), expected);
      }
      state.stages[0].tasks.pop();
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      assert.equal(await page.locator(`${stage(1)} .stage-collapsed-title`).textContent(), 'Stage 1 (2)');
      assert.deepEqual(state.writes, []);
    }, { stages: initialStages().map(s => ({
      ...s,
      tasks: s.id === 2 ? [] : s.tasks.map((t, i) => ({ ...t, done: i === 0 })),
    })) });

    await test('long collapsed titles stay inside narrow headers and render as text', async (page, state) => {
      await page.locator(grip(1)).dblclick();
      await settled(page);
      const title = page.locator(`${stage(1)} .stage-collapsed-title`);
      const expected = `${state.stages[0].name} (${state.stages[0].tasks.length})`;
      assert.equal(await title.textContent(), expected);
      assert.equal(await title.getAttribute('title'), expected);
      assert.equal(await title.locator('b').count(), 0);
      const titleBox = await title.boundingBox();
      const stageBox = await page.locator(stage(1)).boundingBox();
      assert.ok(titleBox.y + titleBox.height <= stageBox.y + stageBox.height);
      assert.ok(titleBox.width < stageBox.width);
      await page.evaluate(() => document.documentElement.classList.add('dark'));
      await assertCollapsed(page, 1, true);
      assert.deepEqual(state.writes, []);
    }, { stages: initialStages().map(s => s.id === 1 ? { ...s, name: '<b>A very long stage title & '.repeat(15) } : s) });

    await test('compact stage headers center titles with their grip and menu', async page => {
      for (const id of [1, 6]) {
        const header = await page.locator(`${stage(id)} [data-stage-drag-handle]`).boundingBox();
        const title = await page.locator(`${stage(id)} [data-field="stage-name"]`).boundingBox();
        const handle = await page.locator(grip(id)).boundingBox();
        const menu = await page.locator(`${stage(id)} [data-action="toggle-stage-menu"]`).boundingBox();
        const center = box => box.y + box.height / 2;
        assert.ok(Math.abs(center(title) - center(handle)) < 0.5, 'Title and grip are vertically centered');
        assert.ok(Math.abs(center(title) - center(menu)) < 0.5, 'Title and menu are vertically centered');
        assert.equal(handle.height, 32, 'Keep the existing touch target height');
        if (id === 1) assert.ok(header.height <= 46, 'Regular stage header is more compact');
      }
    });

    await test('CDP touchcancel before movement clears stage 5 selection before dragging stage 3', async (page, state, context) => {
      const cdp = await context.newCDPSession(page);
      try {
        const original = placementsOf(state.stages);
        await touchEvent(cdp, 'touchStart', await point(page, grip(5)));
        assert.equal(await page.evaluate(() => Sortable.dragged?.dataset.stageColumnId), '5',
          'Touch prepared stage 5 before any movement');
        assert.equal(await page.locator(`${stage(5)}.sortable-chosen`).count(), 1);
        await assertNoStageStart(page);
        // No touchMove: cancellation must work after choose but before onStart.
        await touchEvent(cdp, 'touchCancel');
        assert.equal(await page.evaluate(() => window.dragEvents.some(e => e.type === 'touchcancel')), true);
        await settled(page);
        await assertNoStageStart(page);
        assert.deepEqual(state.writes, []);
        assert.deepEqual(await page.evaluate(() => ({
          dragged: !!Sortable.dragged,
          chosen: document.querySelectorAll('.sortable-chosen').length,
        })), { dragged: false, chosen: 0 }, 'Pre-start cancellation releases the prepared Sortable selection');
        await assertLayout(page, original);

        // A different source exposes stale selection: reusing stage 5 would
        // conceal a prepared drag that survived cancellation.
        await touchHover(page, cdp, 3, '[data-stage-insert-position="0"]');
        assert.deepEqual(await page.evaluate(() => window.dragEvents
          .filter(e => e.type === 'start' && e.kind === 'stage').map(e => e.id)), ['3']);
        const expected = [placement(3, 0, 0), placement(1, 0, 1), placement(2, 1, 1),
          placement(4, 0, 2), placement(5, 0, 3), placement(6, 1, 3)];
        await Promise.all([expectStageWrite(page, state, expected), touchEvent(cdp, 'touchEnd')]);
      } finally {
        await cdp.detach();
      }
    }, { touch: true });

    await test('native insert shifts both rows, promotes source lower stage, and survives page reload', async (page, state) => {
      await stageHover(page, 5, BOUNDARY);
      await dropStage(page, state, INSERTED);
      assert.equal(await page.evaluate(() => window.dragEvents.some(e =>
        e.type === 'end' && e.kind === 'stage' && e.originalType === 'drop')), true,
      'Mouse exercised native HTML drag/drop');
      await page.reload();
      await page.waitForLoadState('networkidle');
      await ready(page);
      await assertLayout(page, INSERTED);
      assert.equal(state.writes.length, 1, 'Reload only reads the persisted fixture layout');
    });

    await test('occupied slot displaces target below promoted source', async (page, state) => {
      await stageHover(page, 5, slot(0, 1));
      await dropStage(page, state, OCCUPIED);
    });

    await test('same-slot drop leaves both rows unchanged and sends no write', async (page, state) => {
      const original = placementsOf(state.stages);
      await stageHover(page, 5, slot(0, 2));
      await page.mouse.up();
      await settled(page);
      assert.deepEqual(state.writes, []);
      await assertLayout(page, original);
    });

    await test('empty lower slot accepts stage when its top anchor exists', async (page, state) => {
      await stageHover(page, 5, slot(1, 1));
      await dropStage(page, state, [placement(1, 0, 0), placement(2, 1, 0), placement(3, 0, 1),
        placement(5, 1, 1), placement(6, 0, 2)]);
    }, { stages: initialStages().filter(s => s.id !== 4) });

    await test('unpaired top stage cannot drop into its own lower slot and become orphaned', async (page, state) => {
      const original = placementsOf(state.stages);
      await stageHover(page, 5, slot(1, 2), false);
      await page.mouse.up();
      await settled(page);
      assert.deepEqual(state.writes, []);
      await assertLayout(page, original);
    }, { stages: initialStages().filter(s => s.id !== 6) });

    for (const failure of ['http', 'network']) {
      await test(`${failure} reorder failure alerts, restores original layout, and permits retry`, async (page, state) => {
        const original = structuredClone(state.stages);
        await stageHover(page, 5, BOUNDARY);
        const failureObserved = failure === 'http'
          ? page.waitForResponse(r => r.url().endsWith('/api/stages/reorder') && r.status() === 503)
          : page.waitForEvent('requestfailed', r => r.url().endsWith('/api/stages/reorder'));
        await Promise.all([failureObserved, page.waitForEvent('dialog'), page.mouse.up()]);
        await settled(page);
        assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/stages/reorder', body: { stages: INSERTED } }]);
        assert.deepEqual(state.stages, original, 'Failed request did not commit fixture state');
        await assertLayout(page, placementsOf(original));
        assert.equal(await page.locator('.stage-drop-active, .stage-ghost, .sortable-chosen').count(), 0);
        assert.equal(await page.locator('#stage-1').evaluate(el => !Sortable.get(el).option('disabled')), true,
          'Task dragging is enabled again too');
        state.reorderFailure = null;
        state.writes = [];
        await stageHover(page, 5, BOUNDARY);
        await dropStage(page, state, INSERTED);
      }, { reorderFailure: failure, expectedDialogs: [SAVE_ALERT] });
    }

    await test('viewer has no stage or task Sortables and mouse gestures send no writes', async (page, state) => {
      const original = placementsOf(state.stages);
      assert.equal(await page.locator('.stage-drag-grip, [data-stage-insert-position]').count(), 0);
      const sortableCount = () => page.locator('[data-stage-slot], .board-stage-body')
        .evaluateAll(els => els.filter(el => Sortable.get(el)).length);
      assert.equal(await sortableCount(), 0);
      for (const selector of [`${stage(5)} [data-stage-drag-handle]`, task(101)]) {
        await startDrag(page, selector);
        await move(page, await point(page, slot(0, 1)));
        await page.mouse.up();
      }
      await page.waitForTimeout(250);
      await assertNoStageStart(page);
      assert.equal(await sortableCount(), 0);
      assert.deepEqual(state.writes, []);
      await assertLayout(page, original);
    }, { role: 'viewer' });

    await test('task reorder within stage sends only task API', async (page, state) => {
      const destination = await point(page, task(103), 0.5, 0.9);
      await startDrag(page, task(101));
      await move(page, destination);
      await assertTaskHighlight(page, stage(1));
      await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/api/tasks/reorder')),
        page.mouse.up(),
      ]);
      await settled(page);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/tasks/reorder', body: { stage_id: 1, ids: [102, 103, 101] } }]);
      assert.deepEqual(await page.locator('#stage-1 .board-task-card').evaluateAll(els => els.map(el => Number(el.dataset.taskId))), [102, 103, 101]);
      await assertNoStageStart(page);
    });

    await test('task drag across stages sends only task API', async (page, state) => {
      const destination = await point(page, task(302), 0.5, 0.9);
      await startDrag(page, task(101));
      await move(page, destination);
      await assertTaskHighlight(page, stage(3));
      await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/tasks/reorder')), page.mouse.up()]);
      await settled(page);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/tasks/reorder', body: { stage_id: 3, ids: [301, 101, 302] } }]);
      assert.equal(await page.locator(`#stage-3 ${task(101)}`).count(), 1);
      assert.equal(await page.locator(`#stage-1 ${task(101)}`).count(), 0);
      await assertNoStageStart(page);
    });

    await test('task feedback follows eligible targets only and clears on outside hover and Escape', async (page, state) => {
      await page.locator(grip(3)).dblclick();
      await settled(page);
      await page.evaluate(() => document.documentElement.classList.add('dark'));
      await startDrag(page, task(101));
      await move(page, await point(page, '#stage-2'));
      await assertTaskHighlight(page, stage(2));
      for (const selector of ['#stage-6', `${stage(3)} .stage-collapsed-title`, BOUNDARY, 'nav']) {
        await move(page, await point(page, selector));
        assert.equal(await page.locator('.task-drop-active').count(), 0, `No task highlight on ${selector}`);
      }
      await move(page, await point(page, '#stage-1'));
      await assertTaskHighlight(page, stage(1));
      await page.keyboard.press('Escape');
      await page.mouse.up();
      await settled(page);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.ok(state.writes.every(write => write.path === '/api/tasks/reorder'));
      await assertNoStageStart(page);
    });

    await test('empty task stage highlights without changing its drop behavior', async (page, state) => {
      await startDrag(page, task(101));
      await move(page, await point(page, '#stage-3'));
      await assertTaskHighlight(page, stage(3));
      await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/tasks/reorder')), page.mouse.up()]);
      await settled(page);
      assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/tasks/reorder', body: { stage_id: 3, ids: [101] } }]);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
    }, { stages: initialStages().map(s => s.id === 3 ? { ...s, tasks: [] } : s) });

    for (const date of ['2026-09-02', '2026-08-31']) {
      await test(`calendar task highlights empty day ${date} and changes only due date`, async (page, state) => {
        const original = structuredClone(state.stages[0].tasks[0]);
        await page.evaluate(() => document.documentElement.classList.add('dark'));
        await startDrag(page, calendarTask('2026-09-01'));
        await move(page, await point(page, calendarDropzone(date)));
        await assertTaskHighlight(page, calendarDay(date));
        await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/tasks/101')), page.mouse.up()]);
        await page.waitForLoadState('networkidle');
        await settled(page);
        assert.equal(await page.locator('.task-drop-active').count(), 0);
        assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/tasks/101', body: { due_date: date } }]);
        assert.deepEqual(state.stages[0].tasks[0], { ...original, due_date: date });
        assert.equal(await page.locator(calendarTask(date)).count(), 1);
        await assertNoStageStart(page);
      }, { view: 'calendar', stages: calendarStages() });
    }

    await test('calendar same-day task drag highlights then clears without saving', async (page, state) => {
      await startDrag(page, calendarTask('2026-09-01'));
      await move(page, await point(page, calendarTask('2026-09-01', 102), 0.5, 0.9));
      await assertTaskHighlight(page, calendarDay('2026-09-01'));
      await page.mouse.up();
      await settled(page);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.deepEqual(state.writes, []);
    }, { view: 'calendar', stages: calendarStages() });

    await test('calendar recurrence preview gestures do not activate task feedback', async (page, state) => {
      await startDrag(page, `${calendarDay('2026-09-04')} [data-calendar-draggable="false"]`);
      await move(page, await point(page, calendarDropzone('2026-09-03')));
      await page.mouse.up();
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.equal(await page.evaluate(() => !!Sortable.active), false);
      assert.deepEqual(state.writes, []);
    }, { view: 'calendar', stages: calendarStages() });

    await test('calendar viewers have no task drag feedback or writes', async (page, state) => {
      await startDrag(page, calendarTask('2026-09-01'));
      await move(page, await point(page, calendarDropzone('2026-09-02')));
      await page.mouse.up();
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.deepEqual(state.writes, []);
    }, { view: 'calendar', stages: calendarStages(), role: 'viewer' });

    await test('calendar save failure clears feedback and permits the next drag', async (page, state) => {
      await page.route('**/api/tasks/101', route => route.fulfill({ status: 503, json: { detail: 'Intentional task update failure' } }));
      await startDrag(page, calendarTask('2026-09-01'));
      await move(page, await point(page, calendarDropzone('2026-09-02')));
      await assertTaskHighlight(page, calendarDay('2026-09-02'));
      await page.mouse.up();
      await page.waitForLoadState('networkidle');
      await settled(page);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.equal(await page.locator(calendarTask('2026-09-01')).count(), 1);
      await page.unroute('**/api/tasks/101');
      await startDrag(page, calendarTask('2026-09-01'));
      await move(page, await point(page, calendarDropzone('2026-09-02')));
      await assertTaskHighlight(page, calendarDay('2026-09-02'));
      await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/tasks/101')), page.mouse.up()]);
      await settled(page);
      assert.deepEqual(state.writes, [{ method: 'PUT', path: '/api/tasks/101', body: { due_date: '2026-09-02' } }]);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
    }, { view: 'calendar', stages: calendarStages(), expectedDialogs: ['Intentional task update failure'] });

    await test('task reorder failure leaves no highlight and restores the original stage', async (page, state) => {
      await page.route('**/api/tasks/reorder', route => route.fulfill({ status: 503, json: { detail: 'Intentional reorder failure' } }));
      await startDrag(page, task(101));
      await move(page, await point(page, '#stage-3'));
      await assertTaskHighlight(page, stage(3));
      await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/tasks/reorder')), page.mouse.up()]);
      await settled(page);
      assert.equal(await page.locator('.task-drop-active').count(), 0);
      assert.equal(await page.locator(`#stage-1 ${task(101)}`).count(), 1);
      assert.deepEqual(state.writes, []);
    });

    for (const view of ['stages', 'calendar']) {
      await test(`touch task dragging highlights and clears its ${view} destination`, async (page, state, context) => {
        const cdp = await context.newCDPSession(page);
        try {
          const source = view === 'calendar' ? calendarTask('2026-09-01') : task(101);
          const destination = view === 'calendar' ? calendarDropzone('2026-09-02') : '#stage-3';
          const highlight = view === 'calendar' ? calendarDay('2026-09-02') : stage(3);
          const from = await point(page, source);
          const to = await point(page, destination);
          await touchEvent(cdp, 'touchStart', from);
          for (let i = 1; i <= 20; i++) {
            await touchEvent(cdp, 'touchMove', {
              x: from.x + (to.x - from.x) * i / 20, y: from.y + (to.y - from.y) * i / 20,
            });
            await page.waitForTimeout(25);
          }
          await assertTaskHighlight(page, highlight);
          await touchEvent(cdp, 'touchEnd');
          await settled(page);
          assert.equal(await page.locator('.task-drop-active').count(), 0);
          assert.equal(state.writes.length, 1);
          assert.equal(state.writes[0].path, view === 'calendar' ? '/api/tasks/101' : '/api/tasks/reorder');
          await assertNoStageStart(page);
        } finally {
          await cdp.detach();
        }
      }, { view, touch: true, stages: calendarStages() });
    }

    await test('native Escape after valid hover does not write stage layout', async (page, state) => {
      await stageHover(page, 5, BOUNDARY);
      await page.keyboard.press('Escape');
      await page.mouse.up();
      await settled(page);
      assert.deepEqual(state.writes, []);
      assert.equal(await page.locator('.stage-drop-active').count(), 0);
    });

    await test('release outside after valid hover does not write stage layout', async (page, state) => {
      await stageHover(page, 5, BOUNDARY);
      await move(page, { x: 1400, y: 940 });
      assert.equal(await page.locator('.stage-drop-active').count(), 0);
      await page.mouse.up();
      await settled(page);
      assert.deepEqual(state.writes, []);
    });

    await test('title and menu gestures never start stage dragging', async (page, state) => {
      for (const selector of [`${stage(5)} input[data-field="stage-name"]`, `${stage(5)} [data-action="toggle-stage-menu"]`]) {
        await startDrag(page, selector);
        await move(page, await point(page, BOUNDARY));
        await page.mouse.up();
        await settled(page);
      }
      await assertNoStageStart(page);
      assert.ok(state.writes.every(w => w.path === '/api/stages/5' && Object.keys(w.body).join() === 'name'),
        'Only normal title-blur saves are allowed');
    });

    await test('log stage is draggable but its tasks have no Sortable', async (page, state) => {
      assert.equal(await page.locator('#stage-6').evaluate(el => !!Sortable.get(el)), false);
      assert.equal(await page.locator('#stage-1').evaluate(el => !!Sortable.get(el)), true);
      await stageHover(page, 6, BOUNDARY);
      await dropStage(page, state, [placement(1, 0, 0), placement(2, 1, 0), placement(6, 0, 1),
        placement(3, 0, 2), placement(4, 1, 2), placement(5, 0, 3)]);
      assert.equal(await page.locator('#stage-6').evaluate(el => !!Sortable.get(el)), false);
    });

    await test('Sortables reinitialize after menu rerender and after a saved drag', async (page, state) => {
      const old = await page.locator(stage(5)).elementHandle();
      await page.locator(`${stage(5)} [data-action="toggle-stage-menu"]`).click();
      await ready(page);
      assert.equal(await old.evaluate(el => el.isConnected), false, 'Menu action really replaced stage DOM');
      await old.dispose();
      await page.locator(`${stage(5)} [data-action="toggle-stage-menu"]`).click();
      await ready(page);
      await stageHover(page, 5, BOUNDARY);
      await dropStage(page, state, INSERTED);
      state.writes = [];
      await stageHover(page, 5, slot(0, 3));
      await dropStage(page, state, [placement(1, 0, 0), placement(2, 1, 0), placement(6, 0, 1),
        placement(3, 0, 2), placement(4, 1, 2), placement(5, 0, 3)]);
    });

    await test('CDP touch fallback inserts at boundary', async (page, state, context) => {
      const cdp = await context.newCDPSession(page);
      try {
        await touchHover(page, cdp, 5, BOUNDARY);
        await Promise.all([expectStageWrite(page, state, INSERTED), touchEvent(cdp, 'touchEnd')]);
        assert.equal(await page.evaluate(() =>
          window.dragEvents.some(e => e.type === 'pointerdown' && e.pointerType === 'touch') &&
          !window.dragEvents.some(e => e.type === 'dragstart') &&
          window.dragEvents.some(e => e.type === 'end' && e.kind === 'stage' &&
            ['touchend', 'pointerup'].includes(e.originalType))), true,
        'Touch exercised Sortable fallback');
      } finally {
        await cdp.detach();
      }
    }, { touch: true });

    await test('CDP touchcancel after valid hover sends no write and allows a new drag', async (page, state, context) => {
      const cdp = await context.newCDPSession(page);
      try {
        const original = placementsOf(state.stages);
        await touchHover(page, cdp, 5, BOUNDARY);
        await touchEvent(cdp, 'touchCancel');
        assert.equal(await page.evaluate(() => window.dragEvents.some(e => e.type === 'touchcancel')), true,
          'Browser delivered native touch cancellation');
        await page.waitForTimeout(250);
        assert.deepEqual(state.writes, []);
        // Keep a failed cleanup visible: a cancellation that leaves Sortable
        // active blocks future gestures even though it correctly sent no PUT.
        await settled(page);
        assert.equal(await page.locator('.stage-drop-active, .stage-ghost, .sortable-chosen').count(), 0);
        await assertLayout(page, original);
        await touchHover(page, cdp, 5, BOUNDARY);
        await Promise.all([expectStageWrite(page, state, INSERTED), touchEvent(cdp, 'touchEnd')]);
      } finally {
        await cdp.detach();
      }
    }, { touch: true });

    await test('horizontal edge scrolling during native drag resolves the visible release boundary', async (page, state) => {
      const surface = page.locator('#board-stages-view');
      assert.equal(await surface.evaluate(el => el.scrollWidth > el.clientWidth), true, 'Board overflows horizontally');
      const source = await page.locator(stage(1)).elementHandle();
      await startDrag(page, grip(1));
      await page.waitForSelector('#board-stages-view.stage-dragging');
      const viewport = page.viewportSize();
      await move(page, { x: viewport.width - 8, y: 180 });
      // Exercise native/Sortable edge auto-scroll using real pointer input.
      await page.waitForFunction(() => document.querySelector('#board-stages-view').scrollLeft > 80);
      const target = '[data-stage-insert-position="3"]';
      await move(page, await point(page, target, 0.5, 0.3));
      await page.waitForSelector(`${target}.stage-drop-active`);
      assert.equal(await source.evaluate(el => el.isConnected && el.parentElement.dataset.stageSlotPosition === '0'), true,
        'Scrolling does not relocate the drag source');
      await source.dispose();
      await dropStage(page, state, [placement(2, 0, 0), placement(3, 0, 1), placement(4, 1, 1),
        placement(5, 0, 2), placement(6, 1, 2), placement(1, 0, 3)]);
    }, { viewport: { width: 1000, height: 1000 } });

    console.log(`\n${passes} passed; ${failures} failed.`);
    if (failures) process.exitCode = 1;
  } finally {
    await browser?.close();
    if (fixture) await new Promise((resolve, reject) => fixture.server.close(error => error ? reject(error) : resolve()));
    await api?.dispose();
  }
}

main().catch(error => { console.error(error.stack); process.exitCode = 1; });

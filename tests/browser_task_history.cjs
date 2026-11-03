#!/usr/bin/env node
'use strict';

// Uses a disposable database. Requires Playwright/Chromium; optionally set
// QUESTLINE_TEST_PYTHON and QUESTLINE_TEST_SCREENSHOT (PNG path).
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-history-browser-'));
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(process.env.QUESTLINE_TEST_PYTHON || 'python', [
    '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(port), '--lifespan', 'off',
  ], {
    cwd: path.resolve(__dirname, '..'),
    env: {...process.env, QUESTLINE_DATABASE_URL: `sqlite:///${path.join(directory, 'test.db')}`,
      QUESTLINE_ENV: 'development', QUESTLINE_ALLOW_INSECURE_COOKIES: 'true',
      QUESTLINE_AUDIT_LOG_PATH: '', QUESTLINE_PUBLIC_BASE_URL: origin},
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let output = '';
  server.stderr.on('data', data => {output += data.toString();});
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      try {ready = (await fetch(`${origin}/login`)).ok;} catch {}
      if (ready || server.exitCode !== null) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, output);
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({timezoneId: 'Europe/Berlin', viewport: {width: 1280, height: 900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const registration = await page.request.post(`${origin}/api/auth/register`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'history@example.invalid', password: 'test-password-only', display_name: 'Alex Example'},
    });
    assert.equal(registration.status(), 200, await registration.text());
    const cookies = await page.context().cookies();
    const headers = {'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': cookies.find(cookie => cookie.name === 'questline_csrf').value};
    async function write(method, route, data) {
      const response = await page.request[method](`${origin}${route}`, {headers, data});
      assert(response.ok(), await response.text());
      return response.json();
    }
    const board = await write('post', '/api/boards', {name: 'Task history'});
    const stage = await write('post', '/api/stages', {board_id: board.id, name: 'Inbox'});
    const next = await write('post', '/api/stages', {board_id: board.id, name: 'Done'});
    const task = await write('post', '/api/tasks', {stage_id: stage.id, title: 'Prepare the next release'});
    const other = await write('post', '/api/tasks', {stage_id: stage.id, title: 'Another objective'});
    const taskUrl = `/api/tasks/${task.id}`;
    await write('post', '/api/automations', {board_id: board.id, name: 'Complete and move', enabled: true,
      trigger_type: 'task_done', action_type: 'move_to_stage', action_stage_id: next.id});
    await write('put', taskUrl, {description: 'Review the release notes and verify the published package.'});
    const item = await write('post', `${taskUrl}/checklist`, {title: 'Run regression checks'});
    await write('put', `${taskUrl}/checklist/${item.id}`, {done: true});
    await write('put', taskUrl, {done: true});
    for (let index = 0; index < 55; index++) {
      await write('put', taskUrl, {title: `Prepare the next release (${index + 1})`});
    }
    let historyReads = 0;
    page.on('request', request => {if (request.url().includes(`${taskUrl}/history`)) historyReads++;});
    await page.goto(`${origin}/board/${board.id}?task_id=${task.id}`);
    const modal = page.locator('#board-task-modal');
    const toggle = modal.locator('.task-history-toggle');
    const pane = modal.locator('#task-history-pane');
    await toggle.waitFor();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(await pane.count(), 0);
    assert.equal(historyReads, 0);
    const collapsedBox = await modal.locator('.task-modal-shell').boundingBox();
    const collapsedWidth = collapsedBox.width;
    assert.equal(collapsedWidth, 672);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-collapsed.png')});
    }
    await toggle.click();
    await pane.locator('.task-history-event').first().waitFor();
    assert.equal(await pane.locator('.task-history-event').count(), 50);
    const shellBox = await modal.locator('.task-modal-shell').boundingBox();
    const paneBox = await pane.boundingBox();
    const mainBox = await modal.locator('.task-modal-main').boundingBox();
    assert(shellBox.width > collapsedWidth);
    assert(Math.abs(shellBox.height - collapsedBox.height) < 1);
    assert(Math.abs(shellBox.y - collapsedBox.y) < 1);
    assert.equal(mainBox.width, collapsedWidth);
    assert(paneBox.x >= mainBox.x + mainBox.width - 1);
    assert(Math.abs(paneBox.height - shellBox.height) < 2);
    const scroll = pane.locator('[data-role="task-history-scroll"]');
    assert(await scroll.evaluate(element => element.scrollHeight > element.clientHeight));
    await pane.getByRole('button', {name: 'Load older events'}).click();
    await pane.getByText('Task created', {exact: true}).waitFor();
    assert(Math.abs((await modal.locator('.task-modal-shell').boundingBox()).height - collapsedBox.height) < 1);
    assert((await pane.innerText()).includes('Automation'));
    assert((await pane.innerText()).includes('Alex Example'));
    assert((await pane.innerText()).includes('Checklist item completed'));
    assert((await pane.innerText()).includes('Run regression checks'));
    assert((await pane.locator('time').first().getAttribute('datetime')).endsWith('Z'));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await scroll.evaluate(element => {element.scrollTop = element.scrollHeight;});
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT});
    }
    // A visible history refreshes after a modal edit and suppresses unchanged saves.
    const title = modal.locator('[data-field="modal-title"]');
    await title.fill('Release ready');
    await title.press('Tab');
    await page.waitForFunction(() => document.querySelector('[data-field="modal-title"]')?.value === 'Release ready'
      && !document.querySelector('[data-role="task-history-scroll"]')?.getAttribute('aria-busy')?.includes('true'));
    const after = await (await page.request.get(`${origin}${taskUrl}/history`, {params: {limit: 100}})).json();
    assert(after.items[0].message === 'Title updated');
    await pane.locator(`[data-history-event-id="${after.items[0].id}"]`).waitFor();
    await title.focus();
    await title.press('Tab');
    const noChange = await (await page.request.get(`${origin}${taskUrl}/history`, {params: {limit: 100}})).json();
    assert.equal(noChange.items.length, after.items.length);
    // Mobile uses a stacked pane with its own scroll area and no horizontal overflow.
    await page.setViewportSize({width: 390, height: 844});
    const mobile = await pane.boundingBox();
    const mobileMain = await modal.locator('.task-modal-main').boundingBox();
    assert(mobile.y >= mobileMain.y + mobileMain.height - 1);
    assert(await modal.locator('.task-modal-shell').evaluate(element => element.scrollWidth <= element.clientWidth));
    await toggle.click();
    const mobileCollapsed = await modal.locator('.task-modal-shell').boundingBox();
    await toggle.click();
    await pane.locator('.task-history-event').first().waitFor();
    const mobileExpanded = await modal.locator('.task-modal-shell').boundingBox();
    assert(Math.abs(mobileExpanded.height - mobileCollapsed.height) < 1);
    assert(Math.abs(mobileExpanded.y - mobileCollapsed.y) < 1);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-mobile.png')});
      await page.evaluate(() => document.documentElement.classList.add('dark'));
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-dark.png')});
    }
    // Closing/reopening or opening a different objective always starts collapsed.
    await modal.locator('button[data-action="close-task-modal"]').click();
    await page.goto(`${origin}/board/${board.id}?task_id=${other.id}`);
    await toggle.waitFor();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    await toggle.click();
    await pane.getByText('Task created', {exact: true}).waitFor();
    assert.equal(await pane.locator('.task-history-event').count(), 1);
    assert.deepEqual(errors, []);
    console.log('Task history browser checks passed (desktop, mobile, pagination, edits, automation, task switching).');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => server.exitCode === null ? server.once('exit', resolve) : resolve());
    await fs.rm(directory, {recursive: true, force: true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

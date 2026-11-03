#!/usr/bin/env node
'use strict';

// Real browser/API checks using the same disposable database and Playwright
// setup as browser_deadlines.cjs.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-assignments-browser-'));
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
    const page = await browser.newPage({viewport: {width: 1100, height: 850}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const registered = await page.request.post(`${origin}/api/auth/register`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'alice@example.invalid', password: 'test-password-only', display_name: 'Alice Adams'},
    });
    assert(registered.ok(), await registered.text());
    const alice = await registered.json();
    const cookies = await page.context().cookies();
    const headers = {'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': cookies.find(cookie => cookie.name === 'questline_csrf').value};
    async function post(route, data) {
      const response = await page.request.post(`${origin}${route}`, {headers, data});
      assert(response.ok(), await response.text());
      return response.json();
    }
    const board = await post('/api/boards', {name: 'Shared assignments'});
    const stage = await post('/api/stages', {board_id: board.id, name: 'Inbox'});
    const task = await post('/api/tasks', {stage_id: stage.id, title: 'Plan the next release'});
    const teammateContext = await browser.newContext();
    const teammates = [];
    for (const [email, display_name] of [['bob@example.invalid', 'Bob Brown'], ['carol@example.invalid', 'Carol Cruz']]) {
      const response = await teammateContext.request.post(`${origin}/api/auth/register`, {
        headers: {'X-Requested-With': 'XMLHttpRequest'}, data: {email, display_name, password: 'test-password-only'},
      });
      assert(response.ok(), await response.text());
      const user = await response.json();
      const activated = await page.request.put(`${origin}/api/admin/users/${user.id}`, {headers, data: {is_active: true}});
      assert(activated.ok(), await activated.text());
      await post(`/api/boards/${board.id}/members`, {email, role: 'viewer'});
      teammates.push(user);
    }
    const modal = page.locator('#board-task-modal');
    const trigger = modal.locator('[data-action="modal-toggle-assignees"]');
    const picker = modal.locator('#objective-assignees-options');
    const taskUrl = `${origin}/api/tasks/${task.id}`;
    async function toggle(name, checked) {
      const saved = page.waitForResponse(response => response.url() === taskUrl && response.request().method() === 'PUT');
      await picker.getByRole('checkbox', {name, exact: true}).setChecked(checked);
      const response = await saved;
      assert(response.ok(), await response.text());
      await page.waitForFunction(() => !document.querySelector('#objective-assignees-options input:disabled'));
      return response.json();
    }
    await page.goto(`${origin}/board/${board.id}?task_id=${task.id}`);
    await trigger.waitFor();
    assert.equal(await trigger.innerText(), 'Unassigned');
    await trigger.click();
    assert.equal(await picker.getByRole('checkbox').count(), 3);
    let saved = await toggle('Bob Brown', true);
    assert.deepEqual(saved.assignee_user_ids, [teammates[0].id]);
    assert(await picker.isVisible());
    saved = await toggle('Carol Cruz', true);
    assert.deepEqual(saved.assignee_user_ids, teammates.map(user => user.id));
    assert(await picker.getByRole('checkbox', {name: 'Bob Brown'}).isChecked());
    assert(await picker.getByRole('checkbox', {name: 'Carol Cruz'}).isChecked());
    // Escape closes only the dropdown and restores the trigger's keyboard focus.
    await page.keyboard.press('Escape');
    assert.equal(await picker.count(), 0);
    assert(await trigger.isVisible());
    assert.equal(await page.locator(':focus').getAttribute('data-action'), 'modal-toggle-assignees');
    await page.reload();
    await trigger.waitFor();
    assert.equal(await trigger.innerText(), 'Bob Brown, Carol Cruz');
    await modal.locator('button[data-action="close-task-modal"]').click();
    const card = page.locator(`[data-task-id="${task.id}"]`).first();
    assert.deepEqual(await card.locator('.task-assignee-pill').allTextContents(), ['BB', 'CC']);
    assert.equal(await card.locator('.task-assignee-pill').first().getAttribute('title'), 'Bob Brown');
    assert(!(await card.innerText()).includes('@'));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT});
    await card.click();
    await trigger.click();
    // Clicking outside and tabbing out close the dropdown without closing the modal.
    await modal.locator('[data-action="modal-toggle-deadline"]').click();
    assert.equal(await picker.count(), 0);
    await page.keyboard.press('Escape');
    await trigger.click();
    await modal.locator('[data-action="modal-toggle-deadline"]').focus();
    assert.equal(await picker.count(), 0);
    // Failed updates keep the previous assignments and allow a retry.
    await page.route(taskUrl, async route => {
      if (route.request().method() === 'PUT') await route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({detail: 'Test rejection'})});
      else await route.continue();
    });
    await trigger.click();
    const rejected = page.waitForResponse(response => response.url() === taskUrl && response.status() === 400);
    await picker.getByRole('checkbox', {name: 'Bob Brown', exact: true}).click();
    await rejected;
    await modal.getByRole('alert').waitFor();
    assert(await picker.getByRole('checkbox', {name: 'Bob Brown', exact: true}).isChecked());
    assert.equal(await trigger.innerText(), 'Bob Brown, Carol Cruz');
    await page.unroute(taskUrl);
    await toggle('Bob Brown', false);
    await toggle('Carol Cruz', false);
    assert.equal(await trigger.innerText(), 'Unassigned');
    // Mobile: select two users with the same checkbox control.
    await page.setViewportSize({width: 390, height: 844});
    await toggle('Alice Adams', true);
    await toggle('Carol Cruz', true);
    const rect = await picker.boundingBox();
    assert(rect.x >= 0 && rect.x + rect.width <= 390);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-mobile.png')});
    // Viewers see the full selection but cannot edit it through the UI or API.
    const loggedIn = await teammateContext.request.post(`${origin}/api/auth/login`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'carol@example.invalid', password: 'test-password-only'},
    });
    assert(loggedIn.ok(), await loggedIn.text());
    const viewer = await teammateContext.newPage();
    await viewer.goto(`${origin}/board/${board.id}?task_id=${task.id}`);
    const viewerTrigger = viewer.locator('[data-action="modal-toggle-assignees"]');
    await viewerTrigger.waitFor();
    assert(await viewerTrigger.isDisabled());
    assert.equal(await viewerTrigger.innerText(), 'Alice Adams, Carol Cruz');
    assert.deepEqual(errors, []);
    console.log('Assignment browser checks passed: multiple selection, reload, initials pills, keyboard, failed saves, clearing, mobile, viewer.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => {if (server.exitCode !== null) resolve(); else server.once('exit', resolve);});
    await fs.rm(directory, {recursive: true, force: true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

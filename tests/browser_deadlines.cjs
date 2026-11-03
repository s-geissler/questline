#!/usr/bin/env node
'use strict';

// Real browser/API check with a disposable database. See browser_trello_import.cjs
// for the same Playwright and QUESTLINE_TEST_PYTHON setup.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-deadlines-browser-'));
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
  let serverOutput = '';
  server.stderr.on('data', data => {serverOutput += data.toString();});
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      try {ready = (await fetch(`${origin}/login`)).ok;} catch {}
      if (ready || server.exitCode !== null) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, serverOutput);
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({timezoneId: 'Europe/Berlin', viewport: {width: 1100, height: 850}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => {errors.push(dialog.message()); dialog.accept();});
    const registered = await page.request.post(`${origin}/api/auth/register`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'deadlines@example.invalid', password: 'test-password-only', display_name: 'Deadline Owner'},
    });
    assert.equal(registered.status(), 200, await registered.text());
    const cookies = await page.context().cookies();
    const headers = {'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': cookies.find(cookie => cookie.name === 'questline_csrf').value};
    async function post(route, data) {
      const response = await page.request.post(`${origin}${route}`, {headers, data});
      assert(response.ok(), await response.text());
      return response.json();
    }
    const board = await post('/api/boards', {name: 'Timed deadlines'});
    const stage = await post('/api/stages', {board_id: board.id, name: 'Inbox'});
    const task = await post('/api/tasks', {stage_id: stage.id, title: 'Review release', due_date: '2026-11-03'});
    const feed = await post('/api/calendar-feeds', {name: 'Deadlines', board_id: board.id});
    const taskUrl = `${origin}/api/tasks/${task.id}`;
    const modal = page.locator('#board-task-modal');
    const trigger = modal.locator('[data-action="modal-toggle-deadline"]');
    const picker = modal.locator('[data-role="deadline-picker"]');
    const dueTime = picker.getByLabel('Time (optional)', {exact: true});
    const writes = [];
    page.on('request', request => {if (request.url() === taskUrl && request.method() === 'PUT') writes.push(request.postDataJSON());});
    async function save(name = 'Apply') {
      const saved = page.waitForResponse(response => response.url() === taskUrl && response.request().method() === 'PUT');
      await picker.getByRole('button', {name, exact: true}).click();
      const response = await saved;
      assert(response.ok(), await response.text());
      const body = await response.json();
      await picker.waitFor({state: 'hidden'});
      return body;
    }
    await page.goto(`${origin}/board/${board.id}?task_id=${task.id}`);
    await trigger.waitFor();
    assert.equal(await modal.locator('input[type="time"], input[type="date"]').count(), 0);
    let stream = await (await page.request.get(feed.subscription_url)).text();
    assert(stream.includes('DTSTART;VALUE=DATE:20261103'));
    // The single control opens a calendar with an optional time; keyboard date
    // navigation changes the draft without sending partial API updates.
    await trigger.focus();
    await trigger.press('Enter');
    await picker.waitFor();
    assert.equal(await dueTime.inputValue(), '');
    assert((await picker.innerText()).includes('No time · all-day deadline'));
    assert.equal(await page.locator(':focus').getAttribute('data-date'), '2026-11-03');
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator(':focus').getAttribute('data-date'), '2026-11-04');
    await page.keyboard.press('Enter');
    await dueTime.fill('14:30');
    assert.equal(writes.length, 0);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-open.png')});
    }
    let saved = await save();
    assert.equal(saved.due_date, '2026-11-04');
    assert.equal(saved.due_timezone, 'Europe/Berlin');
    assert.equal(saved.due_at, '2026-11-04T13:30:00Z');
    assert.deepEqual(writes[0], {due_date: '2026-11-04', due_time: '14:30', due_timezone: 'Europe/Berlin'});
    stream = await (await page.request.get(feed.subscription_url)).text();
    assert(stream.includes('DTSTART:20261104T133000Z'));
    assert(!stream.includes('DTEND'));
    await page.reload();
    await trigger.waitFor();
    assert((await trigger.innerText()).includes('14:30'));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT});
    await trigger.click();
    assert.equal(await dueTime.inputValue(), '14:30');
    assert((await picker.innerText()).includes('Europe/Berlin'));
    await page.keyboard.press('PageDown');
    await page.keyboard.press('Enter');
    await dueTime.fill('20:00');
    await page.keyboard.press('Escape');
    await picker.waitFor({state: 'hidden'});
    assert(await trigger.evaluate(element => element === document.activeElement));
    assert.equal(writes.length, 1);
    assert.equal((await (await page.request.get(taskUrl)).json()).due_time, '14:30');
    await trigger.click();
    await picker.getByRole('button', {name: 'Cancel', exact: true}).click();
    assert.equal(writes.length, 1);
    await trigger.click();
    await modal.getByText('Description', {exact: true}).click();
    await picker.waitFor({state: 'hidden'});
    assert.equal(writes.length, 1);

    await page.setViewportSize({width: 390, height: 844});
    await trigger.click();
    await picker.waitFor();
    const bounds = await picker.boundingBox();
    assert(bounds.x >= 0 && bounds.x + bounds.width <= 390 && bounds.y >= 0 && bounds.y + bounds.height <= 844, JSON.stringify(bounds));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-mobile.png')});
    }
    await page.evaluate(() => document.documentElement.classList.add('dark'));
    assert.equal(await picker.evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(17, 24, 39)');
    await page.evaluate(() => document.documentElement.classList.remove('dark'));
    for (let month = 0; month < 4; month++) await picker.getByRole('button', {name: 'Previous month'}).click();
    await picker.locator('[data-date="2026-07-03"]').click();
    saved = await save();
    assert.equal(saved.due_time, '14:30');
    assert.equal(saved.due_at, '2026-07-03T12:30:00Z');
    await trigger.click();
    await picker.getByRole('button', {name: 'No time', exact: true}).click();
    saved = await save();
    assert.equal(saved.due_time, null);
    assert.equal(saved.due_timezone, null);
    stream = await (await page.request.get(feed.subscription_url)).text();
    assert(stream.includes('DTSTART;VALUE=DATE:20260703'));
    assert(stream.includes('DTEND;VALUE=DATE:20260704'));
    await trigger.click();
    await dueTime.fill('00:00');
    saved = await save();
    assert.equal(saved.due_time, '00:00');
    await trigger.click();
    saved = await save('Clear');
    assert.equal(saved.due_date, null);
    assert.equal(saved.due_time, null);
    assert.equal((await trigger.innerText()).trim(), 'No due date');
    assert(!(await (await page.request.get(feed.subscription_url)).text()).includes('BEGIN:VEVENT'));
    await trigger.click();
    assert(await dueTime.isDisabled());
    await page.keyboard.press('Enter');
    assert(await dueTime.isEnabled());
    saved = await save();
    assert.equal(saved.due_time, null);
    assert.equal(saved.due_timezone, null);
    assert((await (await page.request.get(feed.subscription_url)).text()).includes('DTSTART;VALUE=DATE:'));
    assert.deepEqual(errors, []);
    console.log('Deadline browser checks passed: single control, combined calendar/time picker, atomic updates, keyboard navigation, cancel/Escape/outside dismissal, timezone, DST, midnight, clearing, calendar stream, desktop/mobile and dark mode.');
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) {
      const exited = new Promise(resolve => server.once('exit', resolve));
      server.kill();
      await exited;
    }
    await fs.rm(directory, {recursive: true, force: true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

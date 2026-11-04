#!/usr/bin/env node
'use strict';

// Run against an isolated database with the Playwright setup used by the other
// browser checks. QUESTLINE_TEST_SCREENSHOT optionally saves editor previews.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-filter-sorting-'));
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(process.env.QUESTLINE_TEST_PYTHON || 'python', [
    '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(port), '--lifespan', 'off',
  ], {cwd: path.resolve(__dirname, '..'),
    env: {...process.env, QUESTLINE_DATABASE_URL: `sqlite:///${path.join(directory, 'test.db')}`,
      QUESTLINE_ENV: 'development', QUESTLINE_ALLOW_INSECURE_COOKIES: 'true',
      QUESTLINE_AUDIT_LOG_PATH: '', QUESTLINE_PUBLIC_BASE_URL: origin},
    stdio: ['ignore', 'ignore', 'pipe']});
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
    const page = await browser.newPage({viewport: {width: 1100, height: 1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const registration = await page.request.post(`${origin}/api/auth/register`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'sort@example.invalid', display_name: 'Sort Owner', password: 'test-password-only'},
    });
    assert(registration.ok(), await registration.text());
    const cookies = await page.context().cookies();
    const headers = {'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': cookies.find(cookie => cookie.name === 'questline_csrf').value};
    async function write(method, route, data) {
      const response = await page.request[method](`${origin}${route}`, {headers, data});
      assert(response.ok(), await response.text());
      return response.json();
    }
    const board = await write('post', '/api/boards', {name: 'Sorting demo'});
    const source = await write('post', '/api/stages', {board_id: board.id, name: 'Inbox'});
    const log = await write('post', '/api/stages', {board_id: board.id, name: 'Work log'});
    const type = await write('post', '/api/task-types', {board_id: board.id, name: 'Issue'});
    const priority = await write('post', `/api/task-types/${type.id}/fields`, {
      name: 'Priority', field_type: 'dropdown', options: ['High', 'Medium', 'Low'], show_on_card: true,
    });
    const tasks = [];
    for (const [title, due_date, value] of [
      ['A: Later urgent task', '2026-11-05', 'High'],
      ['B: Earlier low priority', '2026-11-04', 'Low'],
      ['C: Earlier urgent task', '2026-11-04', 'High'],
      ['D: No due date', null, 'Medium'],
    ]) {
      const task = await write('post', '/api/tasks', {stage_id: source.id, title, due_date, task_type_id: type.id});
      await write('put', `/api/tasks/${task.id}`, {custom_fields: {[priority.id]: value}});
      tasks.push(task);
    }
    const saved = await write('post', '/api/filters', {board_id: board.id, name: 'Open work',
      definition: {op: 'and', rules: [{field: 'done', operator: 'eq', value: false}]}});
    await write('put', `/api/stages/${log.id}/config`, {is_log: true, filter_id: saved.id});
    const filterUrl = `${origin}/api/filters/${saved.id}`;
    const boardUrl = `${origin}/board/${board.id}`;
    const filtersUrl = `${boardUrl}/filters`;
    const sourceIds = tasks.map(task => task.id);
    const logCards = page.locator(`#stage-${log.id} .board-task-card`);
    async function cardIds(locator) {return (await locator.evaluateAll(cards => cards.map(card => Number(card.dataset.taskId))));}
    async function expectLog(expected) {
      await page.waitForFunction(({id, expected}) => {
        const ids = [...document.querySelectorAll(`#stage-${id} .board-task-card`)].map(card => Number(card.dataset.taskId));
        return JSON.stringify(ids) === JSON.stringify(expected);
      }, {id: log.id, expected});
      assert.deepEqual(await cardIds(page.locator(`#stage-${source.id} .board-task-card`)), sourceIds);
    }
    async function editFilter() {
      await page.goto(filtersUrl);
      await page.locator(`[data-action="edit-filter"][data-filter-id="${saved.id}"]`).click();
    }
    async function saveFilter() {
      const savedResponse = page.waitForResponse(response => response.url() === filterUrl && response.request().method() === 'PUT');
      await page.getByRole('button', {name: 'Save Filter', exact: true}).click();
      const response = await savedResponse;
      assert(response.ok(), await response.text());
      await page.locator('[data-action="save-filter"]').waitFor({state: 'hidden'});
      return response.json();
    }
    await page.goto(boardUrl);
    await expectLog([...sourceIds].reverse());
    await editFilter();
    assert.equal(await page.locator('[data-sort-rule]').count(), 0);
    assert((await page.locator('#filters-editor-container').innerText()).includes('newest objectives first'));
    await saveFilter();
    await page.goto(boardUrl);
    await expectLog([...sourceIds].reverse());
    await editFilter();
    await page.getByRole('button', {name: '+ Add sorting rule', exact: true}).click();
    await page.getByRole('button', {name: '+ Add sorting rule', exact: true}).click();
    await page.getByLabel('Sort field 2', {exact: true}).selectOption(`custom:${priority.id}`);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await page.locator('#filters-page').screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT});
    let result = await saveFilter();
    assert.deepEqual(result.definition.sort_rules, [{field: 'due_date', direction: 'asc'}, {field: `custom:${priority.id}`, direction: 'asc'}]);
    await page.goto(boardUrl);
    await expectLog([tasks[2].id, tasks[1].id, tasks[0].id, tasks[3].id]);
    // Change a custom field through the task modal; the log reorders immediately.
    await logCards.filter({hasText: tasks[2].title}).click();
    const modal = page.locator('#board-task-modal');
    const customField = modal.locator(`[data-field="modal-custom-field"][data-field-id="${priority.id}"]`);
    const update = page.waitForResponse(response => response.url() === `${origin}/api/tasks/${tasks[2].id}` && response.request().method() === 'PUT');
    await customField.selectOption('Low');
    await update;
    await expectLog([tasks[2].id, tasks[1].id, tasks[0].id, tasks[3].id]);
    // B becomes High, so it moves ahead of C within the same due date.
    await modal.locator('button[data-action="close-task-modal"]').click();
    await logCards.filter({hasText: tasks[1].title}).click();
    const updateB = page.waitForResponse(response => response.url() === `${origin}/api/tasks/${tasks[1].id}` && response.request().method() === 'PUT');
    await customField.selectOption('High');
    await updateB;
    await expectLog([tasks[1].id, tasks[2].id, tasks[0].id, tasks[3].id]);
    await editFilter();
    assert.equal(await page.getByLabel('Sort field 1', {exact: true}).inputValue(), 'due_date');
    assert.equal(await page.getByLabel('Sort field 2', {exact: true}).inputValue(), `custom:${priority.id}`);
    await page.getByRole('button', {name: 'Move sort rule 2 up', exact: true}).click();
    result = await saveFilter();
    assert.equal(result.definition.sort_rules[0].field, `custom:${priority.id}`);
    await page.goto(boardUrl);
    await expectLog([tasks[1].id, tasks[0].id, tasks[3].id, tasks[2].id]);
    await editFilter();
    await page.setViewportSize({width: 390, height: 844});
    await page.getByLabel('Sort direction 1', {exact: true}).selectOption('desc');
    const editor = page.locator('#filters-editor-container');
    assert(await editor.evaluate(el => el.scrollWidth <= el.clientWidth));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await page.locator('#filters-page').screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-mobile.png')});
    // A failed save retains the draft, including rule order and directions.
    await page.route(filterUrl, route => route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({detail: 'Test rejection'})}));
    await page.getByRole('button', {name: 'Save Filter', exact: true}).click();
    await page.getByRole('alert').waitFor();
    assert.equal(await page.getByLabel('Sort direction 1', {exact: true}).inputValue(), 'desc');
    await page.unroute(filterUrl);
    await saveFilter();
    await page.goto(boardUrl);
    await expectLog([tasks[2].id, tasks[3].id, tasks[1].id, tasks[0].id]);
    // Removing every rule restores the old newest-first order.
    await editFilter();
    await page.locator('[data-sort-rule="0"] [data-action="remove-sort"]').click();
    await page.locator('[data-sort-rule="0"] [data-action="remove-sort"]').click();
    await saveFilter();
    await page.goto(boardUrl);
    await expectLog([...sourceIds].reverse());
    assert.deepEqual(errors, []);
    console.log('Filter sorting browser checks passed: legacy ordering, multiple keys, custom fields, edit refresh, reorder, directions, failed save, clear, mobile.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => {if (server.exitCode !== null) resolve(); else server.once('exit', resolve);});
    await fs.rm(directory, {recursive: true, force: true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

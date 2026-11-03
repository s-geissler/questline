#!/usr/bin/env node
'use strict';

// End-to-end import check against a disposable application database.
// Requires Playwright/Chromium and the Python app dependencies. Optionally set
// QUESTLINE_TEST_PYTHON to a virtualenv Python and QUESTLINE_TEST_SCREENSHOT to a PNG path.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const exportData = {
  name: 'Browser Trello Hub',
  lists: [{ id: 'todo', name: 'To do', pos: 1 }, { id: 'done', name: 'Done', pos: 2 }],
  cards: [
    { id: 'active', idList: 'todo', name: 'Imported Objective', desc: 'Original description', pos: 1,
      idMembers: ['alice'], attachments: [{ name: 'Notes.pdf', url: 'https://trello.example/notes.pdf' }],
      idChecklists: ['check'] },
    { id: 'archived', idList: 'done', name: 'Archived Objective', closed: true },
  ],
  members: [{ id: 'alice', fullName: 'Alice Example', username: 'alice' }],
  checklists: [{ id: 'check', idCard: 'active', name: 'Checklist', checkItems: [{ name: 'Check result', state: 'complete', pos: 1 }] }],
};

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-trello-browser-'));
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(process.env.QUESTLINE_TEST_PYTHON || 'python', [
    '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(port), '--lifespan', 'off',
  ], {
    cwd: ROOT,
    env: { ...process.env, QUESTLINE_DATABASE_URL: `sqlite:///${path.join(directory, 'test.db')}`,
      QUESTLINE_ENV: 'development', QUESTLINE_ALLOW_INSECURE_COOKIES: 'true', QUESTLINE_AUDIT_LOG_PATH: '',
      QUESTLINE_PUBLIC_BASE_URL: origin },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let serverOutput = '';
  server.stderr.on('data', data => { serverOutput += data.toString(); });
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { ready = (await fetch(`${origin}/login`)).ok; } catch {}
      if (ready || server.exitCode !== null) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, serverOutput);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const registered = await page.request.post(`${origin}/api/auth/register`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      data: { email: 'browser-import@example.invalid', password: 'test-password-only', display_name: 'Browser Owner' },
    });
    assert.equal(registered.status(), 200, await registered.text());
    const cookies = await page.context().cookies();
    const headers = { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': cookies.find(cookie => cookie.name === 'questline_csrf').value };
    const file = { name: 'trello.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(exportData)) };

    await page.goto(origin);
    await page.getByRole('button', { name: 'Import from Trello', exact: true }).click();
    await page.locator('[data-trello-file]').setInputFiles(file);
    const dialog = page.getByRole('dialog', { name: 'Import from Trello' });
    await dialog.getByText('2 Stages · 1 Objective · 1 checklist item', { exact: true }).waitFor();
    assert.equal(await page.locator('[data-trello-file]').evaluate(input => input.files[0].name), 'trello.json');
    await dialog.getByRole('button', { name: 'Create Hub', exact: true }).click();
    await page.waitForURL(/\/board\/\d+$/);
    const boardId = Number(page.url().split('/').pop());
    const stages = await (await page.request.get(`${origin}/api/stages?board_id=${boardId}`)).json();
    assert.equal(stages.length, 2);
    assert.equal(stages[0].tasks.length, 1);
    assert(stages[0].tasks[0].description.includes('Alice Example (@alice)'));
    assert(stages[0].tasks[0].description.includes('[Notes.pdf](https://trello.example/notes.pdf)'));
    assert.equal(stages[0].tasks[0].checklist[0].done, true);

    assert.equal((await page.request.post(`${origin}/api/tasks`, { headers, data: { stage_id: stages[0].id, title: 'Remove me' } })).status(), 200);
    assert.equal((await page.request.post(`${origin}/api/automations`, { headers, data: {
      board_id: boardId, name: 'Remove this automation', trigger_type: 'task_created', action_type: 'set_done',
    } })).status(), 200);
    await page.locator('#board-settings-button').click();
    await page.getByRole('button', { name: 'Choose Trello export…', exact: true }).click();
    await page.locator('[data-trello-file]').setInputFiles(file);
    await dialog.getByText('2 Stages · 1 Objective · 1 checklist item', { exact: true }).waitFor();
    assert(await dialog.getByRole('button', { name: 'Replace content', exact: true }).isDisabled());
    assert((await dialog.innerText()).includes('all automations (1)'));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await page.screenshot({ path: process.env.QUESTLINE_TEST_SCREENSHOT });
    }
    await dialog.getByRole('checkbox').check();
    const navigation = page.waitForEvent('load');
    await dialog.getByRole('button', { name: 'Replace content', exact: true }).click();
    await navigation;
    const replaced = await (await page.request.get(`${origin}/api/stages?board_id=${boardId}`)).json();
    assert.equal(replaced.flatMap(stage => stage.tasks).length, 1);
    assert.notEqual(replaced[0].id, stages[0].id);
    assert.equal(replaced[0].tasks[0].done, false);
    assert.deepEqual(await (await page.request.get(`${origin}/api/automations?board_id=${boardId}`)).json(), []);

    await page.locator('#board-settings-button').click();
    await page.getByRole('button', { name: 'Choose Trello export…', exact: true }).click();
    await page.locator('[data-trello-file]').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{}') });
    await dialog.getByRole('alert').waitFor();
    assert(await dialog.getByRole('button', { name: 'Replace content', exact: true }).isDisabled());
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog', { name: 'Import from Trello' }).count(), 0);
    assert.deepEqual(errors, []);
    console.log('Trello browser checks passed: create, preview, replacement confirmation, metadata, deletion, invalid file, and cancel.');
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) {
      const exited = new Promise(resolve => server.once('exit', resolve));
      server.kill();
      await exited;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });

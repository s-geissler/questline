#!/usr/bin/env node
'use strict';

// Uses a disposable database and real Chromium clipboard image/text pastes.
// Document files use synthetic paste events because OS file clipboards vary.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-attachment-paste-'));
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
    const context = await browser.newContext({viewport: {width: 1280, height: 950},
      permissions: ['clipboard-read', 'clipboard-write']});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const registration = await page.request.post(`${origin}/api/auth/register`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'clipboard@example.invalid', password: 'test-password-only', display_name: 'Clipboard User'},
    });
    assert(registration.ok(), await registration.text());
    const cookies = await context.cookies();
    const headers = {'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': cookies.find(cookie => cookie.name === 'questline_csrf').value};
    async function create(route, data) {
      const response = await page.request.post(`${origin}${route}`, {headers, data});
      assert(response.ok(), await response.text());
      return response.json();
    }
    const board = await create('/api/boards', {name: 'Clipboard attachments'});
    const stage = await create('/api/stages', {board_id: board.id, name: 'Inbox'});
    const task = await create('/api/tasks', {stage_id: stage.id, title: 'Paste task'});
    const attachmentUrl = `${origin}/api/tasks/${task.id}/attachments`;
    let uploadCount = 0;
    page.on('request', request => {
      if (request.url() === attachmentUrl && request.method() === 'POST') uploadCount++;
    });
    await page.goto(`${origin}/board/${board.id}?task_id=${task.id}`);
    const modal = page.locator('#board-task-modal');
    const section = modal.locator('[data-role="task-attachments"]');
    await section.getByText('Paste an image or file', {exact: false}).waitFor();
    // Wait for attachment metadata to load through the normal modal lifecycle.
    await modal.locator('[data-action="modal-toggle-action-menu"]').click();
    await page.waitForFunction(() => document.querySelector('[data-action="modal-attach-file"]')?.disabled === false);
    await modal.locator('[data-action="modal-toggle-action-menu"]').click();

    async function copyImage() {
      await page.evaluate(async () => {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 2;
        canvas.getContext('2d').fillRect(0, 0, 2, 2);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        await navigator.clipboard.write([new ClipboardItem({'image/png': blob})]);
      });
    }
    async function pasteImage() {
      const saved = page.waitForResponse(response => response.url() === attachmentUrl
        && response.request().method() === 'POST');
      await page.keyboard.press('Control+v');
      const response = await saved;
      assert.equal(response.status(), 201, await response.text());
      const attachment = await response.json();
      await section.locator(`a[href$="/${attachment.id}/download"]`).waitFor();
      return attachment;
    }
    async function pasteFiles(files, selector = '[data-field="modal-description"]') {
      return page.evaluate(({files, selector}) => {
        const data = new DataTransfer();
        for (const file of files) data.items.add(new File([file.content], file.name, {type: file.type}));
        const event = new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true});
        (selector ? document.querySelector(selector) : document.body).dispatchEvent(event);
        return event.defaultPrevented;
      }, {files, selector});
    }

    // Image paste uploads while retaining the unsaved title, focus and cursor.
    const title = modal.locator('[data-field="modal-title"]');
    await title.fill('Draft title');
    await title.evaluate(element => element.setSelectionRange(5, 5));
    await copyImage();
    const image = await pasteImage();
    assert.equal(image.content_type, 'image/png');
    assert.equal(await title.inputValue(), 'Draft title');
    assert(await title.evaluate(element => document.activeElement === element && element.selectionStart === 5));
    const storedTask = await (await page.request.get(`${origin}/api/tasks/${task.id}`)).json();
    assert.equal(storedTask.title, 'Paste task');
    const imageDownload = await page.request.get(`${attachmentUrl}/${image.id}/download`);
    assert.deepEqual((await imageDownload.body()).subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    // Text-only Ctrl+V retains the input's native paste behavior.
    await page.evaluate(() => navigator.clipboard.writeText(' text'));
    await page.keyboard.press('Control+v');
    assert.equal(await title.inputValue(), 'Draft text title');
    assert.equal(uploadCount, 1);
    const titleSaved = page.waitForResponse(response => response.url() === `${origin}/api/tasks/${task.id}`
      && response.request().method() === 'PUT');
    await title.press('Tab');
    assert((await titleSaved).ok());
    await modal.locator('[data-action="modal-edit-description"]').click();
    const description = modal.locator('[data-field="modal-description"]');
    await description.fill('Description draft');
    await description.evaluate(element => element.setSelectionRange(3, 3));
    await copyImage();
    await pasteImage();
    assert.equal(await description.inputValue(), 'Description draft');
    assert(await description.evaluate(element => document.activeElement === element && element.selectionStart === 3));

    // Multiple clipboard files follow the same upload/download path.
    assert(await pasteFiles([
      {name: 'report.pdf', type: 'application/pdf', content: '%PDF-1.4\nclipboard document'},
      {name: 'notes.txt', type: 'text/plain', content: 'Clipboard notes'},
    ]));
    await section.getByRole('link', {name: 'notes.txt', exact: true}).waitFor();
    const documents = await (await page.request.get(attachmentUrl)).json();
    assert.equal(documents.length, 4);
    const report = documents.find(file => file.filename === 'report.pdf');
    assert.equal(await (await page.request.get(`${attachmentUrl}/${report.id}/download`)).text(), '%PDF-1.4\nclipboard document');
    assert.equal(await description.inputValue(), 'Description draft');
    assert(await description.evaluate(element => document.activeElement === element && element.selectionStart === 3));
    assert.equal(uploadCount, 4);
    // Count and size validation reject a whole paste before sending any files.
    await pasteFiles([
      {name: 'extra.txt', content: 'one'}, {name: 'too-many.txt', content: 'two'},
    ]);
    assert((await section.getByRole('alert').innerText()).includes('at most 5'));
    await pasteFiles([{name: 'large.txt', content: 'x'.repeat(10 * 1024 * 1024 + 1)}]);
    assert((await section.getByRole('alert').innerText()).includes('10 MiB'));
    assert.equal(uploadCount, 4);
    // Paste also works when the task is open without a focused text field.
    const descriptionSaved = page.waitForResponse(response => response.url() === `${origin}/api/tasks/${task.id}`
      && response.request().method() === 'PUT');
    await description.press('Tab');
    assert((await descriptionSaved).ok());
    await page.evaluate(() => document.activeElement.blur());
    await copyImage();
    await pasteImage();
    assert.equal(uploadCount, 5);
    assert.equal((await (await page.request.get(attachmentUrl)).json()).length, 5);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) {
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT});
      await page.setViewportSize({width: 390, height: 844});
      assert(await modal.locator('.task-modal-shell').evaluate(element => element.scrollWidth <= element.clientWidth));
      await page.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-mobile.png')});
    }
    await modal.locator('button[data-action="close-task-modal"]').click();
    assert(await page.locator(`[data-task-id="${task.id}"] [aria-label="Has attachments"]`).first().isVisible());
    assert.equal(await pasteFiles([{name: 'closed.txt', content: 'No open task'}], null), false);
    assert.equal(uploadCount, 5);
    assert.deepEqual(errors, []);
    console.log('Clipboard attachment browser checks passed (native image/text paste, documents, drafts, limits, downloads).');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => server.exitCode === null ? server.once('exit', resolve) : resolve());
    await fs.rm(directory, {recursive: true, force: true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

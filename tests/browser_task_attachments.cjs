#!/usr/bin/env node
'use strict';

// Real-browser upload regression check. Run with `node tests/browser_task_attachments.cjs`.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');

async function main() {
  const server = http.createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://fixture').pathname;
    if (request.method === 'GET' && pathname === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html' });
      response.end(`<!doctype html>
        <html><head><meta charset="utf-8">
          <link rel="stylesheet" href="/static/style.css">
          <script src="/static/base.js"></script>
          <script src="/static/board/api.js"></script>
          <script src="/static/board/board.js"></script>
        </head><body><div id="fixture"></div></body></html>`);
      return;
    }
    if (request.method === 'GET' && pathname.startsWith('/static/')) {
      const filePath = path.resolve(ROOT, `.${pathname}`);
      assert.ok(filePath.startsWith(`${ROOT}${path.sep}static${path.sep}`));
      const content = await fs.readFile(filePath);
      response.writeHead(200, {
        'Content-Type': filePath.endsWith('.css') ? 'text/css' : 'text/javascript',
        'Cache-Control': 'no-store',
      });
      response.end(content);
      return;
    }
    response.writeHead(404);
    response.end();
  });

  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    let uploadRequest = null;
    await page.route('**/api/tasks/42/attachments', async route => {
      const request = route.request();
      const headers = request.headers();
      const body = request.postDataBuffer();
      const match = headers['content-type']?.match(/boundary=([^;]+)/);
      const boundary = match?.[1];
      const validMultipart = boundary
        && body
        && body.subarray(0, Buffer.byteLength(`--${boundary}`))
          .equals(Buffer.from(`--${boundary}`))
        && body.includes(Buffer.from('filename="notes.txt"'))
        && body.includes(Buffer.from('\r\n\r\nhello\r\n'))
        && body.includes(Buffer.from(`\r\n--${boundary}--\r\n`));
      uploadRequest = {
        method: request.method(),
        contentType: headers['content-type'],
        bodyPrefix: body?.toString('latin1', 0, 80),
        validMultipart,
      };
      await route.fulfill({
        status: validMultipart ? 201 : 400,
        contentType: 'application/json',
        body: JSON.stringify(validMultipart
          ? { id: 1, filename: 'notes.txt', size_bytes: 5, content_type: 'text/plain' }
          : { detail: 'There was an error parsing the body' }),
      });
    });

    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.evaluate(() => {
      const root = document.createElement('div');
      root.id = 'board-root';
      const modal = document.createElement('div');
      modal.id = 'board-task-modal';
      root.append(modal);
      document.body.append(root);
      root.addEventListener('change', event => {
        window.__observedAttachmentChange = {
          field: event.target.dataset.field,
          files: event.target.files?.length || 0,
        };
      });

      const board = window._createBoard();
      board._el = root;
      board.taskModalEl = modal;
      board.currentBoardRole = 'owner';
      board.selectedTask = { id: 42, stage_id: 1, task_type_id: null, recurrence: null };
      board.showModal = true;
      board.taskActionMenuOpen = true;
      board.taskTypes = [];
      board.stages = [];
      board.renderTaskModal = () => {
        modal.innerHTML = `
          <div data-stop-propagation="true">
            <div data-role="modal-action-menu-anchor">
              <button data-action="modal-toggle-action-menu">☰</button>
              ${board._renderTaskActionMenuDropdown(board.selectedTask)}
              <input type="file" data-field="modal-attachment-file" class="hidden">
            </div>
          </div>`;
      };
      board.bindSurfaceEvents();
      board.renderTaskModal();
      window.__attachmentBoard = board;
    });

    const [fileChooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      page.locator('[data-action="modal-attach-file"]').click(),
    ]);
    await fileChooser.setFiles({
      name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('hello'),
    });
    try {
      await page.waitForFunction(() => (
        !window.__attachmentBoard.taskAttachmentsBusy
        && (window.__attachmentBoard.taskAttachments.length > 0
          || window.__attachmentBoard.taskAttachmentsError)
      ), null, { timeout: 5000 });
    } catch (error) {
      const state = await page.evaluate(() => ({
        busy: window.__attachmentBoard.taskAttachmentsBusy,
        attachments: window.__attachmentBoard.taskAttachments,
        error: window.__attachmentBoard.taskAttachmentsError,
        selectedFiles: document.querySelector('[data-field="modal-attachment-file"]')?.files.length,
        observedChange: window.__observedAttachmentChange,
      }));
      throw new Error(`${error.message}; board state=${JSON.stringify(state)}; request=${JSON.stringify(uploadRequest)}`);
    }

    assert.equal(uploadRequest?.method, 'POST', 'Selecting a file should send an upload request');
    assert.equal(uploadRequest.validMultipart, true, `Invalid multipart request: ${JSON.stringify(uploadRequest)}`);
    assert.equal(await page.evaluate(() => window.__attachmentBoard.taskAttachments.length), 1);
    assert.equal(await page.evaluate(() => window.__attachmentBoard.selectedTask.attachment_count), 1);
    const marginTop = await page.evaluate(() => {
      const probe = document.createElement('span');
      probe.className = 'task-card-attachment-indicator';
      document.body.append(probe);
      return getComputedStyle(probe).marginTop;
    });
    assert.equal(marginTop, '5px');
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

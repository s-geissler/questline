#!/usr/bin/env node
'use strict';

// Uses a disposable database. QUESTLINE_TEST_SCREENSHOT optionally saves the
// create-user dialog at desktop and mobile viewport sizes.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'questline-admin-registration-'));
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const usersUrl = `${origin}/api/admin/users`;
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
    const page = await browser.newPage({viewport: {width: 1200, height: 950}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const registration = await page.request.post(`${origin}/api/auth/register`, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      data: {email: 'admin@example.invalid', display_name: 'Admin', password: 'test-admin-password'},
    });
    assert(registration.ok(), await registration.text());
    const admin = await registration.json();
    await page.goto(`${origin}/admin`);
    await page.waitForFunction(() => document.getElementById('settings-registration-enabled')?.checked);
    await page.locator('#settings-registration-enabled').uncheck();
    const settingsSaved = page.waitForResponse(response => response.url().endsWith('/api/admin/settings') && response.request().method() === 'PUT');
    await page.getByRole('button', {name: 'Save settings', exact: true}).click();
    assert((await settingsSaved).ok());

    const guest = await browser.newContext();
    const publicPage = await guest.newPage();
    publicPage.on('pageerror', error => errors.push(error.message));
    await publicPage.goto(`${origin}/login`);
    assert.equal(await publicPage.locator('a[href="/register"]').count(), 0);
    const closed = await publicPage.goto(`${origin}/register`);
    assert.equal(closed.status(), 403);
    await publicPage.getByRole('heading', {name: 'Registration closed'}).waitFor();
    assert.equal(await publicPage.locator('#register-submit').count(), 0);

    const dialog = page.locator('#admin-create-user-dialog');
    const openButton = page.getByRole('button', {name: 'Create user', exact: true});
    await openButton.click();
    assert(await dialog.isVisible());
    const name = dialog.getByLabel('Display name (optional)', {exact: true});
    const email = dialog.getByLabel('Email', {exact: true});
    const password = dialog.getByLabel('Password', {exact: true});
    const confirm = dialog.getByLabel('Confirm password', {exact: true});
    const submit = dialog.locator('#admin-create-user-submit');
    await name.fill('New User <team>');
    await email.fill('new-user@example.invalid');
    await password.fill('test-user-password');
    await confirm.fill('different-password');
    await submit.click();
    assert.equal(await dialog.getByRole('alert').innerText(), 'Passwords do not match');
    await confirm.fill('test-user-password');

    // A network failure keeps the entered values and enables another attempt.
    await page.route(usersUrl, route => route.abort());
    await submit.click();
    await dialog.getByRole('alert').filter({hasText: 'Unable to create user'}).waitFor();
    assert.equal(await email.inputValue(), 'new-user@example.invalid');
    assert(await submit.isEnabled());
    await page.unroute(usersUrl);
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await dialog.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT});

    // Prevent duplicate submissions and dismissal while account creation runs.
    let releaseRequest;
    const gate = new Promise(resolve => {releaseRequest = resolve;});
    let requestStarted;
    const started = new Promise(resolve => {requestStarted = resolve;});
    let writes = 0;
    await page.route(usersUrl, async route => {
      writes++;
      requestStarted();
      await gate;
      await route.continue();
    });
    const createdResponse = page.waitForResponse(response => response.url() === usersUrl && response.request().method() === 'POST');
    await submit.click();
    await started;
    assert(await submit.isDisabled());
    await submit.evaluate(button => button.click());
    await page.keyboard.press('Escape');
    assert(await dialog.isVisible());
    releaseRequest();
    assert.equal((await createdResponse).status(), 201);
    await dialog.waitFor({state: 'hidden'});
    assert.equal(writes, 1);
    await page.unroute(usersUrl);
    assert((await page.locator('#admin-users-list').innerText()).includes('New User <team>'));
    assert.equal((await (await page.request.get(`${origin}/api/auth/me`)).json()).id, admin.id);

    await page.setViewportSize({width: 390, height: 844});
    await openButton.click();
    assert.equal(await password.inputValue(), '');
    await email.fill('new-user@example.invalid');
    await password.fill('test-user-password');
    await confirm.fill('test-user-password');
    await submit.click();
    await dialog.getByRole('alert').filter({hasText: 'already exists'}).waitFor();
    assert.equal(await email.inputValue(), 'new-user@example.invalid');
    await email.fill('inactive@example.invalid');
    await dialog.getByLabel('Active account', {exact: true}).uncheck();
    assert(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().width <= innerWidth));
    if (process.env.QUESTLINE_TEST_SCREENSHOT) await dialog.screenshot({path: process.env.QUESTLINE_TEST_SCREENSHOT.replace('.png', '-mobile.png')});
    const inactiveResponse = page.waitForResponse(response => response.url() === usersUrl && response.request().method() === 'POST');
    await submit.click();
    const inactive = await inactiveResponse;
    assert.equal(inactive.status(), 201);
    assert.equal((await inactive.json()).is_active, false);
    await dialog.waitFor({state: 'hidden'});
    await openButton.click();
    assert.equal(await email.inputValue(), '');
    assert(await dialog.getByLabel('Active account', {exact: true}).isChecked());
    await email.fill('cancelled@example.invalid');
    await dialog.getByRole('button', {name: 'Cancel', exact: true}).click();
    await openButton.click();
    assert.equal(await email.inputValue(), '');
    await page.keyboard.press('Escape');
    await dialog.waitFor({state: 'hidden'});

    await publicPage.goto(`${origin}/login`);
    await publicPage.locator('#login-email-input').fill('new-user@example.invalid');
    await publicPage.locator('#login-password-input').fill('test-user-password');
    await publicPage.getByRole('button', {name: 'Login', exact: true}).click();
    await publicPage.waitForURL(`${origin}/`);
    await guest.clearCookies();
    await page.locator('#settings-registration-enabled').check();
    const reopened = page.waitForResponse(response => response.url().endsWith('/api/admin/settings') && response.request().method() === 'PUT');
    await page.getByRole('button', {name: 'Save settings', exact: true}).click();
    assert((await reopened).ok());
    await publicPage.goto(`${origin}/login`);
    assert.equal(await publicPage.locator('a[href="/register"]').count(), 2);
    assert.deepEqual(errors, []);
    console.log('Admin registration browser checks passed, including closed registration, account creation, failures, retries, activation, and mobile.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => {
      if (server.exitCode !== null) resolve();
      else server.once('exit', resolve);
    });
    await fs.rm(directory, {recursive: true, force: true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});

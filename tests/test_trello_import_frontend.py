import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_import_js(script):
    bootstrap = f"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const redirects = [];
const context = {{
  FormData, Blob,
  document: {{addEventListener() {{}}, removeEventListener() {{}}}},
  window: {{location: {{assign(url) {{redirects.push(url);}}}}}},
  _escapeNavHtml(value) {{return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');}},
  async fetch(url, options) {{
    requests.push({{url, options}});
    return {{ok: true, async json() {{return {{board_id: 9, name: 'Imported', stage_count: 1, task_count: 2, checklist_item_count: 0, skipped_archived_card_count: 3, target_board: {{name: 'Existing', stage_count: 1, task_count: 1, automation_count: 0}}}};}}}};
  }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(ROOT / 'static' / 'trello_import.js'))}, 'utf8'), context);
const dialog = vm.runInContext('Object.create(TrelloImportDialog.prototype)', context);
Object.assign(dialog, {{
  boardId: null, boardName: '', file: new Blob(['{{}}'], {{type: 'application/json'}}),
  preview: null, busy: false, confirmed: false, error: '',
  root: {{innerHTML: '', querySelector() {{return {{focus() {{}}}};}}}},
}});
(async () => {{
{script}
}})().catch(error => {{console.error(error); process.exitCode = 1;}});
"""
    result = subprocess.run(["node", "-e", bootstrap], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_preview_upload_and_confirmation_protect_replacement():
    run_import_js("""
dialog.boardId = 42;
await dialog.loadPreview();
assert.equal(requests.length, 1);
assert.equal(requests[0].url, '/api/boards/import-trello/preview');
assert.equal(requests[0].options.body.get('board_id'), '42');
assert.equal(requests[0].options.body.get('confirm_replace'), null);
assert(requests[0].options.body.get('file') instanceof Blob);
await dialog.importFile();
assert.equal(requests.length, 1, 'Unconfirmed replacement must not submit');
dialog.confirmed = true;
await dialog.importFile();
assert.equal(requests.length, 2);
assert.equal(requests[1].url, '/api/boards/import-trello');
assert.equal(requests[1].options.body.get('confirm_replace'), 'true');
assert.deepEqual(redirects, ['/board/9']);
await dialog.importFile();
assert.equal(requests.length, 2, 'Repeated clicks while importing must not submit');
""")


def test_new_import_and_preview_validation_errors():
    run_import_js("""
dialog.file = {size: 10 * 1024 * 1024 + 1, name: 'oversized.json'};
await dialog.loadPreview();
assert.equal(requests.length, 0);
assert(dialog.error.includes('10 MiB'));
await dialog.importFile();
assert.equal(requests.length, 0);
dialog.file = new Blob(['{}']);
context.fetch = async () => ({ok: false, async json() {return {detail: 'Invalid export'};}});
await dialog.loadPreview();
assert.equal(dialog.error, 'Invalid export');
assert.equal(dialog.busy, false);
assert.equal(dialog.preview, null);
context.fetch = async (url, options) => {
  requests.push({url, options});
  return {ok: true, async json() {return {board_id: 5};}};
};
dialog.preview = {name: 'New', stage_count: 0, task_count: 0, checklist_item_count: 0, skipped_archived_card_count: 0};
await dialog.importFile();
assert.equal(requests.length, 1);
assert.equal(requests[0].options.body.get('board_id'), null);
assert.equal(requests[0].options.body.get('confirm_replace'), null);
assert.deepEqual(redirects, ['/board/5']);
""")


def test_import_dialog_escapes_export_metadata_and_explains_replacement():
    run_import_js(r"""
dialog.boardId = 42;
dialog.file = {name: '<img src=x onerror=alert(1)>.json'};
dialog.error = '<script>bad</script>';
dialog.preview = {
  name: '<svg onload=alert(1)>', stage_count: 2, task_count: 3, checklist_item_count: 4,
  skipped_archived_card_count: 5,
  target_board: {name: '<img src=x>', stage_count: 6, task_count: 7, automation_count: 8},
};
dialog.render();
const html = dialog.root.innerHTML;
assert(!html.includes('<img'));
assert(!html.includes('<svg'));
assert(!html.includes('<script>'));
assert(html.includes('all automations (8)'));
assert(html.includes('Calendar Stage selections'));
assert(html.includes('role="dialog"'));
assert(html.includes('data-trello-confirm'));
assert(/data-trello-action="import"\s+disabled/.test(html));
""")

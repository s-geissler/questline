import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_board_js(script: str):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_task_card_custom_field_chip_uses_loaded_task_type_option_color():
    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{
  document: {{ addEventListener() {{}} }},
  renderMarkdown(value) {{ return value || ''; }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);

const board = context._createBoard();
board.taskTypes = [{{
  id: 1,
  name: 'Bug',
  color: null,
  custom_fields: [{{
    id: 10,
    name: 'Priority',
    field_type: 'dropdown',
    show_on_card: true,
    options: [{{label: 'High', color: '#ef4444'}}],
  }}],
}}];

const staleTask = {{
  id: 42,
  title: 'Fix login',
  description: '',
  due_date: null,
  done: false,
  task_type_id: 1,
  task_type: {{
    id: 1,
    name: 'Bug',
    color: null,
    custom_fields: [{{
      id: 10,
      name: 'Priority',
      field_type: 'dropdown',
      show_on_card: true,
      options: [],
    }}],
  }},
  custom_field_values: {{'10': 'High'}},
  checklist: [],
  recurrence: null,
}};

const html = board.renderTaskCard(staleTask, {{id: 1, is_log: false}});
assert(html.includes('swatch-ef4444'), html);
"""

    run_board_js(script)


def test_task_card_custom_field_chips_emit_arbitrary_option_color_classes():
    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{
  document: {{ addEventListener() {{}} }},
  renderMarkdown(value) {{ return value || ''; }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);

const board = context._createBoard();
const task = {{
  id: 42,
  title: 'Fix login',
  description: '',
  due_date: null,
  done: false,
  task_type_id: 1,
  task_type: {{
    id: 1,
    name: 'Bug',
    color: null,
    custom_fields: [
      {{
        id: 10,
        name: 'Impact',
        field_type: 'dropdown',
        show_on_card: true,
        options: [{{label: 'Major', color: '#123456'}}],
      }},
      {{
        id: 11,
        name: 'Risk',
        field_type: 'dropdown',
        show_on_card: true,
        options: [{{label: 'Open', color: '#abcdef'}}],
      }},
    ],
  }},
  custom_field_values: {{'10': 'Major', '11': 'Open'}},
  checklist: [],
  recurrence: null,
}};

const html = board.renderTaskCard(task, {{id: 1, is_log: false}});
assert(html.includes('Impact: Major'), html);
assert(html.includes('Risk: Open'), html);
assert(html.includes('swatch-123456'), html);
assert(html.includes('swatch-abcdef'), html);
"""

    run_board_js(script)


def test_task_card_custom_field_chip_ignores_invalid_option_color_and_uses_field_color():
    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{
  document: {{ addEventListener() {{}} }},
  renderMarkdown(value) {{ return value || ''; }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);

const board = context._createBoard();
const task = {{
  id: 42,
  title: 'Architecture Simulation',
  description: '',
  due_date: null,
  done: false,
  task_type_id: 1,
  task_type: {{
    id: 1,
    name: 'Paper',
    color: null,
    custom_fields: [{{
      id: 10,
      name: 'Assi',
      field_type: 'dropdown',
      color: '#3b82f6',
      show_on_card: true,
      options: [{{label: 'David', color: 'None'}}],
    }}],
  }},
  custom_field_values: {{'10': 'David'}},
  checklist: [],
  recurrence: null,
}};

const html = board.renderTaskCard(task, {{id: 1, is_log: false}});
assert(html.includes('Assi: David'), html);
assert(html.includes('swatch-3b82f6'), html);
assert(!html.includes('swatch-empty'), html);
"""

    run_board_js(script)


def test_task_type_color_popover_toggle_click_is_not_immediately_closed():
    task_types_js = ROOT / "static" / "task_types.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{
  document: {{ addEventListener() {{}} }},
  PRESET_COLORS: ['#ef4444'],
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(task_types_js))}, 'utf8') + '\\nglobalThis.TaskTypesPageController = TaskTypesPageController;', context);

const controller = Object.create(context.TaskTypesPageController.prototype);
let closed = false;
controller.activePopover = {{kind: 'type-color', typeId: 1, fieldId: null, optionIndex: null}};
controller.root = {{ contains() {{ return true; }} }};
controller.closePopover = () => {{ closed = true; controller.activePopover = null; }};

controller.handleDocumentClick({{
  target: {{
    closest(selector) {{
      return selector === '[data-action^="toggle-"]' ? this : null;
    }},
  }},
}});

assert.equal(closed, false);
assert(controller.activePopover);
"""

    run_board_js(script)


def test_cancel_new_stage_reinitializes_task_drag_sortables():
    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{
  document: {{ addEventListener() {{}} }},
  requestAnimationFrame(callback) {{ callback(); }},
  renderMarkdown(value) {{ return value || ''; }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);

const board = context._createBoard();
board.showNewStage = true;
board.newStageName = 'Aborted stage';
board.readonlyBannerEl = {{ classList: {{ toggle() {{}} }}, innerHTML: '' }};
board.renderReadonlyBanner = () => {{}};
board.renderViewToggle = () => {{}};
board.renderCalendarToolbar = () => {{}};
board.renderStagesView = () => {{}};
board.renderCalendarView = () => {{}};
board.renderCalendarCreateModal = () => {{}};
board.renderSettingsModal = () => {{}};
board.renderTaskModal = () => {{}};
board.renderLogConfigModal = () => {{}};
board.updateStageDropTargetVisibility = () => {{}};

let initCount = 0;
board.initSortable = () => {{ initCount += 1; }};

board.cancelNewStage();

assert.equal(board.showNewStage, false);
assert.equal(board.newStageName, '');
assert.equal(initCount, 1);
"""

    run_board_js(script)


def test_task_attachment_section_escapes_names_and_respects_viewer_permissions():
    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{ document: {{ addEventListener() {{}} }} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);

const board = context._createBoard();
board.taskAttachments = [{{
  id: 7,
  filename: '<img src=x onerror=alert(1)>.txt',
  size_bytes: 1024,
}}];
board.taskAttachmentsLoading = false;
board.taskAttachmentsBusy = false;
board.taskAttachmentsError = '';

const editableHtml = board._renderTaskAttachmentsSection({{id: 42}}, true);
assert(editableHtml.includes('&lt;img src=x onerror=alert(1)&gt;.txt'), editableHtml);
assert(!editableHtml.includes('<img src=x onerror=alert(1)>'), editableHtml);
assert(editableHtml.includes('/api/tasks/42/attachments/7/download'), editableHtml);
assert(editableHtml.includes('data-action="modal-delete-attachment"'), editableHtml);
assert(editableHtml.includes('1.0 KiB'), editableHtml);

const viewerHtml = board._renderTaskAttachmentsSection({{id: 42}}, false);
assert(viewerHtml.includes('/api/tasks/42/attachments/7/download'), viewerHtml);
assert(!viewerHtml.includes('data-field="modal-attachment-file"'), viewerHtml);
assert(!viewerHtml.includes('data-action="modal-delete-attachment"'), viewerHtml);

board.taskAttachments = [];
assert.equal(board._renderTaskAttachmentsSection({{id: 42}}, true), '');
board.taskAttachmentsLoading = false;
board.taskAttachmentsBusy = false;
board.taskActionMenuOpen = true;
const menu = board._renderTaskActionMenuDropdown({{id: 42, recurrence: null, task_type_id: null, stage_id: 1}});
assert(menu.includes('data-action="modal-attach-file"'), menu);
"""

    run_board_js(script)


def test_task_attachment_upload_uses_browser_multipart_boundary():
    api_js = ROOT / "static" / "board" / "api.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let request;
class FakeFormData {{
  constructor() {{ this.fields = []; }}
  append(name, value) {{ this.fields.push([name, value]); }}
}}
const context = {{
  FormData: FakeFormData,
  fetch(url, init) {{ request = {{url, init}}; return Promise.resolve({{ok: true}}); }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(api_js))}, 'utf8'), context);

(async () => {{
  const file = {{name: 'notes.txt'}};
  await context.apiUploadTaskAttachment(42, file);
  assert.equal(request.url, '/api/tasks/42/attachments');
  assert.equal(request.init.method, 'POST');
  assert(request.init.body instanceof FakeFormData);
  assert.deepEqual(request.init.body.fields, [['file', file]]);
  assert.equal(request.init.headers, undefined);
}})().catch(error => {{ console.error(error); process.exitCode = 1; }});
"""

    run_board_js(script)


def test_task_card_shows_paperclip_only_when_attachments_exist():
    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const context = {{
  document: {{ addEventListener() {{}} }},
  renderMarkdown(value) {{ return value || ''; }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);

const board = context._createBoard();
const task = {{
  id: 42,
  title: 'Task',
  description: 'Has details',
  done: false,
  checklist: [],
  custom_field_values: {{}},
  recurrence: null,
  attachment_count: 1,
}};
const stage = {{id: 1, is_log: false}};
const withAttachment = board.renderTaskCard(task, stage);
const descriptionIndicator = withAttachment.indexOf('aria-label="Has description"');
const paperclipIndicator = withAttachment.indexOf('aria-label="Has attachments"');
const metadataRow = withAttachment.indexOf('class="flex items-center gap-1.5 mt-1.5 flex-wrap"');
assert(descriptionIndicator >= 0, withAttachment);
assert(paperclipIndicator > descriptionIndicator, withAttachment);
assert(paperclipIndicator < metadataRow, withAttachment);
assert(withAttachment.includes('width="11" height="11"'), withAttachment);
assert(withAttachment.includes('class="task-card-attachment-indicator inline-flex'), withAttachment);

const withoutAttachment = board.renderTaskCard({{...task, attachment_count: 0}}, stage);
assert(!withoutAttachment.includes('aria-label="Has attachments"'), withoutAttachment);
"""

    run_board_js(script)

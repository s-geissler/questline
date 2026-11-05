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


def test_sorted_log_refresh_ignores_stale_responses_and_leaves_source_stages_alone():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const context = {document: {addEventListener() {}},
  apiGetStages: () => new Promise(resolve => requests.push(resolve))};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.renderBoardSurface = () => {};
board.stages = [{id: 1, tasks: [{id: 1}, {id: 2}]}];
(async () => {
  await board.refreshSortedLogStages();
  assert.equal(requests.length, 0);
  board.stages.push({id: 2, is_log: true, tasks: [{id: 1}, {id: 2}], saved_filter: {
    definition: {sort_rules: [{field: 'title', direction: 'asc'}]}}});
  board.stages.push({id: 3, is_log: true, tasks: [{id: 2}, {id: 1}]});
  const old = board.refreshSortedLogStages();
  const current = board.refreshSortedLogStages();
  requests[1]([{id: 1, tasks: [{id: 2}, {id: 1}]}, {id: 2, tasks: [{id: 2}, {id: 1}]}, {id: 3, tasks: []}]);
  await current;
  requests[0]([{id: 2, tasks: [{id: 1}, {id: 2}]}]);
  await old;
  assert.deepEqual(JSON.parse(JSON.stringify(board.stages.map(stage => stage.tasks.map(task => task.id)))), [[1, 2], [2, 1], [2, 1]]);
})().catch(error => {console.error(error); process.exitCode = 1;});
""")


def test_history_escapes_user_content_and_uses_absolute_local_timestamps():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {addEventListener() {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
assert.equal(board.taskHistoryExpanded, false);
assert(board.taskHistoryContentHtml().includes('No history recorded yet.'));
board.taskHistory = [{id: 1, message: 'Checklist item renamed',
  actor_name: '<img src=x onerror=alert(1)>', subject: '<script>unsafe</script>',
  created_at: '2026-11-03T13:22:00.000000Z'}];
const html = board.taskHistoryContentHtml();
assert(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
assert(!html.includes('<script>'));
assert(html.includes('datetime="2026-11-03T13:22:00.000000Z"'));
assert(html.includes('2026'));
""")


def test_history_ignores_stale_task_responses_and_preserves_events_on_load_failure():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const context = {document: {addEventListener() {}},
  apiGetTaskHistory: (taskId, beforeId) => new Promise(resolve => requests.push({taskId, beforeId, resolve})),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.renderTaskModal = () => {};
board.renderTaskHistory = () => {};
board.showModal = true;
board.selectedTask = {id: 1};
const reply = (index, items, next_before_id = null) => requests[index].resolve({
  ok: true, json: async () => ({items, next_before_id})});
(async () => {
  board.refreshTaskHistory();
  assert.equal(requests.length, 0);
  const first = board.toggleTaskHistory();
  assert.equal(requests[0].taskId, 1);
  board.resetTaskHistory();
  board.selectedTask = {id: 2};
  const second = board.toggleTaskHistory();
  reply(0, [{id: 1, message: 'Old task'}]);
  await first;
  assert.equal(board.taskHistory.length, 0);
  assert.equal(board.taskHistoryLoading, true);
  reply(1, [{id: 20, message: 'New task'}], 20);
  await second;
  assert.equal(board.taskHistory[0].id, 20);
  const more = board.loadTaskHistory(true);
  assert.equal(requests[2].beforeId, 20);
  reply(2, [{id: 19}], 19);
  await more;
  assert.deepEqual(Array.from(board.taskHistory, event => event.id), [20, 19]);
  const failed = board.loadTaskHistory(true);
  requests[3].resolve({ok: false, json: async () => ({detail: 'History unavailable'})});
  await failed;
  assert.equal(board.taskHistoryError, 'History unavailable');
  assert.equal(board.taskHistoryLoading, false);
  assert.equal(board.taskHistoryNextId, 19);
  assert.deepEqual(Array.from(board.taskHistory, event => event.id), [20, 19]);
  const retry = board.loadTaskHistory(true);
  reply(4, [{id: 18}]);
  await retry;
  assert.equal(board.taskHistoryError, '');
  assert.equal(board.taskHistoryNextId, null);
  assert.deepEqual(Array.from(board.taskHistory, event => event.id), [20, 19, 18]);
  await board.toggleTaskHistory();
  board.refreshTaskHistory();
  assert.equal(requests.length, 5);
})().catch(error => {console.error(error); process.exitCode = 1;});
""")


def test_assignee_initial_pills_escape_names_and_support_single_names_and_unicode():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {addEventListener() {}}, renderMarkdown: value => value || ''};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
const users = [
  {id: 1, display_name: ' Alice   Adams '},
  {id: 2, display_name: 'Björk'},
  {id: 3, display_name: 'Éva 東京'},
  {id: 4, display_name: '<script> unsafe'},
];
assert.equal(board.assigneeInitials(users[0]), 'AA');
assert.equal(board.assigneeInitials(users[1]), 'B');
assert.equal(board.assigneeInitials(users[2]), 'É東');
const html = board.renderTaskCard({id: 1, title: 'Task', assignees: users}, {id: 1});
assert.equal((html.match(/class="task-assignee-pill task-assignee-color-[0-7]"/g) || []).length, 4);
assert(html.includes('>AA</span>'));
assert(html.includes('title=" Alice   Adams "'));
assert(html.includes('aria-label="Assigned to Éva 東京"'));
assert(!html.includes('@ Alice'));
assert(!html.includes('<script>'));
// Old serialized tasks can still be displayed.
assert(board.renderTaskCard({id: 2, title: 'Legacy', assignee: users[0]}, {id: 1}).includes('>AA</span>'));
""")


def test_assignee_picker_sends_full_list_and_recovers_after_failed_save():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const writes = [];
let fail = false;
const users = [{id: 1, display_name: 'Alice Adams'}, {id: 2, display_name: 'Bob Brown'}];
const context = {document: {addEventListener() {}},
  apiUpdateTask: async (id, body) => {
    writes.push(body);
    return {ok: !fail, json: async () => fail ? {detail: 'Save rejected'} : {
      id, assignee_user_ids: body.assignee_user_ids,
      assignees: users.filter(user => body.assignee_user_ids.includes(user.id)),
    }};
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.currentBoardRole = 'owner';
board.selectedTask = {id: 7, assignee_user_ids: [1], assignees: [users[0]]};
board.assigneePickerOpen = true;
board.boardMembers = users.map(user => ({...user, user_id: user.id, is_active: true}));
board.renderTaskModal = () => {};
board._syncTaskInStages = () => {};
(async () => {
  await board.updateAssignee(2, true);
  assert.deepEqual(JSON.parse(JSON.stringify(writes[0])), {assignee_user_ids: [1, 2]});
  assert.equal(board.assigneePickerOpen, true);
  assert.equal(board.assigneeSaving, false);
  fail = true;
  await board.updateAssignee(1, false);
  assert.deepEqual(JSON.parse(JSON.stringify(board.selectedTask.assignee_user_ids)), [1, 2]);
  assert.equal(board.assigneeError, 'Save rejected');
  assert(board.assigneePickerHtml(board.selectedTask).includes('role="alert"'));
  fail = false;
  await board.updateAssignee(1, false);
  assert.deepEqual(JSON.parse(JSON.stringify(board.selectedTask.assignee_user_ids)), [2]);
  await board.updateAssignee(2, false);
  assert.equal(board.taskAssigneeIds(board.selectedTask).length, 0);
  board.currentBoardRole = 'viewer';
  assert(/data-action="modal-toggle-assignees" disabled/.test(board.assigneePickerHtml(board.selectedTask)));
  await board.updateAssignee(1, true);
  assert.equal(writes.length, 4);
})().catch(error => {console.error(error); process.exitCode = 1;});
""")


def test_single_deadline_control_and_combined_picker_respect_viewer_permissions():
    script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {addEventListener() {}}, renderMarkdown: value => value || '', PRESET_COLORS: []};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.currentBoardRole = 'owner';
board.taskModalEl = {innerHTML: ''};
board.showModal = true;
board.selectedTask = {id: 1, title: 'Deadline', stage_id: 1, checklist: [], due_date: null};
board.renderTaskModal();
let html = board.taskModalEl.innerHTML;
assert(html.includes('No due date'));
assert.equal((html.match(/data-action="modal-toggle-deadline"/g) || []).length, 1);
assert(!html.includes('type="time"'));
assert(!html.includes('type="date"'));
board.selectedTask.due_date = '2026-11-03';
board.browserTimezone = () => 'Europe/Berlin';
board.openDeadlinePicker();
html = board.deadlinePickerHtml();
assert(html.includes('No time · all-day deadline'));
assert(html.includes('data-date="2026-11-03"'));
assert(html.includes('type="time"'));
Object.assign(board.selectedTask, {due_time: '14:30', due_timezone: 'Europe/Berlin', due_at: '2026-11-03T13:30:00Z'});
board.openDeadlinePicker();
board.renderTaskModal();
assert(board.taskModalEl.innerHTML.includes('14:30'));
assert(board.deadlinePickerHtml().includes('Europe/Berlin'));
assert(board.renderTaskCard(board.selectedTask, {id: 1}).includes('14:30 (Europe/Berlin)'));
assert(board.renderCalendarEntry(board.selectedTask, '2026-11-03').includes('14:30 (Europe/Berlin)'));
board.currentBoardRole = 'viewer';
board.deadlinePickerOpen = false;
board.renderTaskModal();
html = board.taskModalEl.innerHTML;
assert(/data-action="modal-toggle-deadline"[^>]*disabled/.test(html));
board.openDeadlinePicker();
assert.equal(board.deadlinePickerOpen, false);
"""
    run_board_js(script)


def test_combined_deadline_picker_saves_atomically_and_discards_cancelled_edits():
    script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const writes = [], alerts = [];
let fail = false;
const task = {id: 1, stage_id: 1, title: 'Deadline', due_date: '2026-11-03', due_time: null};
const context = {
  document: {addEventListener() {}}, alert: message => alerts.push(message),
  apiUpdateTask: async (id, body) => {
    writes.push({id, body});
    if (fail) return {ok: false, json: async () => ({detail: 'Rejected deadline'})};
    Object.assign(task, body);
    return {ok: true, json: async () => ({...task})};
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.currentBoardRole = 'owner';
board.selectedTask = {...task};
board.stages = [{id: 1, tasks: [{...task}]}];
board.renderBoardSurface = () => {};
board.renderTaskModal = () => {};
board.renderDeadlinePicker = () => {};
board.browserTimezone = () => 'Europe/Berlin';
(async () => {
  board.openDeadlinePicker();
  board.selectDeadlinePickerDate('2026-11-04');
  board.handleSurfaceInput({target: {dataset: {field: 'deadline-picker-time'}, value: '14:30'}});
  assert.equal(writes.length, 0);
  await board.saveDeadlinePicker();
  assert.deepEqual(JSON.parse(JSON.stringify(writes[0])), {id: 1, body: {due_date: '2026-11-04', due_time: '14:30', due_timezone: 'Europe/Berlin'}});
  assert.equal(board.stages[0].tasks[0].due_time, '14:30');
  assert.equal(board.deadlinePickerOpen, false);
  // Editing from another timezone retains the deadline's original timezone.
  board.browserTimezone = () => 'America/New_York';
  board.openDeadlinePicker();
  board.setDeadlinePickerTime('15:00');
  await board.saveDeadlinePicker();
  assert.equal(writes[1].body.due_timezone, 'Europe/Berlin');
  board.openDeadlinePicker();
  board.selectDeadlinePickerDate('2026-12-25');
  board.setDeadlinePickerTime('22:00');
  board.closeDeadlinePicker();
  assert.equal(writes.length, 2);
  assert.equal(board.selectedTask.due_date, '2026-11-04');
  assert.equal(board.selectedTask.due_time, '15:00');
  board.openDeadlinePicker();
  board.setDeadlinePickerTime('');
  await board.saveDeadlinePicker();
  assert.equal(board.selectedTask.due_time, null);
  fail = true;
  board.openDeadlinePicker();
  board.selectDeadlinePickerDate('2026-11-05');
  await board.saveDeadlinePicker();
  assert.equal(board.selectedTask.due_date, '2026-11-04');
  assert.equal(board.deadlinePickerOpen, true);
  assert.equal(board.deadlinePickerDate, '2026-11-05');
  assert.equal(board.deadlinePickerSaving, false);
  assert.deepEqual(alerts, ['Rejected deadline']);
  board.currentBoardRole = 'viewer';
  await board.saveDeadlinePicker();
  assert.equal(writes.length, 4);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    run_board_js(script)


def test_deadline_calendar_keyboard_navigation_handles_month_and_year_boundaries():
    script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {addEventListener() {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.renderDeadlinePicker = () => {};
board.deadlinePickerMonth = new Date('2028-01-01T12:00:00Z');
function key(date, key, shiftKey = false) {
  const handled = board.handleDeadlinePickerKeydown({target: {dataset: {date}}, key, shiftKey,
    preventDefault() {}, stopPropagation() {}});
  assert(handled);
  return board.deadlinePickerFocusDate;
}
assert.equal(key('2028-01-31', 'PageDown'), '2028-02-29');
assert.equal(key('2028-02-29', 'ArrowRight'), '2028-03-01');
assert.equal(key('2028-03-01', 'Home'), '2028-02-28');
assert.equal(key('2028-03-01', 'End'), '2028-03-05');
assert.equal(key('2028-02-29', 'PageDown', true), '2029-02-28');
board.deadlinePickerMonth = new Date('0001-01-01T12:00:00Z');
board.changeDeadlinePickerMonth(-1);
assert.equal(board.deadlinePickerMonth.getUTCFullYear(), 1);
assert.equal(board.deadlinePickerMonth.getUTCMonth(), 0);
board.deadlinePickerMonth = new Date('9999-12-01T12:00:00Z');
board.changeDeadlinePickerMonth(1);
assert.equal(board.deadlinePickerMonth.getUTCFullYear(), 9999);
assert.equal(board.deadlinePickerMonth.getUTCMonth(), 11);
"""
    run_board_js(script)


def test_timed_deadline_overdue_and_ordering_use_the_deadline_timezone():
    script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const now = Date.parse('2026-11-03T00:15:00Z');
class FixedDate extends Date {
  constructor(...args) {super(...(args.length ? args : [now]));}
  static now() {return now;}
}
const context = {Date: FixedDate, document: {addEventListener() {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
const task = {due_date: '2026-11-02', due_time: '18:00', due_timezone: 'America/Los_Angeles', due_at: '2026-11-03T02:00:00Z'};
assert.equal(board.dueDateClass(task.due_date, task), 'due-date-today');
assert.equal(board.dueDateClass(task.due_date, {...task, due_at: '2026-11-03T00:00:00Z'}), 'due-date-overdue');
assert.equal(board.dueDateClass('2026-11-02'), 'due-date-overdue');
const dateOnly = {id: 1, due_date: '2026-11-03'};
const berlin = {id: 2, due_date: '2026-11-03', due_time: '14:30', due_at: '2026-11-03T13:30:00Z'};
const utc = {id: 3, due_date: '2026-11-03', due_time: '14:00', due_at: '2026-11-03T14:00:00Z'};
const undated = {id: 4};
const ordered = [undated, utc, berlin, dateOnly].sort((a, b) => board.compareTaskDeadlines(a, b));
assert.deepEqual(ordered.map(task => task.id), [1, 2, 3, 4]);
// Calendar moves send only a new date so the API preserves optional time fields.
board.stages = [{id: 1, tasks: [{...berlin, title: 'Timed'}]}];
board.loadStages = async () => {};
let payload;
context.apiUpdateTask = async (id, body) => {payload = body; return {ok: true};};
(async () => {
  await board.handleCalendarTaskDrop(2, '2026-11-05');
  assert.deepEqual(JSON.parse(JSON.stringify(payload)), {due_date: '2026-11-05'});
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    run_board_js(script)


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
assert(board._renderTaskAttachmentsSection({{id: 42}}, true).includes('Ctrl+V'));
assert.equal(board._renderTaskAttachmentsSection({{id: 42}}, false), '');
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


def test_task_attachment_paste_only_handles_files_for_an_editable_open_task():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const document = {addEventListener() {}, body: {}, documentElement: {}};
const context = {document};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
const editor = {};
board.taskModalEl = {contains: target => target === editor};
board.selectedTask = {id: 42};
board.showModal = true;
board.currentBoardRole = 'editor';
const uploads = [];
board.uploadTaskAttachments = files => uploads.push(files);
function paste(files, target = editor, defaultPrevented = false) {
  const event = {target, defaultPrevented, clipboardData: {files},
    preventDefault() { this.defaultPrevented = true; }};
  board.handleTaskAttachmentPaste(event);
  return event.defaultPrevented;
}
assert.equal(paste([]), false, 'Text and HTML paste keep their native behavior');
const image = {name: 'image.png', type: 'image/png'};
const documentFile = {name: 'report.pdf', type: 'application/pdf'};
assert.equal(paste([image, documentFile]), true);
assert.deepEqual(Array.from(uploads[0]), [image, documentFile]);
assert.equal(paste([image], document.body), true, 'Paste works without a focused editor');
assert.equal(paste([image], {}), false, 'Inputs outside the task retain their behavior');
assert.equal(paste([image], editor, true), true, 'An earlier handler can consume the event');
board.currentBoardRole = 'viewer';
assert.equal(paste([image]), false);
board.currentBoardRole = 'owner';
board.showModal = false;
assert.equal(paste([image]), false);
board.showModal = true;
board.selectedTask = null;
assert.equal(paste([image]), false);
assert.equal(uploads.length, 2);
""")


def test_task_attachment_batches_validate_limits_and_serialize_uploads():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const context = {document: {addEventListener() {}},
  apiUploadTaskAttachment: (taskId, file) => new Promise((resolve, reject) => {
    requests.push({taskId, file, resolve, reject});
  })};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.selectedTask = {id: 42};
board.currentBoardRole = 'owner';
board.renderTaskAttachments = () => {};
const syncs = [];
board._syncTaskInStages = (task, options) => syncs.push({task, options});
const files = [{name: 'image.png', size: 30}, {name: 'report.pdf', size: 40}];
const reply = (index, payload, ok = true) => requests[index].resolve({ok,
  json: async () => payload});
(async () => {
  await board.uploadTaskAttachments([files[0], {size: 10 * 1024 * 1024 + 1}]);
  assert(board.taskAttachmentsError.includes('10 MiB'));
  assert.equal(requests.length, 0, 'The whole batch is checked before upload');
  board.taskAttachments = [{id: 1}, {id: 2}, {id: 3}, {id: 4}];
  await board.uploadTaskAttachments(files);
  assert(board.taskAttachmentsError.includes('at most 5'));
  assert.equal(requests.length, 0);
  board.taskAttachments = [];
  board.taskAttachmentsLoading = true;
  await board.uploadTaskAttachments(files);
  assert(board.taskAttachmentsError.includes('Wait'));
  assert.equal(requests.length, 0);
  board.taskAttachmentsLoading = false;
  const upload = board.uploadTaskAttachments(files);
  assert.equal(board.taskAttachmentsBusy, true);
  assert.equal(requests.length, 1);
  await board.uploadTaskAttachments(files);
  assert.equal(requests.length, 1, 'Repeated pastes cannot start concurrent uploads');
  reply(0, {id: 1, filename: files[0].name});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 2, 'The next file starts after the first is saved');
  assert.equal(requests[1].taskId, 42);
  reply(1, {id: 2, filename: files[1].name});
  await upload;
  assert.equal(board.taskAttachmentsBusy, false);
  assert.deepEqual(Array.from(board.taskAttachments, item => item.id), [1, 2]);
  assert.equal(board.selectedTask.attachment_count, 2);
  assert(syncs.every(sync => sync.options.renderTaskModal === false), 'Typing drafts survive count updates');

  const failed = board.uploadTaskAttachments([files[0], files[1], files[0]]);
  reply(2, {id: 3, filename: files[0].name});
  await new Promise(resolve => setImmediate(resolve));
  reply(3, {detail: 'Storage unavailable'}, false);
  await failed;
  assert.equal(requests.length, 4, 'A failed upload stops the batch');
  assert.deepEqual(Array.from(board.taskAttachments, item => item.id), [1, 2, 3]);
  assert.equal(board.taskAttachmentsError, 'Storage unavailable');
  assert.equal(board.taskAttachmentsBusy, false);
  const retry = board.uploadTaskAttachments([files[1]]);
  reply(4, {id: 4, filename: files[1].name});
  await retry;
  assert.equal(board.taskAttachmentsError, '');
  const networkFailure = board.uploadTaskAttachments([files[0]]);
  requests[5].reject(new Error('Connection lost'));
  await networkFailure;
  assert.equal(board.taskAttachmentsError, 'Connection lost');
  assert.equal(board.taskAttachmentsBusy, false);
})().catch(error => {console.error(error); process.exitCode = 1;});
""")


def test_task_attachment_batch_stops_when_the_task_is_closed_or_changed():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const context = {document: {addEventListener() {}},
  apiUploadTaskAttachment: (taskId, file) => new Promise(resolve => {
    requests.push({taskId, file, resolve});
  })};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
board.currentBoardRole = 'owner';
board.renderTaskModal = () => {};
board.renderTaskAttachments = () => {};
board.loadTaskAttachments = () => {};
board.syncTaskAttachmentCount = () => {throw new Error('Stale upload updated the task');};
const files = [{name: 'one.png', size: 30}, {name: 'two.pdf', size: 40}];
(async () => {
  board.selectedTask = {id: 42};
  const closed = board.uploadTaskAttachments(files);
  board.closeModal();
  requests[0].resolve({ok: true, json: async () => ({id: 1})});
  await closed;
  assert.equal(requests.length, 1, 'Closing a task stops remaining files');
  assert.equal(board.taskAttachments.length, 0);
  assert.equal(board.selectedTask, null);
  board.selectedTask = {id: 42};
  const switched = board.uploadTaskAttachments(files);
  board.selectedTask = {id: 99};
  board.beginTaskAttachmentLoad(99);
  requests[1].resolve({ok: true, json: async () => ({id: 2})});
  await switched;
  assert.equal(requests.length, 2, 'Files cannot spill into the next task');
  assert.equal(board.selectedTask.id, 99);
  assert.equal(board.taskAttachments.length, 0);
  assert.equal(board.taskAttachmentsLoading, true);
  assert.equal(board.taskAttachmentsError, '');
})().catch(error => {console.error(error); process.exitCode = 1;});
""")


def test_type_name_visibility_controls_board_and_calendar_card_pills():
    run_board_js("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {addEventListener() {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/board/board.js', 'utf8'), context);
const board = context._createBoard();
const stage = {id: 1, name: 'Inbox', tasks: []};
board.stages = [stage];
const type = {id: 4, name: 'Unique Type Name', color: '#ef4444'};
const task = {id: 10, title: 'A typed task', stage_id: 1, task_type_id: 4,
  task_type: type, color: type.color, due_date: '2026-11-05', done: false, checklist: [], custom_field_values: {}};
for (const hidden of [undefined, false, true]) {
  type.hide_name_on_card = hidden;
  const card = board.renderTaskCard(task, stage);
  const calendarCard = board.renderCalendarEntry(task, '2026-11-05');
  assert.equal(card.includes(type.name), hidden !== true);
  assert.equal(calendarCard.includes(type.name), hidden !== true);
  assert(card.includes('task-border-ef4444'), 'Type color applies when the name is hidden');
  assert(calendarCard.includes('task-border-ef4444'));
}
const untyped = {...task, task_type: null, task_type_id: null};
assert(!board.renderTaskCard(untyped, stage).includes(type.name));
assert(!board.renderCalendarEntry(untyped, '2026-11-05').includes(type.name));
""")


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

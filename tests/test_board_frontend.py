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
controller.root = {{ contains() {{ return false; }} }};
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

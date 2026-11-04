import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_filters_js(script):
    setup = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {addEventListener() {}}, PRESET_COLORS: []};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/filters.js', 'utf8') + '\\nglobalThis.Controller = FiltersPageController;', context);
const element = {classList: {toggle() {}}, addEventListener() {}, innerHTML: ''};
const root = {querySelector: () => element, addEventListener() {}};
const page = new context.Controller(root);
page.boardId = 1;
page.boardRole = 'owner';
page.currentUser = {display_name: 'Owner'};
page.taskTypes = [{id: 2, name: 'Issue', custom_fields: [{id: 7, name: 'Priority', field_type: 'dropdown'}]}];
const plain = value => JSON.parse(JSON.stringify(value));
"""
    response = subprocess.run(["node", "-e", setup + script], cwd=ROOT, text=True, capture_output=True)
    assert response.returncode == 0, response.stderr


def test_legacy_filter_editor_preserves_matching_and_only_sorts_when_requested():
    run_filters_js("""
page.filters = [{id: 1, name: 'Legacy', definition: {op: 'and', selected_task_type_id: 2,
  source_board_ids: [1], rules: [{field: 'custom:7', operator: 'eq', value: 'High'}]}}];
page.startEdit(1);
let definition = plain(page.normalizedDefinition());
assert.equal(definition.selected_task_type_id, 2);
assert.deepEqual(definition.rules, [{field: 'custom:7', operator: 'eq', value: 'High'}]);
assert.deepEqual(definition.sort_rules, []);
assert.equal(page.normalizeRule({field: 'done', operator: 'eq', value: false}).value, 'False');
assert.equal(page.normalizeRule({field: 'has_parent_task', operator: 'eq', value: true}).value, 'True');
assert(page.renderSortRules().includes('newest objectives first'));
page.addSortRule();
page.addSortRule();
page.handleChange({target: {dataset: {field: 'sort-field', sortIndex: '1'}, value: 'custom:7'}});
page.handleChange({target: {dataset: {field: 'sort-direction', sortIndex: '1'}, value: 'desc'}});
assert.deepEqual(plain(page.normalizedDefinition().sort_rules), [
  {field: 'due_date', direction: 'asc'}, {field: 'custom:7', direction: 'desc'},
]);
page.moveSortRule(1, -1);
assert.equal(page.normalizedDefinition().sort_rules[0].field, 'custom:7');
page.handleClick({target: {closest: () => ({dataset: {action: 'remove-sort', sortIndex: '0'}})}});
assert.deepEqual(plain(page.normalizedDefinition().sort_rules), [{field: 'due_date', direction: 'asc'}]);
page.handleClick({target: {closest: () => ({dataset: {action: 'remove-sort', sortIndex: '0'}})}});
assert.deepEqual(plain(page.normalizedDefinition().sort_rules), []);
assert.equal(page.filters[0].definition.sort_rules, undefined);
""")


def test_sort_summary_and_controls_escape_field_names_and_preserve_deleted_fields():
    run_filters_js("""
page.taskTypes[0].custom_fields[0].name = '<img src=x onerror=alert(1)>';
page.startCreate();
page.editingFilter.definition.sort_rules = [{field: 'custom:7', direction: 'asc'}, {field: 'custom:99', direction: 'desc'}];
let html = page.renderSortRules();
assert(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert(!html.includes('<img'));
assert(html.includes('Unavailable field'));
assert(html.includes('aria-label="Move sort rule 1 up" disabled'));
assert.deepEqual(plain(page.normalizedDefinition().sort_rules), [
  {field: 'custom:7', direction: 'asc'}, {field: 'custom:99', direction: 'desc'},
]);
page.filters = [{id: 1, name: 'Sort', definition: page.normalizedDefinition()}];
const summary = page.renderSavedFilter(page.filters[0]);
assert(summary.includes('Sort: Issue: &lt;img'));
page.boardRole = 'viewer';
assert(!page.renderSavedFilter(page.filters[0]).includes('data-action="edit-filter"'));
""")


def test_failed_save_keeps_sorting_draft_and_viewers_cannot_save():
    run_filters_js("""
let writes = 0;
context.fetch = async () => {writes++; return {ok: false, json: async () => ({detail: 'Invalid custom sort field'})};};
page.startCreate();
page.editingFilter.name = 'Keep my draft';
page.addSortRule();
(async () => {
  await page.saveFilter();
  assert.equal(page.editingFilter.name, 'Keep my draft');
  assert.equal(page.editingFilter.definition.sort_rules.length, 1);
  assert.equal(page.saving, false);
  assert(page.renderEditor().includes('role="alert"'));
  assert(page.renderEditor().includes('Invalid custom sort field'));
  page.boardRole = 'viewer';
  await page.saveFilter();
  assert.equal(writes, 1);
})().catch(error => {console.error(error); process.exitCode = 1;});
""")

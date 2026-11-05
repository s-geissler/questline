import subprocess
import unittest
from pathlib import Path


class TaskTypesFrontendTests(unittest.TestCase):
    def test_hide_type_name_checkbox_saves_rolls_back_and_respects_viewer_access(self):
        script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
const context = {document: {addEventListener() {}},
  fetch: (url, init) => new Promise((resolve, reject) => requests.push({url, init, resolve, reject}))};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/task_types.js', 'utf8'), context);
const Controller = vm.runInContext('TaskTypesPageController', context);
const controller = Object.create(Controller.prototype);
controller.boardRole = 'owner';
const type = {id: 4, name: 'Bug', hide_name_on_card: false};
controller.taskTypes = [type];
controller.renderColorPopover = () => '';
controller.render = () => {};
const originalSetter = controller.setTypeNameHidden;
let change;
controller.setTypeNameHidden = (typeId, hidden) => {change = {typeId, hidden};};
controller.handleChange({target: {dataset: {field: 'type-hide-name', typeId: '4'}, checked: true}});
assert.deepEqual(change, {typeId: 4, hidden: true});
controller.setTypeNameHidden = originalSetter;
function checkbox() {
  return controller.renderTaskTypeHeader(type).match(/<input[^>]+data-field="type-hide-name"[^>]*>/)[0];
}
(async () => {
  assert(!checkbox().includes(' checked'));
  assert(!checkbox().includes(' disabled'));
  const saved = controller.setTypeNameHidden(4, true);
  assert.equal(requests[0].url, '/api/task-types/4');
  assert.equal(requests[0].init.method, 'PUT');
  assert.deepEqual(JSON.parse(requests[0].init.body), {hide_name_on_card: true});
  assert(checkbox().includes(' disabled'));
  await controller.setTypeNameHidden(4, false);
  assert.equal(requests.length, 1, 'A pending save disables repeated changes');
  requests[0].resolve({ok: true, json: async () => ({hide_name_on_card: true})});
  await saved;
  assert.equal(type.hide_name_on_card, true);
  assert(checkbox().includes(' checked'));
  assert(!checkbox().includes(' disabled'));
  const failed = controller.setTypeNameHidden(4, false);
  requests[1].resolve({ok: false});
  await failed;
  assert.equal(type.hide_name_on_card, true);
  assert(type.nameVisibilityError.includes('Unable to update'));
  assert.equal(type.nameVisibilitySaving, false);
  const network = controller.setTypeNameHidden(4, false);
  requests[2].reject(new Error('Offline'));
  await network;
  assert.equal(type.hide_name_on_card, true);
  assert(type.nameVisibilityError.includes('Unable to update'));
  const retry = controller.setTypeNameHidden(4, false);
  requests[3].resolve({ok: true, json: async () => ({hide_name_on_card: false})});
  await retry;
  assert.equal(type.hide_name_on_card, false);
  assert.equal(type.nameVisibilityError, '');
  controller.boardRole = 'viewer';
  assert(checkbox().includes(' disabled'));
  await controller.setTypeNameHidden(4, true);
  assert.equal(requests.length, 4);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
        result = subprocess.run(["node", "-e", script], check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_task_types_color_popover_uses_stable_anchor_for_outside_click_detection(self):
        source = Path("static/task_types.js").read_text()

        self.assertIn('data-role="color-popover-anchor"', source)
        self.assertIn("closest('[data-role=\"color-popover-anchor\"]')", source)


if __name__ == "__main__":
    unittest.main()

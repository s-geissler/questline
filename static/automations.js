function _escapeAutoHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function _colorSwatchClass(color) {
  return color ? `swatch-${String(color).replace('#', '')}` : 'swatch-empty';
}

function _createAutomations() {
  return {
    boardId: 0,
    boardRole: null,
    automations: [],
    stages: [],
    taskTypes: [],
    showCreateForm: false,
    newAuto: {
      name: '',
      trigger_type: 'task_created',
      trigger_stage_id: '',
      action_type: 'move_to_stage',
      action_stage_id: '',
      action_task_type_id: '',
      action_color: null,
      action_days_offset: 7,
    },

    get canEdit() {
      return this.boardRole === 'owner' || this.boardRole === 'editor' || this.boardRole === 'admin';
    },

    async init() {
      const root = document.getElementById('automations-root');
      this.boardId = parseInt(root?.dataset.boardId || '0', 10);
      this.boardRole = JSON.parse(root?.dataset.boardRole || 'null');

      const [autoRes, stageRes, taskTypesRes] = await Promise.all([
        fetch('/api/automations?board_id=' + this.boardId),
        fetch('/api/stages?board_id=' + this.boardId),
        fetch('/api/task-types?board_id=' + this.boardId),
      ]);
      this.automations = await autoRes.json();
      this.stages = await stageRes.json();
      this.taskTypes = await taskTypesRes.json();

      this._updateReadonlyBanner();
      this._updateNewAutoButton();
      this._populateStageSelects();
      this._populateTaskTypeSelects();
      this.renderCreateForm();
      this.renderAutomations();
      this.bindEvents();
    },

    _updateReadonlyBanner() {
      const el = document.getElementById('readonly-banner');
      if (el) el.style.display = this.canEdit ? 'none' : 'block';
    },

    _updateNewAutoButton() {
      const el = document.getElementById('new-auto-btn');
      if (el) el.style.display = this.canEdit ? 'block' : 'none';
    },

    _populateStageSelects() {
      const triggerSelect = document.getElementById('auto-trigger-stage-id');
      const actionSelect = document.getElementById('auto-action-stage-id');
      const options = this.stages.map(s =>
        `<option value="${s.id}">${_escapeAutoHtml(s.name)}</option>`
      ).join('');
      if (triggerSelect) triggerSelect.innerHTML = '<option value="">Any stage</option>' + options;
      if (actionSelect) actionSelect.innerHTML = '<option value="">Select a stage...</option>' + options;
    },

    _populateTaskTypeSelects() {
      const select = document.getElementById('auto-action-task-type-id');
      if (!select) return;
      const options = this.taskTypes.map(tt =>
        `<option value="${tt.id}">${_escapeAutoHtml(tt.name)}</option>`
      ).join('');
      select.innerHTML = '<option value="">Select a type...</option>' + options;
    },

    _renderColorSwatches() {
      const container = document.getElementById('color-swatches');
      if (!container) return;
      const selected = this.newAuto.action_color;
      container.innerHTML = PRESET_COLORS.map(c => {
        const swatchClass = _colorSwatchClass(c);
        const ring = selected === c ? 'ring-2 ring-offset-2 ring-gray-500' : '';
        return `<button
          type="button"
          data-action="select-color"
          data-color="${c}"
          class="w-6 h-6 rounded-full border border-black/10 hover:scale-110 transition-transform ${swatchClass} ${ring}"
        ></button>`;
      }).join('') + `<button
        type="button"
        data-action="clear-color"
        class="w-6 h-6 rounded-full bg-gray-100 border border-dashed border-gray-300 flex items-center justify-center text-gray-400 text-xs hover:scale-110 transition-transform ${!selected ? 'ring-2 ring-offset-2 ring-gray-500' : ''}"
      >✕</button>`;
    },

    renderCreateForm() {
      const form = document.getElementById('create-form');
      if (!form) return;
      form.style.display = this.showCreateForm ? 'block' : 'none';

      const nameInput = document.getElementById('auto-name-input');
      const triggerType = document.getElementById('auto-trigger-type');
      const triggerStage = document.getElementById('auto-trigger-stage-id');
      const actionType = document.getElementById('auto-action-type');
      const actionStage = document.getElementById('auto-action-stage-id');
      const actionTaskType = document.getElementById('auto-action-task-type-id');
      const actionDays = document.getElementById('auto-action-days-offset');

      if (nameInput) nameInput.value = this.newAuto.name;
      if (triggerType) triggerType.value = this.newAuto.trigger_type;
      if (triggerStage) triggerStage.value = this.newAuto.trigger_stage_id;
      if (actionType) actionType.value = this.newAuto.action_type;
      if (actionStage) actionStage.value = this.newAuto.action_stage_id;
      if (actionTaskType) actionTaskType.value = this.newAuto.action_task_type_id;
      if (actionDays) actionDays.value = this.newAuto.action_days_offset;

      const stageDiv = document.getElementById('action-stage-div');
      const taskTypeDiv = document.getElementById('action-task-type-div');
      const daysDiv = document.getElementById('action-due-in-days-div');
      const colorDiv = document.getElementById('action-color-div');

      if (stageDiv) stageDiv.style.display = this.newAuto.action_type === 'move_to_stage' ? 'block' : 'none';
      if (taskTypeDiv) taskTypeDiv.style.display = this.newAuto.action_type === 'set_task_type' ? 'block' : 'none';
      if (daysDiv) daysDiv.style.display = this.newAuto.action_type === 'set_due_in_days' ? 'block' : 'none';
      if (colorDiv) {
        colorDiv.style.display = this.newAuto.action_type === 'set_color' ? 'block' : 'none';
        this._renderColorSwatches();
      }
    },

    renderAutomations() {
      const list = document.getElementById('automations-list');
      const empty = document.getElementById('automations-empty');
      if (!list) return;

      if (!this.automations.length) {
        list.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
      }

      if (empty) empty.style.display = 'none';

      list.innerHTML = this.automations.map(auto => {
        const disabledRing = auto.enabled ? '' : 'opacity-60';
        const toggleBg = auto.enabled ? 'bg-blue-500' : 'bg-gray-300';
        const toggleTranslate = auto.enabled ? 'translate-x-4' : 'translate-x-0';
        const title = auto.enabled ? 'Disable' : 'Enable';
        const canEditHtml = this.canEdit ? `<button
          data-action="toggle-enabled"
          data-auto-id="${auto.id}"
          class="flex-shrink-0 w-10 h-6 rounded-full transition-colors relative ${toggleBg}"
          title="${title}"
        >
          <span class="absolute left-0.5 top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${toggleTranslate}"></span>
        </button>` : '';

        return `<div class="bg-white rounded-xl shadow p-4 flex items-center gap-4 ${disabledRing}">
          ${canEditHtml}
          <div class="flex-1 min-w-0">
            <div class="font-medium text-gray-800 text-sm">${_escapeAutoHtml(auto.name)}</div>
            <div class="text-xs text-gray-400 mt-0.5">
              <span class="text-orange-500 font-medium">When</span>
              <span>${_escapeAutoHtml(this._triggerLabel(auto))}</span>
              <span class="mx-1 text-gray-300">→</span>
              <span class="text-green-600 font-medium">Then</span>
              <span>${_escapeAutoHtml(this._actionLabel(auto))}</span>
            </div>
          </div>
          ${this.canEdit ? `<button
            data-action="delete-auto"
            data-auto-id="${auto.id}"
            data-auto-name="${_escapeAutoHtml(auto.name)}"
            class="text-gray-300 hover:text-red-500 transition-colors text-xl leading-none flex-shrink-0"
            title="Delete automation"
          >×</button>` : ''}
        </div>`;
      }).join('');
    },

    _triggerLabel(auto) {
      const labels = {
        task_created: ' an objective is created',
        task_done: ' an objective is marked done',
        task_moved_to_stage: ' an objective moves into a stage',
        checklist_completed: ' a checklist is fully completed',
      };
      let label = labels[auto.trigger_type] || ' an automation event occurs';
      if (auto.trigger_stage_id) {
        const stage = this.stages.find(s => s.id === auto.trigger_stage_id);
        if (stage) label += ` in "${stage.name}"`;
      }
      return label;
    },

    _actionLabel(auto) {
      if (auto.action_type === 'move_to_stage') {
        let label = ' move to ';
        const stage = this.stages.find(s => s.id === auto.action_stage_id);
        label += stage ? `"${stage.name}"` : 'unknown stage';
        return label;
      }
      if (auto.action_type === 'set_done') return ' mark the objective as done';
      if (auto.action_type === 'set_task_type') {
        const taskType = this.taskTypes.find(t => t.id === auto.action_task_type_id);
        return ` set type to ${taskType ? `"${taskType.name}"` : 'unknown type'}`;
      }
      if (auto.action_type === 'set_color') return ' set card color';
      if (auto.action_type === 'set_due_in_days') return ` set due date to ${auto.action_days_offset ?? 0} day(s) from then`;
      return ' perform an action';
    },

    bindEvents() {
      const root = document.getElementById('automations-root');
      if (!root) return;

      root.addEventListener('click', event => {
        const action = event.target.closest('[data-action]')?.dataset.action;

        if (action === 'show-create-form') {
          this.showCreateForm = true;
          this.newAuto = {
            name: '',
            trigger_type: 'task_created',
            trigger_stage_id: '',
            action_type: 'move_to_stage',
            action_stage_id: '',
            action_task_type_id: '',
            action_color: null,
            action_days_offset: 7,
          };
          this.renderCreateForm();
          const nameInput = document.getElementById('auto-name-input');
          if (nameInput) nameInput.focus();
          return;
        }

        if (action === 'cancel-create-form') {
          this.showCreateForm = false;
          this.renderCreateForm();
          return;
        }

        if (action === 'create-auto') {
          this._readNewAutoFromDom();
          this.createAuto();
          return;
        }

        if (action === 'toggle-enabled') {
          const el = event.target.closest('[data-action]');
          const autoId = parseInt(el.dataset.autoId, 10);
          const auto = this.automations.find(a => a.id === autoId);
          if (auto) this.toggleEnabled(auto);
          return;
        }

        if (action === 'delete-auto') {
          const el = event.target.closest('[data-action]');
          const autoId = parseInt(el.dataset.autoId, 10);
          const autoName = el.dataset.autoName;
          if (confirm(`Delete automation "${autoName}"?`)) {
            this.deleteAuto(autoId);
          }
          return;
        }

        if (action === 'select-color') {
          const el = event.target.closest('[data-action]');
          this.newAuto.action_color = el.dataset.color;
          this._renderColorSwatches();
          return;
        }

        if (action === 'clear-color') {
          this.newAuto.action_color = null;
          this._renderColorSwatches();
          return;
        }
      });

      root.addEventListener('change', event => {
        const id = event.target.id;

        if (id === 'auto-trigger-type') {
          this.newAuto.trigger_type = event.target.value;
          return;
        }
        if (id === 'auto-trigger-stage-id') {
          this.newAuto.trigger_stage_id = event.target.value;
          return;
        }
        if (id === 'auto-action-type') {
          this.newAuto.action_type = event.target.value;
          this.renderCreateForm();
          return;
        }
        if (id === 'auto-action-stage-id') {
          this.newAuto.action_stage_id = event.target.value;
          return;
        }
        if (id === 'auto-action-task-type-id') {
          this.newAuto.action_task_type_id = event.target.value;
          return;
        }
      });

      root.addEventListener('input', event => {
        const id = event.target.id;
        if (id === 'auto-name-input') {
          this.newAuto.name = event.target.value;
          return;
        }
        if (id === 'auto-action-days-offset') {
          this.newAuto.action_days_offset = parseInt(event.target.value, 10) || 0;
          return;
        }
      });
    },

    _readNewAutoFromDom() {
      const nameInput = document.getElementById('auto-name-input');
      const triggerType = document.getElementById('auto-trigger-type');
      const triggerStage = document.getElementById('auto-trigger-stage-id');
      const actionType = document.getElementById('auto-action-type');
      const actionStage = document.getElementById('auto-action-stage-id');
      const actionTaskType = document.getElementById('auto-action-task-type-id');
      const actionDays = document.getElementById('auto-action-days-offset');

      if (nameInput) this.newAuto.name = nameInput.value;
      if (triggerType) this.newAuto.trigger_type = triggerType.value;
      if (triggerStage) this.newAuto.trigger_stage_id = triggerStage.value;
      if (actionType) this.newAuto.action_type = actionType.value;
      if (actionStage) this.newAuto.action_stage_id = actionStage.value;
      if (actionTaskType) this.newAuto.action_task_type_id = actionTaskType.value;
      if (actionDays) this.newAuto.action_days_offset = parseInt(actionDays.value, 10) || 7;
    },

    async createAuto() {
      if (!this.canEdit) return;
      if (!this.newAuto.name.trim()) {
        alert('Please enter a name for the automation.');
        return;
      }
      if (this.newAuto.action_type === 'move_to_stage' && !this.newAuto.action_stage_id) {
        alert('Please select a target stage for the action.');
        return;
      }
      if (this.newAuto.action_type === 'set_task_type' && !this.newAuto.action_task_type_id) {
        alert('Please select a target type for the action.');
        return;
      }
      if (this.newAuto.action_type === 'set_due_in_days' && (this.newAuto.action_days_offset === '' || this.newAuto.action_days_offset === null)) {
        alert('Please enter a number of days.');
        return;
      }

      const res = await fetch('/api/automations', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          name: this.newAuto.name.trim(),
          trigger_type: this.newAuto.trigger_type,
          trigger_stage_id: this.newAuto.trigger_stage_id ? parseInt(this.newAuto.trigger_stage_id, 10) : null,
          action_type: this.newAuto.action_type,
          action_stage_id: this.newAuto.action_stage_id ? parseInt(this.newAuto.action_stage_id, 10) : null,
          action_task_type_id: this.newAuto.action_task_type_id ? parseInt(this.newAuto.action_task_type_id, 10) : null,
          action_color: this.newAuto.action_color || null,
          action_days_offset: this.newAuto.action_type === 'set_due_in_days' ? parseInt(this.newAuto.action_days_offset, 10) : null,
          board_id: this.boardId,
        }),
      });

      const auto = await res.json();
      this.automations.push(auto);
      this.showCreateForm = false;
      this.renderCreateForm();
      this.renderAutomations();
    },

    async toggleEnabled(auto) {
      if (!this.canEdit) return;
      const res = await fetch(`/api/automations/${auto.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: !auto.enabled}),
      });
      const updated = await res.json();
      auto.enabled = updated.enabled;
      this.renderAutomations();
    },

    async deleteAuto(autoId) {
      if (!this.canEdit) return;
      await fetch(`/api/automations/${autoId}`, {method: 'DELETE'});
      this.automations = this.automations.filter(a => a.id !== autoId);
      this.renderAutomations();
    },
  };
}

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('automations-root');
  if (!el) return;
  const instance = _createAutomations();
  instance.init();
});

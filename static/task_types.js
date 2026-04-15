function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderSelected(selected, value) {
  return String(selected) === String(value) ? ' selected' : '';
}

function renderChecked(value) {
  return value ? ' checked' : '';
}

function renderDisabled(value) {
  return value ? ' disabled' : '';
}

function parsePageJson(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

class TaskTypesPageController {
  constructor(root) {
    this.root = root;
    this.boardId = 0;
    this.boardRole = null;
    this.boards = [];
    this.taskTypes = [];
    this.stages = [];
    this.stagesByBoard = {};
    this.showCreateForm = false;
    this.newType = {name: '', is_epic: false};
    this.createContainer = root.querySelector('#task-types-create-container');
    this.listContainer = root.querySelector('#task-types-list-container');
    this.emptyState = root.querySelector('#task-types-empty-state');
    this.readonlyBanner = root.querySelector('#task-types-readonly-banner');
    this.newButton = root.querySelector('#task-types-new-button');
    this.activePopover = null;
    this.bindEvents();
  }

  bindEvents() {
    this.root.addEventListener('click', event => this.handleClick(event));
    this.root.addEventListener('dblclick', event => this.handleDoubleClick(event));
    this.root.addEventListener('change', event => this.handleChange(event));
    this.root.addEventListener('input', event => this.handleInput(event));
    this.root.addEventListener('keydown', event => this.handleKeydown(event));
    this.root.addEventListener('blur', event => this.handleBlur(event), true);
    document.addEventListener('click', event => this.handleDocumentClick(event));
  }

  get canEdit() {
    return this.boardRole === 'owner' || this.boardRole === 'editor' || this.boardRole === 'admin';
  }

  asString(value) {
    return value === null || value === undefined ? '' : String(value);
  }

  colorSwatchClass(color) {
    return color ? `swatch-${String(color).replace('#', '')}` : 'swatch-empty';
  }

  selectedColorClass(currentColor, color) {
    return currentColor === color ? 'ring-2 ring-offset-1 ring-gray-500' : '';
  }

  paletteColorClass(currentColor, color) {
    return `${this.colorSwatchClass(color)} ${this.selectedColorClass(currentColor, color)}`.trim();
  }

  fieldShowOnCardTitle(field) {
    return field?.show_on_card
      ? 'Shown on card face - click to hide'
      : 'Hidden on card face - click to show';
  }

  blankNewField() {
    return {name: '', field_type: 'text', show_on_card: false, options: [], newOption: ''};
  }

  normalizeOption(option) {
    if (typeof option === 'string') return {label: option, color: null};
    return {
      label: option?.label || option?.value || '',
      color: option?.color || null,
    };
  }

  normalizeField(field) {
    return {
      ...field,
      newOption: '',
      options: (field.options || []).map(option => this.normalizeOption(option)),
    };
  }

  normalizeTaskType(tt) {
    return {
      ...tt,
      spawn_board_id: String(this.findBoardIdForSpawnStage(tt.spawn_stage_id) || this.boardId),
      available_spawn_stages: this.spawnStagesForBoard(this.findBoardIdForSpawnStage(tt.spawn_stage_id) || this.boardId),
      editing: false,
      editName: tt.name,
      showAddField: false,
      newField: this.blankNewField(),
      custom_fields: (tt.custom_fields || []).map(field => this.normalizeField(field)),
    };
  }

  taskTypeById(typeId) {
    return this.taskTypes.find(tt => tt.id === typeId) || null;
  }

  fieldById(tt, fieldId) {
    return tt?.custom_fields?.find(field => field.id === fieldId) || null;
  }

  parsePageData() {
    this.boardId = parseInt(this.root.dataset.boardId || '0', 10);
    this.boardRole = parsePageJson(this.root.dataset.boardRole, null);
    this.boards = parsePageJson(this.root.dataset.boards, []);
  }

  async init() {
    this.parsePageData();
    await this.load();
    this.render();
  }

  async load() {
    const [typesRes, stagesRes, ...boardStageResponses] = await Promise.all([
      fetch('/api/task-types?board_id=' + this.boardId),
      fetch('/api/stages?board_id=' + this.boardId),
      ...this.boards.map(board => fetch('/api/stages?board_id=' + board.id)),
    ]);
    const types = await typesRes.json();
    this.stages = await stagesRes.json();
    const boardStages = await Promise.all(boardStageResponses.map(res => res.json()));
    this.stagesByBoard = Object.fromEntries(
      this.boards.map((board, index) => [String(board.id), boardStages[index]])
    );
    this.taskTypes = types.map(tt => this.normalizeTaskType(tt));
  }

  spawnStagesForBoard(boardId) {
    return (this.stagesByBoard[String(boardId || this.boardId)] || []).filter(stage => !stage.is_log);
  }

  findBoardIdForSpawnStage(stageId) {
    if (!stageId) return this.boardId;
    for (const [boardId, stages] of Object.entries(this.stagesByBoard)) {
      if (stages.some(stage => stage.id === stageId)) return parseInt(boardId, 10);
    }
    return this.boardId;
  }

  hasCustomFields(tt) {
    return !!(tt.custom_fields && tt.custom_fields.length > 0);
  }

  hasFieldOptions(field) {
    return !!(field.options && field.options.length > 0);
  }

  openCreateTypeForm() {
    if (!this.canEdit) return;
    this.showCreateForm = true;
    this.render();
    const input = this.root.querySelector('#new-task-type-name');
    input?.focus();
  }

  closeCreateTypeForm() {
    this.showCreateForm = false;
    this.newType = {name: '', is_epic: false};
    this.render();
  }

  async createType() {
    if (!this.canEdit) return;
    if (!this.newType.name.trim()) return;
    const res = await fetch('/api/task-types', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: this.newType.name.trim(),
        is_epic: this.newType.is_epic,
        board_id: this.boardId,
        show_description_on_card: false,
        show_checklist_on_card: false,
      }),
    });
    if (!res.ok) return;
    const tt = await res.json();
    this.taskTypes.push(this.normalizeTaskType(tt));
    this.newType = {name: '', is_epic: false};
    this.showCreateForm = false;
    this.render();
  }

  startEditType(typeId) {
    if (!this.canEdit) return;
    const tt = this.taskTypeById(typeId);
    if (!tt) return;
    tt.editing = true;
    tt.editName = tt.name;
    this.render();
    const input = this.root.querySelector(`[data-field="type-name"][data-type-id="${typeId}"]`);
    input?.focus();
    input?.select();
  }

  async saveTypeName(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    if (!tt.editName.trim() || tt.editName === tt.name) {
      tt.editing = false;
      tt.editName = tt.name;
      this.render();
      return;
    }
    const res = await fetch(`/api/task-types/${tt.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: tt.editName.trim()}),
    });
    if (!res.ok) {
      tt.editing = false;
      tt.editName = tt.name;
      this.render();
      return;
    }
    tt.name = tt.editName.trim();
    tt.editing = false;
    this.render();
  }

  async toggleEpic(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    const res = await fetch(`/api/task-types/${tt.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({is_epic: !tt.is_epic}),
    });
    if (!res.ok) return;
    const updated = await res.json();
    tt.is_epic = updated.is_epic;
    this.render();
  }

  async toggleTypeDescriptionOnCard(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    const res = await fetch(`/api/task-types/${tt.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({show_description_on_card: !tt.show_description_on_card}),
    });
    if (!res.ok) return;
    const updated = await res.json();
    tt.show_description_on_card = updated.show_description_on_card;
    this.render();
  }

  async toggleTypeChecklistOnCard(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    const res = await fetch(`/api/task-types/${tt.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({show_checklist_on_card: !tt.show_checklist_on_card}),
    });
    if (!res.ok) return;
    const updated = await res.json();
    tt.show_checklist_on_card = updated.show_checklist_on_card;
    this.render();
  }

  async setSpawnStage(typeId, value) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    const spawn_stage_id = value ? parseInt(value, 10) : null;
    const res = await fetch(`/api/task-types/${tt.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({spawn_stage_id}),
    });
    if (!res.ok) return;
    const updated = await res.json();
    tt.spawn_stage_id = updated.spawn_stage_id;
    tt.spawn_board_id = String(this.findBoardIdForSpawnStage(updated.spawn_stage_id) || tt.spawn_board_id || this.boardId);
    tt.available_spawn_stages = this.spawnStagesForBoard(tt.spawn_board_id);
    this.render();
  }

  handleSpawnBoardChange(typeId, boardId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    tt.spawn_board_id = String(boardId);
    tt.available_spawn_stages = this.spawnStagesForBoard(tt.spawn_board_id);
    const availableStages = tt.available_spawn_stages;
    if (!tt.spawn_stage_id) {
      this.render();
      return;
    }
    if (!availableStages.some(stage => String(stage.id) === String(tt.spawn_stage_id))) {
      tt.spawn_stage_id = '';
      this.setSpawnStage(typeId, '');
      return;
    }
    this.render();
  }

  async deleteType(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    if (!confirm(`Delete objective type "${tt.name}"? Objectives using this type will lose their type.`)) return;
    const res = await fetch(`/api/task-types/${tt.id}`, {method: 'DELETE'});
    if (!res.ok) return;
    this.taskTypes = this.taskTypes.filter(entry => entry.id !== tt.id);
    this.render();
  }

  toggleAddFieldForm(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    tt.showAddField = !tt.showAddField;
    if (tt.showAddField) {
      tt.newField = this.blankNewField();
    }
    this.render();
    if (tt.showAddField) {
      const input = this.root.querySelector(`[data-field="new-field-name"][data-type-id="${typeId}"]`);
      input?.focus();
    }
  }

  async addField(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    if (!tt.newField.name.trim()) return;
    const res = await fetch(`/api/task-types/${tt.id}/fields`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: tt.newField.name.trim(),
        field_type: tt.newField.field_type,
        show_on_card: tt.newField.show_on_card,
        options: tt.newField.field_type === 'dropdown' ? tt.newField.options : null,
      }),
    });
    if (!res.ok) return;
    const field = await res.json();
    tt.custom_fields.push(this.normalizeField(field));
    tt.newField = this.blankNewField();
    tt.showAddField = false;
    this.render();
  }

  addNewFieldOption(typeId) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    if (!tt.newField.newOption.trim()) return;
    tt.newField.options.push(this.normalizeOption({label: tt.newField.newOption.trim(), color: null}));
    tt.newField.newOption = '';
    this.render();
  }

  removeNewFieldOption(typeId, optionIndex) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    tt.newField.options.splice(optionIndex, 1);
    this.render();
  }

  setNewFieldOptionColor(typeId, optionIndex, color) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    if (!tt.newField.options[optionIndex]) return;
    tt.newField.options[optionIndex].color = color;
    this.render();
  }

  async addFieldOption(typeId, fieldId) {
    const tt = this.taskTypeById(typeId);
    const field = this.fieldById(tt, fieldId);
    if (!tt || !field || !this.canEdit) return;
    if (!field.newOption.trim()) return;
    const newOptions = [...(field.options || []), this.normalizeOption({label: field.newOption.trim(), color: null})];
    const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: field.name,
        field_type: field.field_type,
        show_on_card: field.show_on_card,
        options: newOptions,
      }),
    });
    if (!res.ok) return;
    const updated = await res.json();
    field.options = (updated.options || []).map(option => this.normalizeOption(option));
    field.newOption = '';
    this.render();
  }

  async removeFieldOption(typeId, fieldId, optionIndex) {
    const tt = this.taskTypeById(typeId);
    const field = this.fieldById(tt, fieldId);
    if (!tt || !field || !this.canEdit) return;
    const newOptions = field.options.filter((_, index) => index !== optionIndex);
    const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: field.name,
        field_type: field.field_type,
        show_on_card: field.show_on_card,
        options: newOptions,
      }),
    });
    if (!res.ok) return;
    const updated = await res.json();
    field.options = (updated.options || []).map(option => this.normalizeOption(option));
    this.render();
  }

  async setFieldOptionColor(typeId, fieldId, optionIndex, color) {
    const tt = this.taskTypeById(typeId);
    const field = this.fieldById(tt, fieldId);
    if (!tt || !field || !this.canEdit) return;
    const newOptions = field.options.map((option, index) => (
      index === optionIndex ? {...option, color} : option
    ));
    const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: field.name,
        field_type: field.field_type,
        show_on_card: field.show_on_card,
        options: newOptions,
      }),
    });
    if (!res.ok) return;
    const updated = await res.json();
    field.options = (updated.options || []).map(option => this.normalizeOption(option));
    this.render();
  }

  async toggleShowOnCard(typeId, fieldId) {
    const tt = this.taskTypeById(typeId);
    const field = this.fieldById(tt, fieldId);
    if (!tt || !field || !this.canEdit) return;
    const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: field.name,
        field_type: field.field_type,
        show_on_card: !field.show_on_card,
      }),
    });
    if (!res.ok) return;
    const updated = await res.json();
    field.show_on_card = updated.show_on_card;
    this.render();
  }

  async deleteField(typeId, fieldId) {
    const tt = this.taskTypeById(typeId);
    const field = this.fieldById(tt, fieldId);
    if (!tt || !field || !this.canEdit) return;
    if (!confirm(`Delete field "${field.name}"?`)) return;
    const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {method: 'DELETE'});
    if (!res.ok) return;
    tt.custom_fields = tt.custom_fields.filter(entry => entry.id !== field.id);
    this.render();
  }

  async setFieldColor(typeId, fieldId, color) {
    const tt = this.taskTypeById(typeId);
    const field = this.fieldById(tt, fieldId);
    if (!tt || !field || !this.canEdit) return;
    const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: field.name,
        field_type: field.field_type,
        show_on_card: field.show_on_card,
        color,
      }),
    });
    if (!res.ok) return;
    field.color = color;
    this.render();
  }

  async setTypeColor(typeId, color) {
    const tt = this.taskTypeById(typeId);
    if (!tt || !this.canEdit) return;
    const res = await fetch(`/api/task-types/${tt.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({color}),
    });
    if (!res.ok) return;
    tt.color = color;
    this.render();
  }

  closePopover() {
    this.activePopover = null;
    this.render();
  }

  togglePopover(popover) {
    const same = this.activePopover
      && this.activePopover.kind === popover.kind
      && this.activePopover.typeId === popover.typeId
      && this.activePopover.fieldId === popover.fieldId
      && this.activePopover.optionIndex === popover.optionIndex;
    this.activePopover = same ? null : popover;
    this.render();
  }

  isPopoverOpen(popover) {
    return !!this.activePopover
      && this.activePopover.kind === popover.kind
      && this.activePopover.typeId === popover.typeId
      && this.activePopover.fieldId === popover.fieldId
      && this.activePopover.optionIndex === popover.optionIndex;
  }

  render() {
    this.readonlyBanner.classList.toggle('hidden', this.canEdit);
    this.newButton.classList.toggle('hidden', !this.canEdit);
    this.createContainer.innerHTML = this.showCreateForm ? this.renderCreateForm() : '';
    this.listContainer.innerHTML = this.taskTypes.map(tt => this.renderTaskType(tt)).join('');
    this.emptyState.classList.toggle('hidden', this.taskTypes.length > 0);
  }

  renderCreateForm() {
    return `
      <div class="bg-white rounded-xl shadow p-4 mb-4">
        <h2 class="font-semibold text-gray-700 mb-3">New Objective Type</h2>
        <div class="flex gap-3 items-end">
          <div class="flex-1">
            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Name</label>
            <input
              id="new-task-type-name"
              data-field="new-type-name"
              value="${escapeHtml(this.newType.name)}"
              placeholder="e.g. Bug, Feature, Quest..."
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
          </div>
          <div class="flex items-center gap-2 pb-2">
            <input type="checkbox" id="new-is-epic" data-field="new-type-epic" class="h-4 w-4 rounded accent-purple-500"${renderChecked(this.newType.is_epic)}>
            <label for="new-is-epic" class="text-sm text-gray-600">Quest <span class="text-purple-600">⚡</span></label>
          </div>
          <div class="flex gap-2 pb-0.5">
            <button type="button" data-action="create-type" class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Create</button>
            <button type="button" data-action="cancel-create-type" class="text-gray-500 hover:text-gray-700 px-3 py-2 text-sm">Cancel</button>
          </div>
        </div>
        ${this.newType.is_epic ? '<p class="mt-2 text-xs text-purple-600 bg-purple-50 px-3 py-1.5 rounded-lg">⚡ Quest objectives automatically spawn a new objective for each checklist item added.</p>' : ''}
      </div>
    `;
  }

  renderTaskType(tt) {
    return `
      <div class="bg-white rounded-xl shadow overflow-visible">
        ${this.renderTaskTypeHeader(tt)}
        ${tt.is_epic ? this.renderSpawnConfig(tt) : ''}
        ${this.renderCustomFields(tt)}
      </div>
    `;
  }

  renderTaskTypeHeader(tt) {
    const typePopover = this.renderColorPopover({
      kind: 'type-color',
      typeId: tt.id,
      fieldId: null,
      optionIndex: null,
      currentColor: tt.color,
      onSetAction: 'set-type-color',
      onClearAction: 'clear-type-color',
    });

    return `
      <div class="flex items-center gap-3 px-5 py-4 border-b">
        <div class="relative flex-shrink-0" data-role="color-popover-anchor">
          <button
            type="button"
            data-action="toggle-type-color"
            data-type-id="${tt.id}"
            class="w-6 h-6 rounded-full border-2 border-gray-200 hover:scale-110 transition-transform shadow-sm ${this.colorSwatchClass(tt.color)}"
            title="Pick color"
            ${renderDisabled(!this.canEdit)}
          ></button>
          ${typePopover}
        </div>
        <div class="flex-1 flex items-center gap-2">
          ${tt.editing
            ? `<input
                type="text"
                data-field="type-name"
                data-type-id="${tt.id}"
                value="${escapeHtml(tt.editName)}"
                class="font-semibold text-gray-800 border-b-2 border-blue-400 focus:outline-none text-lg bg-transparent"
              >`
            : `<span
                data-action="${this.canEdit ? 'start-edit-type' : ''}"
                data-type-id="${tt.id}"
                class="font-semibold text-gray-800 text-lg ${this.canEdit ? 'cursor-pointer hover:text-blue-600' : ''}"
                title="${this.canEdit ? 'Double-click to rename' : ''}"
              >${escapeHtml(tt.name)}</span>`
          }
          ${tt.is_epic ? '<span class="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">⚡ Quest</span>' : ''}
        </div>
        <div class="flex items-center gap-2">
          <label class="flex items-center gap-1.5 text-sm text-gray-500 cursor-pointer">
            <input type="checkbox" data-field="type-show-description" data-type-id="${tt.id}" class="h-4 w-4 rounded accent-blue-500"${renderChecked(tt.show_description_on_card)}${renderDisabled(!this.canEdit)}>
            Description on card
          </label>
          <label class="flex items-center gap-1.5 text-sm text-gray-500 cursor-pointer">
            <input type="checkbox" data-field="type-show-checklist" data-type-id="${tt.id}" class="h-4 w-4 rounded accent-blue-500"${renderChecked(tt.show_checklist_on_card)}${renderDisabled(!this.canEdit)}>
            Checklist on card
          </label>
          <label class="flex items-center gap-1.5 text-sm text-gray-500 cursor-pointer">
            <input type="checkbox" data-field="type-is-epic" data-type-id="${tt.id}" class="h-4 w-4 rounded accent-purple-500"${renderChecked(tt.is_epic)}${renderDisabled(!this.canEdit)}>
            Quest
          </label>
          ${this.canEdit ? `<button type="button" data-action="delete-type" data-type-id="${tt.id}" class="text-gray-300 hover:text-red-500 transition-colors text-lg leading-none ml-2" title="Delete type">×</button>` : ''}
        </div>
      </div>
    `;
  }

  renderColorPopover(config) {
    if (!this.isPopoverOpen(config)) return '';
    const palette = PRESET_COLORS.map(color => `
      <button
        type="button"
        data-action="${config.onSetAction}"
        data-type-id="${config.typeId}"
        ${config.fieldId ? `data-field-id="${config.fieldId}"` : ''}
        ${config.optionIndex !== null ? `data-option-index="${config.optionIndex}"` : ''}
        data-color="${color}"
        class="w-6 h-6 rounded-full hover:scale-110 transition-transform border border-black/10 ${this.paletteColorClass(config.currentColor, color)}"
      ></button>
    `).join('');
    return `
      <div class="absolute top-8 left-0 bg-white shadow-xl rounded-xl p-3 z-20 w-48" data-role="popover">
        <div class="flex flex-wrap gap-2">
          ${palette}
          <button
            type="button"
            data-action="${config.onClearAction}"
            data-type-id="${config.typeId}"
            ${config.fieldId ? `data-field-id="${config.fieldId}"` : ''}
            ${config.optionIndex !== null ? `data-option-index="${config.optionIndex}"` : ''}
            class="w-6 h-6 rounded-full bg-gray-100 border border-dashed border-gray-300 flex items-center justify-center text-gray-400 text-xs hover:bg-gray-200"
            title="No color"
          >✕</button>
        </div>
      </div>
    `;
  }

  renderSpawnConfig(tt) {
    const boardOptions = this.boards.map(board => (
      `<option value="${escapeHtml(this.asString(board.id))}"${renderSelected(tt.spawn_board_id, this.asString(board.id))}>${escapeHtml(board.name)}</option>`
    )).join('');
    const stageOptions = tt.available_spawn_stages.map(stage => (
      `<option value="${escapeHtml(this.asString(stage.id))}"${renderSelected(tt.spawn_stage_id, this.asString(stage.id))}>${escapeHtml(stage.name)}</option>`
    )).join('');
    return `
      <div class="px-5 py-2 bg-purple-50 border-b flex items-center gap-3 flex-wrap">
        <span class="text-xs font-semibold text-purple-600 whitespace-nowrap">⚡ Spawn objectives into</span>
        <select data-field="spawn-board" data-type-id="${tt.id}" class="border rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-purple-400 bg-white"${renderDisabled(!this.canEdit)}>
          ${boardOptions}
        </select>
        <select data-field="spawn-stage" data-type-id="${tt.id}" class="border rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-purple-400 bg-white flex-1 max-w-xs"${renderDisabled(!this.canEdit)}>
          <option value="">Same stage as the quest</option>
          ${stageOptions}
        </select>
      </div>
    `;
  }

  renderCustomFields(tt) {
    return `
      <div class="px-5 py-3">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Custom Fields</span>
          ${this.canEdit ? `<button type="button" data-action="toggle-add-field" data-type-id="${tt.id}" class="text-xs text-blue-500 hover:text-blue-700 font-medium">+ Add field</button>` : ''}
        </div>
        ${this.hasCustomFields(tt) ? `<div class="space-y-1 mb-2">${tt.custom_fields.map(field => this.renderField(tt, field)).join('')}</div>` : '<p class="text-sm text-gray-400 italic py-1">No custom fields yet.</p>'}
        ${tt.showAddField && this.canEdit ? this.renderAddFieldForm(tt) : ''}
      </div>
    `;
  }

  renderField(tt, field) {
    const fieldPopover = this.renderColorPopover({
      kind: 'field-color',
      typeId: tt.id,
      fieldId: field.id,
      optionIndex: null,
      currentColor: field.color,
      onSetAction: 'set-field-color',
      onClearAction: 'clear-field-color',
    });

    const dropdownOptions = field.field_type === 'dropdown' ? this.renderFieldOptions(tt, field) : '';

    return `
      <div class="bg-gray-50 rounded-lg group">
        <div class="flex items-center justify-between py-1.5 px-3">
          <div class="flex items-center gap-2.5">
            <div class="relative flex-shrink-0" data-role="color-popover-anchor">
              <button
                type="button"
                data-action="toggle-field-color"
                data-type-id="${tt.id}"
                data-field-id="${field.id}"
                class="w-4 h-4 rounded border border-black/15 hover:scale-110 transition-transform ${this.colorSwatchClass(field.color)}"
                title="Pick color"
                ${renderDisabled(!this.canEdit)}
              ></button>
              ${fieldPopover}
            </div>
            <span class="text-sm font-medium text-gray-700">${escapeHtml(field.name)}</span>
            <span class="text-xs bg-white border text-gray-500 px-2 py-0.5 rounded">${escapeHtml(field.field_type)}</span>
          </div>
          <div class="flex items-center gap-3">
            <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none" title="${escapeHtml(this.fieldShowOnCardTitle(field))}">
              <input type="checkbox" data-field="field-show-on-card" data-type-id="${tt.id}" data-field-id="${field.id}" class="h-3.5 w-3.5 rounded accent-blue-500"${renderChecked(field.show_on_card)}${renderDisabled(!this.canEdit)}>
              Show on card
            </label>
            ${this.canEdit ? `<button type="button" data-action="delete-field" data-type-id="${tt.id}" data-field-id="${field.id}" class="text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100">×</button>` : ''}
          </div>
        </div>
        ${dropdownOptions}
      </div>
    `;
  }

  renderFieldOptions(tt, field) {
    const optionChips = (field.options || []).map((opt, index) => {
      const optionPopover = this.renderColorPopover({
        kind: 'field-option-color',
        typeId: tt.id,
        fieldId: field.id,
        optionIndex: index,
        currentColor: opt.color,
        onSetAction: 'set-field-option-color',
        onClearAction: 'clear-field-option-color',
      });
      return `
        <span class="relative flex items-center gap-1 text-xs bg-white border rounded-md px-1.5 py-0.5 text-gray-700" data-role="color-popover-anchor">
          <button
            type="button"
            data-action="toggle-field-option-color"
            data-type-id="${tt.id}"
            data-field-id="${field.id}"
            data-option-index="${index}"
            class="w-3.5 h-3.5 rounded border border-black/15 hover:scale-110 transition-transform ${this.colorSwatchClass(opt.color)}"
            title="Pick option color"
            ${renderDisabled(!this.canEdit)}
          ></button>
          <span>${escapeHtml(opt.label)}</span>
          ${this.canEdit ? `<button type="button" data-action="remove-field-option" data-type-id="${tt.id}" data-field-id="${field.id}" data-option-index="${index}" class="text-gray-300 hover:text-red-400 ml-0.5 leading-none">×</button>` : ''}
          ${optionPopover}
        </span>
      `;
    }).join('');

    return `
      <div class="px-3 pb-2.5 border-t border-gray-200">
        <div class="flex flex-wrap gap-1 mt-2 mb-1.5">
          ${optionChips || '<span class="text-xs text-gray-400 italic py-0.5">No options yet</span>'}
        </div>
        ${this.canEdit ? `
          <div class="flex gap-1.5">
            <input
              type="text"
              data-field="field-new-option"
              data-type-id="${tt.id}"
              data-field-id="${field.id}"
              value="${escapeHtml(field.newOption || '')}"
              placeholder="New option..."
              class="flex-1 border rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
            <button type="button" data-action="add-field-option" data-type-id="${tt.id}" data-field-id="${field.id}" class="text-xs bg-white border hover:bg-gray-100 px-2 py-1 rounded-lg transition-colors">Add</button>
          </div>
        ` : ''}
      </div>
    `;
  }

  renderAddFieldForm(tt) {
    const optionChips = tt.newField.options.map((opt, index) => {
      const optionPopover = this.renderColorPopover({
        kind: 'new-field-option-color',
        typeId: tt.id,
        fieldId: null,
        optionIndex: index,
        currentColor: opt.color,
        onSetAction: 'set-new-field-option-color',
        onClearAction: 'clear-new-field-option-color',
      });
      return `
        <span class="relative flex items-center gap-1 text-xs bg-white border rounded-md px-1.5 py-0.5 text-gray-700" data-role="color-popover-anchor">
          <button
            type="button"
            data-action="toggle-new-field-option-color"
            data-type-id="${tt.id}"
            data-option-index="${index}"
            class="w-3.5 h-3.5 rounded border border-black/15 hover:scale-110 transition-transform ${this.colorSwatchClass(opt.color)}"
            title="Pick option color"
            ${renderDisabled(!this.canEdit)}
          ></button>
          <span>${escapeHtml(opt.label)}</span>
          <button type="button" data-action="remove-new-field-option" data-type-id="${tt.id}" data-option-index="${index}" class="text-gray-300 hover:text-red-400 ml-0.5 leading-none">×</button>
          ${optionPopover}
        </span>
      `;
    }).join('');

    return `
      <div class="mt-2 bg-blue-50 rounded-lg p-3">
        <div class="flex gap-2 items-end flex-wrap">
          <div class="flex-1 min-w-32">
            <label class="block text-xs text-gray-500 mb-1">Field name</label>
            <input
              type="text"
              data-field="new-field-name"
              data-type-id="${tt.id}"
              value="${escapeHtml(tt.newField.name)}"
              placeholder="e.g. Assignee, Status..."
              class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1">Type</label>
            <select data-field="new-field-type" data-type-id="${tt.id}" class="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
              <option value="text"${renderSelected(tt.newField.field_type, 'text')}>Text</option>
              <option value="number"${renderSelected(tt.newField.field_type, 'number')}>Number</option>
              <option value="date"${renderSelected(tt.newField.field_type, 'date')}>Date</option>
              <option value="dropdown"${renderSelected(tt.newField.field_type, 'dropdown')}>Dropdown</option>
            </select>
          </div>
          <div class="pb-2">
            <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none whitespace-nowrap">
              <input type="checkbox" data-field="new-field-show-on-card" data-type-id="${tt.id}" class="h-3.5 w-3.5 rounded accent-blue-500"${renderChecked(tt.newField.show_on_card)}>
              Show on card
            </label>
          </div>
          <button type="button" data-action="add-field" data-type-id="${tt.id}" class="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors">Add</button>
          <button type="button" data-action="cancel-add-field" data-type-id="${tt.id}" class="text-gray-500 hover:text-gray-700 px-2 py-1.5 text-sm">Cancel</button>
        </div>
        ${tt.newField.field_type === 'dropdown' ? `
          <div class="mt-2 pt-2 border-t border-blue-100">
            <div class="flex flex-wrap gap-1 mb-1.5">
              ${optionChips || '<span class="text-xs text-gray-400 italic py-0.5">Add at least one option</span>'}
            </div>
            <div class="flex gap-1.5">
              <input
                type="text"
                data-field="new-field-option-input"
                data-type-id="${tt.id}"
                value="${escapeHtml(tt.newField.newOption)}"
                placeholder="Option label..."
                class="flex-1 border rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
              <button type="button" data-action="add-new-field-option" data-type-id="${tt.id}" class="text-xs bg-white border hover:bg-gray-100 px-2 py-1 rounded-lg transition-colors">Add option</button>
            </div>
          </div>
        ` : ''}
      </div>
    `;
  }

  handleClick(event) {
    const actionTarget = event.target.closest('[data-action]');
    if (!actionTarget) return;
    const action = actionTarget.dataset.action;
    const typeId = Number.parseInt(actionTarget.dataset.typeId || '', 10);
    const fieldId = Number.parseInt(actionTarget.dataset.fieldId || '', 10);
    const optionIndex = Number.parseInt(actionTarget.dataset.optionIndex || '', 10);

    if (action === 'create-type') {
      this.createType();
      return;
    }
    if (action === 'cancel-create-type') {
      this.closeCreateTypeForm();
      return;
    }
    if (action === 'delete-type' && !Number.isNaN(typeId)) {
      this.deleteType(typeId);
      return;
    }
    if (action === 'toggle-add-field' && !Number.isNaN(typeId)) {
      this.toggleAddFieldForm(typeId);
      return;
    }
    if (action === 'cancel-add-field' && !Number.isNaN(typeId)) {
      this.toggleAddFieldForm(typeId);
      return;
    }
    if (action === 'add-field' && !Number.isNaN(typeId)) {
      this.addField(typeId);
      return;
    }
    if (action === 'add-new-field-option' && !Number.isNaN(typeId)) {
      this.addNewFieldOption(typeId);
      return;
    }
    if (action === 'remove-new-field-option' && !Number.isNaN(typeId) && !Number.isNaN(optionIndex)) {
      this.removeNewFieldOption(typeId, optionIndex);
      return;
    }
    if (action === 'add-field-option' && !Number.isNaN(typeId) && !Number.isNaN(fieldId)) {
      this.addFieldOption(typeId, fieldId);
      return;
    }
    if (action === 'remove-field-option' && !Number.isNaN(typeId) && !Number.isNaN(fieldId) && !Number.isNaN(optionIndex)) {
      this.removeFieldOption(typeId, fieldId, optionIndex);
      return;
    }
    if (action === 'delete-field' && !Number.isNaN(typeId) && !Number.isNaN(fieldId)) {
      this.deleteField(typeId, fieldId);
      return;
    }

    if (action === 'toggle-type-color' && !Number.isNaN(typeId)) {
      this.togglePopover({kind: 'type-color', typeId, fieldId: null, optionIndex: null});
      return;
    }
    if (action === 'toggle-field-color' && !Number.isNaN(typeId) && !Number.isNaN(fieldId)) {
      this.togglePopover({kind: 'field-color', typeId, fieldId, optionIndex: null});
      return;
    }
    if (action === 'toggle-field-option-color' && !Number.isNaN(typeId) && !Number.isNaN(fieldId) && !Number.isNaN(optionIndex)) {
      this.togglePopover({kind: 'field-option-color', typeId, fieldId, optionIndex});
      return;
    }
    if (action === 'toggle-new-field-option-color' && !Number.isNaN(typeId) && !Number.isNaN(optionIndex)) {
      this.togglePopover({kind: 'new-field-option-color', typeId, fieldId: null, optionIndex});
      return;
    }

    if (action === 'set-type-color' && !Number.isNaN(typeId)) {
      this.setTypeColor(typeId, actionTarget.dataset.color || null);
      return;
    }
    if (action === 'clear-type-color' && !Number.isNaN(typeId)) {
      this.setTypeColor(typeId, null);
      return;
    }
    if (action === 'set-field-color' && !Number.isNaN(typeId) && !Number.isNaN(fieldId)) {
      this.setFieldColor(typeId, fieldId, actionTarget.dataset.color || null);
      return;
    }
    if (action === 'clear-field-color' && !Number.isNaN(typeId) && !Number.isNaN(fieldId)) {
      this.setFieldColor(typeId, fieldId, null);
      return;
    }
    if (action === 'set-field-option-color' && !Number.isNaN(typeId) && !Number.isNaN(fieldId) && !Number.isNaN(optionIndex)) {
      this.setFieldOptionColor(typeId, fieldId, optionIndex, actionTarget.dataset.color || null);
      return;
    }
    if (action === 'clear-field-option-color' && !Number.isNaN(typeId) && !Number.isNaN(fieldId) && !Number.isNaN(optionIndex)) {
      this.setFieldOptionColor(typeId, fieldId, optionIndex, null);
      return;
    }
    if (action === 'set-new-field-option-color' && !Number.isNaN(typeId) && !Number.isNaN(optionIndex)) {
      this.setNewFieldOptionColor(typeId, optionIndex, actionTarget.dataset.color || null);
      return;
    }
    if (action === 'clear-new-field-option-color' && !Number.isNaN(typeId) && !Number.isNaN(optionIndex)) {
      this.setNewFieldOptionColor(typeId, optionIndex, null);
    }
  }

  handleDoubleClick(event) {
    const actionTarget = event.target.closest('[data-action="start-edit-type"]');
    if (!actionTarget) return;
    const typeId = Number.parseInt(actionTarget.dataset.typeId || '', 10);
    if (Number.isNaN(typeId)) return;
    this.startEditType(typeId);
  }

  handleInput(event) {
    const field = event.target.dataset.field;
    const typeId = Number.parseInt(event.target.dataset.typeId || '', 10);
    const fieldId = Number.parseInt(event.target.dataset.fieldId || '', 10);
    if (field === 'new-type-name') {
      this.newType.name = event.target.value;
      return;
    }
    const tt = this.taskTypeById(typeId);
    if (!tt) return;

    if (field === 'type-name') {
      tt.editName = event.target.value;
      return;
    }
    if (field === 'new-field-name') {
      tt.newField.name = event.target.value;
      return;
    }
    if (field === 'new-field-option-input') {
      tt.newField.newOption = event.target.value;
      return;
    }
    if (field === 'field-new-option') {
      const fieldRow = this.fieldById(tt, fieldId);
      if (!fieldRow) return;
      fieldRow.newOption = event.target.value;
    }
  }

  handleChange(event) {
    const field = event.target.dataset.field;
    const typeId = Number.parseInt(event.target.dataset.typeId || '', 10);
    const fieldId = Number.parseInt(event.target.dataset.fieldId || '', 10);

    if (field === 'new-type-epic') {
      this.newType.is_epic = event.target.checked;
      this.render();
      return;
    }

    const tt = this.taskTypeById(typeId);
    if (!tt) return;

    if (field === 'type-show-description') {
      this.toggleTypeDescriptionOnCard(typeId);
      return;
    }
    if (field === 'type-show-checklist') {
      this.toggleTypeChecklistOnCard(typeId);
      return;
    }
    if (field === 'type-is-epic') {
      this.toggleEpic(typeId);
      return;
    }
    if (field === 'spawn-board') {
      this.handleSpawnBoardChange(typeId, event.target.value);
      return;
    }
    if (field === 'spawn-stage') {
      this.setSpawnStage(typeId, event.target.value);
      return;
    }
    if (field === 'field-show-on-card') {
      this.toggleShowOnCard(typeId, fieldId);
      return;
    }
    if (field === 'new-field-type') {
      tt.newField.field_type = event.target.value;
      if (tt.newField.field_type !== 'dropdown') {
        tt.newField.options = [];
        tt.newField.newOption = '';
      }
      this.render();
      return;
    }
    if (field === 'new-field-show-on-card') {
      tt.newField.show_on_card = event.target.checked;
      return;
    }
  }

  handleKeydown(event) {
    const field = event.target.dataset.field;
    const typeId = Number.parseInt(event.target.dataset.typeId || '', 10);
    const fieldId = Number.parseInt(event.target.dataset.fieldId || '', 10);
    const tt = this.taskTypeById(typeId);

    if (field === 'new-type-name') {
      if (event.key === 'Enter') {
        this.createType();
      } else if (event.key === 'Escape') {
        this.closeCreateTypeForm();
      }
      return;
    }

    if (field === 'type-name' && tt) {
      if (event.key === 'Enter') {
        event.target.blur();
      } else if (event.key === 'Escape') {
        tt.editing = false;
        tt.editName = tt.name;
        this.render();
      }
      return;
    }

    if (field === 'new-field-name' && tt) {
      if (event.key === 'Enter' && tt.newField.field_type !== 'dropdown') {
        this.addField(typeId);
      } else if (event.key === 'Escape') {
        tt.showAddField = false;
        this.render();
      }
      return;
    }

    if (field === 'new-field-option-input' && tt && event.key === 'Enter') {
      event.preventDefault();
      this.addNewFieldOption(typeId);
      return;
    }

    if (field === 'field-new-option' && tt && !Number.isNaN(fieldId) && event.key === 'Enter') {
      event.preventDefault();
      this.addFieldOption(typeId, fieldId);
    }
  }

  handleBlur(event) {
    const field = event.target.dataset.field;
    const typeId = Number.parseInt(event.target.dataset.typeId || '', 10);
    if (field === 'type-name' && !Number.isNaN(typeId)) {
      this.saveTypeName(typeId);
    }
  }

  handleDocumentClick(event) {
    if (!this.activePopover) return;
    if (event.target.closest('[data-role="color-popover-anchor"]')) {
      return;
    }
    if (!this.root.contains(event.target)) {
      this.closePopover();
      return;
    }
    if (!event.target.closest('[data-role="popover"]') && !event.target.closest('[data-action^="toggle-"]')) {
      this.closePopover();
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('task-types-page');
  if (!root) return;
  const controller = new TaskTypesPageController(root);
  controller.init();
  const newButton = root.querySelector('#task-types-new-button');
  if (newButton) {
    newButton.addEventListener('click', () => controller.openCreateTypeForm());
  }
});

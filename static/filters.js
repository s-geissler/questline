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

function roleBadgeClass(board) {
  if (board.role === 'admin') return 'bg-fuchsia-100 text-fuchsia-700';
  if (board.role === 'owner') return 'bg-blue-100 text-blue-700';
  if (board.role === 'editor') return 'bg-amber-100 text-amber-700';
  return 'bg-emerald-100 text-emerald-700';
}

function roleBadgeLabel(board) {
  if (!board?.role) return '';
  return board.role.charAt(0).toUpperCase() + board.role.slice(1);
}

class FiltersPageController {
  constructor(root) {
    this.root = root;
    this.boardId = 0;
    this.boardRole = null;
    this.boards = [];
    this.currentUser = null;
    this.assigneeOptions = [];
    this.filters = [];
    this.taskTypes = [];
    this.editingFilter = null;
    this.nextRuleUid = 1;
    this.saveError = '';
    this.saving = false;
    this.editorContainer = root.querySelector('#filters-editor-container');
    this.listContainer = root.querySelector('#filters-list-container');
    this.emptyState = root.querySelector('#filters-empty-state');
    this.readonlyBanner = root.querySelector('#filters-readonly-banner');
    this.newButton = root.querySelector('#filters-new-button');
    this.bindEvents();
  }

  bindEvents() {
    this.root.addEventListener('click', event => this.handleClick(event));
    this.root.addEventListener('change', event => this.handleChange(event));
    this.root.addEventListener('input', event => this.handleInput(event));
  }

  get canEdit() {
    return this.boardRole === 'owner' || this.boardRole === 'editor' || this.boardRole === 'admin';
  }

  asString(value) {
    return value === null || value === undefined ? '' : String(value);
  }

  sameString(left, right) {
    return this.asString(left) === this.asString(right);
  }

  parsePageData() {
    this.boardId = parseInt(this.root.dataset.boardId || '0', 10);
    this.boardRole = JSON.parse(this.root.dataset.boardRole || 'null');
    this.boards = JSON.parse(this.root.dataset.boards || '[]');
    this.currentUser = JSON.parse(this.root.dataset.currentUser || 'null');
    this.assigneeOptions = JSON.parse(this.root.dataset.assigneeOptions || '[]');
  }

  async init() {
    this.parsePageData();
    await this.load();
    this.render();
  }

  async load() {
    const [filtersRes, taskTypesRes] = await Promise.all([
      fetch('/api/filters?board_id=' + this.boardId),
      fetch('/api/task-types?board_id=' + this.boardId),
    ]);
    this.filters = await filtersRes.json();
    this.taskTypes = await taskTypesRes.json();
  }

  get availableFields() {
    return [
      {key: 'title', label: 'Title', type: 'text'},
      {key: 'description', label: 'Description', type: 'text'},
      {key: 'task_type_id', label: 'Objective Type', type: 'task_type'},
      {key: 'assignee_user_id', label: 'Assigned To', type: 'assignee'},
      {key: 'done', label: 'Status', type: 'status'},
      {key: 'due_date', label: 'Due Date', type: 'date'},
      {key: 'color', label: 'Color', type: 'color'},
      {key: 'has_parent_task', label: 'Has Quest', type: 'boolean'},
      {key: '__custom__', label: 'Custom Field', type: 'custom'},
    ];
  }

  get customFieldTaskTypes() {
    return this.taskTypes.filter(taskType => (taskType.custom_fields || []).length > 0);
  }

  get availableSortFields() {
    return [
      {key: 'due_date', label: 'Due Date'},
      {key: 'title', label: 'Title'},
      {key: 'created_at', label: 'Created'},
      {key: 'updated_at', label: 'Last Updated'},
      {key: 'done', label: 'Status'},
      {key: 'task_type_id', label: 'Objective Type'},
      {key: 'assignee_user_id', label: 'Assigned To'},
      {key: 'description', label: 'Description'},
      {key: 'color', label: 'Color'},
      {key: 'has_parent_task', label: 'Has Quest'},
      ...this.taskTypes.flatMap(type => (type.custom_fields || []).map(field => ({
        key: `custom:${field.id}`, label: `${type.name}: ${field.name}`,
      }))),
    ];
  }

  editorTitle() {
    return this.editingFilter?.id ? 'Edit Filter' : 'New Filter';
  }

  customFieldsForRule(rule) {
    const taskType = this.customFieldTaskTypes.find(taskType => String(taskType.id) === String(rule.custom_task_type_id || ''));
    return taskType?.custom_fields || [];
  }

  selectedCustomField(rule) {
    return this.customFieldsForRule(rule).find(field => String(field.id) === String(rule.custom_field_id || '')) || null;
  }

  fieldConfigForRule(rule) {
    if (rule.field === '__custom__') {
      const customField = this.selectedCustomField(rule);
      if (!customField) return {key: '__custom__', label: 'Custom Field', type: 'text', options: []};
      return {
        key: `custom:${customField.id}`,
        label: `Custom: ${customField.name}`,
        type: customField.field_type,
        options: customField.options || [],
      };
    }
    return this.availableFields.find(entry => entry.key === rule.field) || null;
  }

  operatorsForType(type) {
    if (type === 'status' || type === 'boolean' || type === 'dropdown' || type === 'task_type' || type === 'assignee') {
      return [
        {value: 'eq', label: 'is'},
        {value: 'neq', label: 'is not'},
        {value: 'empty', label: 'is empty'},
        {value: 'not_empty', label: 'is not empty'},
      ];
    }
    if (type === 'color') {
      return [
        {value: 'eq', label: 'is'},
        {value: 'neq', label: 'is not'},
        {value: 'empty', label: 'is empty'},
        {value: 'not_empty', label: 'is not empty'},
      ];
    }
    if (type === 'date' || type === 'number') {
      return [
        {value: 'eq', label: 'equals'},
        {value: 'lt', label: 'less than'},
        {value: 'lte', label: 'less than or equal'},
        {value: 'gt', label: 'greater than'},
        {value: 'gte', label: 'greater than or equal'},
        {value: 'empty', label: 'is empty'},
        {value: 'not_empty', label: 'is not empty'},
      ];
    }
    return [
      {value: 'contains', label: 'contains'},
      {value: 'eq', label: 'equals'},
      {value: 'neq', label: 'does not equal'},
      {value: 'empty', label: 'is empty'},
      {value: 'not_empty', label: 'is not empty'},
    ];
  }

  operatorsForField(fieldKey) {
    const field = this.availableFields.find(entry => entry.key === fieldKey);
    return this.operatorsForType(field?.type || 'text');
  }

  operatorsForRule(rule) {
    const field = this.fieldConfigForRule(rule);
    return this.operatorsForType(field?.type || 'text');
  }

  customFieldOptionLabel(option) {
    if (typeof option === 'string') return option;
    return option?.label || option?.value || '';
  }

  valueOptionsForRule(rule) {
    const field = this.fieldConfigForRule(rule);
    if (!field) return [];
    if (field.type === 'status') {
      return [
        {value: 'True', label: 'Done'},
        {value: 'False', label: 'Open'},
      ];
    }
    if (field.type === 'boolean') {
      return [
        {value: 'True', label: 'Yes'},
        {value: 'False', label: 'No'},
      ];
    }
    if (field.type === 'dropdown') {
      return (field.options || []).map(option => ({
        value: this.customFieldOptionLabel(option),
        label: this.customFieldOptionLabel(option),
      }));
    }
    if (field.type === 'task_type') {
      return this.taskTypes.map(taskType => ({value: String(taskType.id), label: taskType.name}));
    }
    if (field.type === 'assignee') {
      return [
        {value: '__me__', label: `${this.currentUser.display_name} (Me)`},
        ...this.assigneeOptions.map(option => ({
          value: String(option.user_id),
          label: `${option.display_name} (${option.email})`,
        })),
      ];
    }
    return [];
  }

  operatorWithoutValue(operator) {
    return operator === 'empty' || operator === 'not_empty';
  }

  usesDropdownValue(rule) {
    const field = this.fieldConfigForRule(rule);
    return !!field && ['status', 'boolean', 'dropdown', 'task_type', 'assignee'].includes(field.type) && !this.operatorWithoutValue(rule.operator);
  }

  usesDateValueMode(rule) {
    const field = this.fieldConfigForRule(rule);
    return !!field && field.type === 'date';
  }

  usesColorValue(rule) {
    const field = this.fieldConfigForRule(rule);
    return !!field && field.type === 'color' && !this.operatorWithoutValue(rule.operator);
  }

  customRuleTypeDisabled(rule) {
    return rule.field === '__custom__' && !this.selectedCustomField(rule);
  }

  ruleValueDisabled(rule) {
    return this.operatorWithoutValue(rule.operator) || this.customRuleTypeDisabled(rule);
  }

  inputTypeForRule(rule) {
    const field = this.fieldConfigForRule(rule);
    return field?.type === 'date' ? 'date' : (field?.type === 'number' ? 'number' : 'text');
  }

  dateValueMode(rule) {
    return rule.value === 'today' ? 'today' : 'date';
  }

  showSpecificDateInput(rule) {
    return this.dateValueMode(rule) === 'date' && !this.operatorWithoutValue(rule.operator);
  }

  colorSwatchClass(color) {
    return color ? `swatch-${String(color).replace('#', '')}` : 'swatch-empty';
  }

  colorButtonClasses(rule, color) {
    return this.sameString(rule.value || '', color) ? 'ring-2 ring-offset-2 ring-gray-500' : '';
  }

  filterColorButtonClass(rule, color) {
    return `${this.colorSwatchClass(color)} ${this.colorButtonClasses(rule, color)}`.trim();
  }

  clearColorButtonClasses(rule) {
    return !rule.value ? 'ring-2 ring-offset-2 ring-gray-400' : '';
  }

  showColorHelp(rule) {
    return !this.operatorWithoutValue(rule.operator);
  }

  showColorSelection(rule) {
    return !!rule.value;
  }

  colorSelectionLabel(rule) {
    return `Selected: ${rule.value}`;
  }

  setDateValueMode(rule, mode) {
    if (mode === 'today') {
      rule.value = 'today';
      return;
    }
    if (rule.value === 'today') {
      rule.value = '';
    }
  }

  normalizeRule(rule) {
    const normalized = {
      uid: rule.uid || this.nextRuleUid++,
      field: rule.field || (this.availableFields[0]?.key || 'title'),
      operator: rule.operator || 'contains',
      value: rule.value ?? '',
      custom_task_type_id: rule.custom_task_type_id ? String(rule.custom_task_type_id) : '',
      custom_field_id: rule.custom_field_id ? String(rule.custom_field_id) : '',
    };
    if (normalized.field.startsWith('custom:')) {
      const customFieldId = normalized.field.split(':', 2)[1];
      const taskType = this.customFieldTaskTypes.find(entry =>
        (entry.custom_fields || []).some(field => String(field.id) === String(customFieldId))
      );
      normalized.field = '__custom__';
      normalized.custom_task_type_id = taskType ? String(taskType.id) : '';
      normalized.custom_field_id = customFieldId ? String(customFieldId) : '';
    }
    if (normalized.field === '__custom__' && !normalized.custom_task_type_id) {
      const firstTaskType = this.customFieldTaskTypes[0];
      normalized.custom_task_type_id = firstTaskType ? String(firstTaskType.id) : '';
      normalized.custom_field_id = firstTaskType?.custom_fields?.[0] ? String(firstTaskType.custom_fields[0].id) : '';
    }
    const field = this.fieldConfigForRule(normalized);
    if (!field) return normalized;
    if (['status', 'boolean', 'dropdown', 'task_type', 'assignee', 'color'].includes(field.type) && normalized.value !== '' && normalized.value !== null) {
      normalized.value = String(normalized.value);
    }
    if (['status', 'boolean'].includes(field.type) && ['true', 'false'].includes(String(normalized.value).toLowerCase())) {
      normalized.value = String(normalized.value).toLowerCase() === 'true' ? 'True' : 'False';
    }
    const validOperators = this.operatorsForType(field.type || 'text').map(entry => entry.value);
    if (!validOperators.includes(normalized.operator)) {
      normalized.operator = validOperators[0];
    }
    if (this.operatorWithoutValue(normalized.operator)) {
      normalized.value = '';
    }
    return normalized;
  }

  blankFilter() {
    return {
      id: null,
      name: '',
      definition: {
        op: 'and',
        selected_task_type_id: null,
        source_board_ids: [this.boardId],
        rules: [],
        sort_rules: [],
      },
    };
  }

  includesSourceBoard(boardId) {
    return (this.editingFilter?.definition?.source_board_ids || []).some(id => String(id) === String(boardId));
  }

  toggleSourceBoard(boardId) {
    if (!this.editingFilter) return;
    const current = [...(this.editingFilter.definition.source_board_ids || [])].map(id => String(id));
    const target = String(boardId);
    this.editingFilter.definition.source_board_ids = current.includes(target)
      ? current.filter(id => id !== target)
      : [...current, target];
  }

  addRule() {
    const fallbackField = this.availableFields[0]?.key || 'title';
    this.editingFilter.definition.rules.push(this.normalizeRule({
      field: fallbackField,
      operator: this.operatorsForField(fallbackField)[0].value,
      value: '',
    }));
  }

  removeRule(uid) {
    this.editingFilter.definition.rules = this.editingFilter.definition.rules.filter(rule => rule.uid !== uid);
  }

  resetRuleForField(rule) {
    rule.operator = this.operatorsForField(rule.field)[0].value;
    rule.value = '';
    if (rule.field === '__custom__') {
      const firstTaskType = this.customFieldTaskTypes[0];
      rule.custom_task_type_id = firstTaskType ? String(firstTaskType.id) : '';
      rule.custom_field_id = firstTaskType?.custom_fields?.[0] ? String(firstTaskType.custom_fields[0].id) : '';
      const customOperators = this.operatorsForRule(rule);
      rule.operator = customOperators[0]?.value || 'contains';
      return;
    }
    rule.custom_task_type_id = '';
    rule.custom_field_id = '';
  }

  handleCustomTaskTypeChange(rule) {
    const firstField = this.customFieldsForRule(rule)[0];
    rule.custom_field_id = firstField ? String(firstField.id) : '';
    rule.value = '';
    const operators = this.operatorsForRule(rule);
    rule.operator = operators[0]?.value || 'contains';
  }

  handleCustomFieldChange(rule) {
    rule.value = '';
    const operators = this.operatorsForRule(rule);
    rule.operator = operators[0]?.value || 'contains';
  }

  startCreate() {
    if (!this.canEdit || this.saving) return;
    this.saveError = '';
    this.editingFilter = this.blankFilter();
    this.render();
  }

  startEdit(savedFilterId) {
    if (!this.canEdit) return;
    const savedFilter = this.filters.find(entry => entry.id === savedFilterId);
    if (!savedFilter) return;
    this.editingFilter = JSON.parse(JSON.stringify(savedFilter));
    this.saveError = '';
    const sourceBoardIds = this.editingFilter.definition.source_board_ids || [];
    this.editingFilter.definition.source_board_ids = (sourceBoardIds.length ? sourceBoardIds : [this.boardId]).map(id => String(id));
    this.editingFilter.definition.rules = (this.editingFilter.definition.rules || []).map(rule => this.normalizeRule(rule));
    this.editingFilter.definition.sort_rules ||= [];
    this.render();
  }

  cancelEdit() {
    this.editingFilter = null;
    this.render();
  }

  normalizedDefinition() {
    return {
      op: this.editingFilter.definition.op,
      selected_task_type_id: this.editingFilter.definition.selected_task_type_id ?? null,
      source_board_ids: (this.editingFilter.definition.source_board_ids || [])
        .map(id => parseInt(id, 10))
        .filter(id => !Number.isNaN(id)),
      rules: this.editingFilter.definition.rules.map(rule => ({
        field: rule.field === '__custom__' && rule.custom_field_id ? `custom:${rule.custom_field_id}` : rule.field,
        operator: rule.operator,
        value: this.operatorWithoutValue(rule.operator) ? null : rule.value,
      })),
      sort_rules: (this.editingFilter.definition.sort_rules || []).map(rule => ({field: rule.field, direction: rule.direction})),
    };
  }

  async saveFilter() {
    if (!this.canEdit || this.saving) return;
    if (!this.editingFilter.name.trim()) return;
    const payload = {
      name: this.editingFilter.name.trim(),
      definition: this.normalizedDefinition(),
    };
    this.saving = true;
    this.saveError = '';
    this.render();
    try {
      const id = this.editingFilter.id;
      const response = await fetch(id ? `/api/filters/${id}` : '/api/filters', {
        method: id ? 'PUT' : 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(id ? payload : {...payload, board_id: this.boardId}),
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(typeof error.detail === 'string' ? error.detail : 'Could not save filter.');
      }
      this.editingFilter = null;
      await this.load();
    } catch (error) {
      this.saveError = error.message || 'Could not save filter.';
    } finally {
      this.saving = false;
      this.render();
    }
  }

  async deleteFilter(savedFilterId) {
    if (!this.canEdit) return;
    const savedFilter = this.filters.find(entry => entry.id === savedFilterId);
    if (!savedFilter) return;
    if (!confirm(`Delete filter "${savedFilter.name}"?`)) return;
    await fetch(`/api/filters/${savedFilter.id}`, {method: 'DELETE'});
    this.filters = this.filters.filter(entry => entry.id !== savedFilter.id);
    if (this.editingFilter?.id === savedFilter.id) this.editingFilter = null;
    this.render();
  }

  filterSummary(savedFilter) {
    const definition = savedFilter.definition || {op: 'and', selected_task_type_id: null, source_board_ids: [], rules: []};
    const ruleCount = (definition.rules || []).length;
    const sourceNames = (definition.source_board_ids || [])
      .map(boardId => this.boards.find(board => String(board.id) === String(boardId))?.name)
      .filter(Boolean);
    const parts = [];
    parts.push(`Hubs: ${(sourceNames.length ? sourceNames : [this.boards.find(board => String(board.id) === String(this.boardId))?.name || 'Current hub']).join(', ')}`);
    parts.push(`${ruleCount} rule${ruleCount === 1 ? '' : 's'}`);
    parts.push(definition.op?.toUpperCase() || 'AND');
    if (definition.sort_rules?.length) {
      parts.push('Sort: ' + definition.sort_rules.map(rule => `${this.sortFieldLabel(rule.field)} ${rule.direction === 'desc' ? '↓' : '↑'}`).join(', then '));
    }
    return parts.join(' • ');
  }

  sortFieldLabel(key) {
    return this.availableSortFields.find(field => field.key === key)?.label || 'Unavailable field';
  }

  addSortRule() {
    const rules = this.editingFilter.definition.sort_rules;
    if (rules.length >= 10) return;
    const field = this.availableSortFields.find(field => !rules.some(rule => rule.field === field.key));
    if (field) rules.push({field: field.key, direction: 'asc'});
  }

  moveSortRule(index, offset) {
    const rules = this.editingFilter.definition.sort_rules;
    const target = index + offset;
    if (target < 0 || target >= rules.length) return;
    [rules[index], rules[target]] = [rules[target], rules[index]];
  }

  ruleByUid(uid) {
    return this.editingFilter?.definition?.rules?.find(rule => rule.uid === uid) || null;
  }

  render() {
    this.readonlyBanner.classList.toggle('hidden', this.canEdit);
    this.newButton.classList.toggle('hidden', !this.canEdit);
    this.editorContainer.innerHTML = this.editingFilter ? this.renderEditor() : '';
    this.listContainer.innerHTML = this.filters.map(savedFilter => this.renderSavedFilter(savedFilter)).join('');
    this.emptyState.classList.toggle('hidden', this.filters.length > 0);
  }

  renderSavedFilter(savedFilter) {
    const actions = this.canEdit
      ? `
        <button type="button" data-action="edit-filter" data-filter-id="${savedFilter.id}" class="text-sm text-blue-600 hover:text-blue-700 transition-colors">Edit</button>
        <button type="button" data-action="delete-filter" data-filter-id="${savedFilter.id}" class="text-sm text-red-400 hover:text-red-600 transition-colors">Delete</button>
      `
      : '';
    return `
      <div class="bg-white rounded-xl shadow p-4 flex items-center gap-4">
        <div class="flex-1 min-w-0">
          <div class="font-medium text-gray-800 text-sm">${escapeHtml(savedFilter.name)}</div>
          <div class="text-xs text-gray-400 mt-0.5">${escapeHtml(this.filterSummary(savedFilter))}</div>
        </div>
        ${actions}
      </div>
    `;
  }

  renderEditor() {
    return `
      <div class="bg-white rounded-xl shadow p-5 mb-6">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-semibold text-gray-700">${escapeHtml(this.editorTitle())}</h2>
          <button type="button" data-action="cancel-edit" class="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        ${this.renderEditorHeader()}
        ${this.renderSourceBoards()}
        ${this.renderRules()}
        ${this.renderSortRules()}
        ${this.saveError ? `<p class="text-sm text-red-600 mt-3" role="alert">${escapeHtml(this.saveError)}</p>` : ''}
        <div class="flex justify-end gap-2 border-t pt-4 mt-5">
          <button type="button" data-action="cancel-edit" class="text-gray-500 hover:text-gray-700 px-4 py-2 text-sm">Cancel</button>
          <button type="button" data-action="save-filter" ${renderDisabled(this.saving)} class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">${this.saving ? 'Saving…' : 'Save Filter'}</button>
        </div>
      </div>
    `;
  }

  renderEditorHeader() {
    return `
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div class="md:col-span-2">
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Name</label>
          <input data-field="filter-name" value="${escapeHtml(this.editingFilter.name || '')}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" placeholder="e.g. Open Bugs, Overdue Work...">
        </div>
        <div>
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Match</label>
          <select data-field="filter-op" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <option value="and"${renderSelected(this.editingFilter.definition.op, 'and')}>All rules (AND)</option>
            <option value="or"${renderSelected(this.editingFilter.definition.op, 'or')}>Any rule (OR)</option>
          </select>
        </div>
      </div>
    `;
  }

  renderSourceBoards() {
    const options = this.boards.map(board => {
      const currentBadge = this.sameString(board.id, this.boardId)
        ? '<span class="text-[11px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700">Current</span>'
        : '';
      const roleBadge = board.role
        ? `<span class="text-[11px] px-1.5 py-0.5 rounded-full ${roleBadgeClass(board)}">${escapeHtml(roleBadgeLabel(board))}</span>`
        : '';
      return `
        <label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input type="checkbox" data-field="source-board" data-board-id="${board.id}" class="h-4 w-4 rounded accent-blue-500"${renderChecked(this.includesSourceBoard(board.id))}>
          <span>${escapeHtml(board.name)}</span>
          ${currentBadge}
          ${roleBadge}
        </label>
      `;
    }).join('');

    return `
      <div class="mb-4">
        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Source Hubs</label>
        <div class="bg-gray-50 border rounded-xl p-3 space-y-2">
          ${options}
        </div>
        <p class="mt-1 text-xs text-gray-400">Logs using this filter will pull objectives from the selected hubs you can access.</p>
      </div>
    `;
  }

  renderRules() {
    const ruleMarkup = this.editingFilter.definition.rules.map((rule, index) => this.renderRule(rule, index)).join('');
    return `
      <div class="space-y-3">
        ${ruleMarkup}
        <button type="button" data-action="add-rule" class="text-sm text-blue-600 hover:text-blue-700 font-medium">+ Add rule</button>
      </div>
    `;
  }

  renderRule(rule, index) {
    return `
      <div class="bg-gray-50 rounded-xl p-3 border">
        <div class="grid grid-cols-1 md:grid-cols-[1.4fr_1fr_1.4fr_auto] gap-3 items-end">
          ${this.renderRuleField(rule)}
          ${rule.field === '__custom__' ? this.renderCustomRuleSelectors(rule) : ''}
          ${this.renderRuleOperator(rule)}
          ${this.renderRuleValue(rule)}
          <button type="button" data-action="remove-rule" data-rule-uid="${rule.uid}" class="text-gray-400 hover:text-red-500 px-2 py-2 text-sm transition-colors">Remove</button>
        </div>
      </div>
    `;
  }

  renderSortRules() {
    const rules = this.editingFilter.definition.sort_rules || [];
    const markup = rules.map((rule, index) => {
      const fields = this.availableSortFields.map(field => `<option value="${escapeHtml(field.key)}"${renderSelected(rule.field, field.key)}${renderDisabled(rules.some((other, otherIndex) => otherIndex !== index && other.field === field.key))}>${escapeHtml(field.label)}</option>`).join('');
      const unavailable = !this.availableSortFields.some(field => field.key === rule.field)
        ? `<option value="${escapeHtml(rule.field)}" selected>Unavailable field</option>` : '';
      return `<div class="bg-gray-50 rounded-xl p-3 border" data-sort-rule="${index}">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label for="filter-sort-field-${index}" class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">${index === 0 ? 'Sort by' : 'Then by'}</label>
            <select id="filter-sort-field-${index}" data-field="sort-field" data-sort-index="${index}" aria-label="Sort field ${index + 1}" class="w-full border rounded-lg px-3 py-2 text-sm">${unavailable}${fields}</select>
          </div>
          <div>
            <label for="filter-sort-direction-${index}" class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Direction</label>
            <select id="filter-sort-direction-${index}" data-field="sort-direction" data-sort-index="${index}" aria-label="Sort direction ${index + 1}" class="w-full border rounded-lg px-3 py-2 text-sm">
              <option value="asc"${renderSelected(rule.direction, 'asc')}>Ascending</option>
              <option value="desc"${renderSelected(rule.direction, 'desc')}>Descending</option>
            </select>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" data-action="move-sort-up" data-sort-index="${index}" aria-label="Move sort rule ${index + 1} up"${renderDisabled(index === 0)} class="border rounded-lg px-3 py-2 text-sm">↑</button>
            <button type="button" data-action="move-sort-down" data-sort-index="${index}" aria-label="Move sort rule ${index + 1} down"${renderDisabled(index === rules.length - 1)} class="border rounded-lg px-3 py-2 text-sm">↓</button>
            <button type="button" data-action="remove-sort" data-sort-index="${index}" class="text-gray-400 hover:text-red-500 px-2 py-2 text-sm">Remove</button>
          </div>
        </div>
      </div>`;
    }).join('');
    return `<section class="border-t pt-4 mt-5" aria-labelledby="filter-sort-heading">
      <h3 id="filter-sort-heading" class="font-semibold text-gray-700 mb-2">Sort order</h3>
      <p class="text-xs text-gray-400 mb-3">${rules.length ? 'The first field has priority; later fields break ties. Empty values are always last.' : 'No sorting rules. Logs keep their current order: newest objectives first.'}</p>
      <div class="space-y-3">${markup}</div>
      <button type="button" data-action="add-sort"${renderDisabled(rules.length >= 10)} class="text-sm text-blue-600 hover:text-blue-700 font-medium mt-3">+ Add sorting rule</button>
      ${rules.length ? '<p class="text-xs text-gray-400 mt-2">Dropdowns use the option order set on their Objective type. Descending reverses it.</p>' : ''}
    </section>`;
  }

  renderRuleField(rule) {
    const options = this.availableFields.map(field => (
      `<option value="${escapeHtml(field.key)}"${renderSelected(rule.field, field.key)}>${escapeHtml(field.label)}</option>`
    )).join('');
    return `
      <div>
        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Field</label>
        <select data-field="rule-field" data-rule-uid="${rule.uid}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
          ${options}
        </select>
      </div>
    `;
  }

  renderCustomRuleSelectors(rule) {
    const taskTypeOptions = this.customFieldTaskTypes.map(taskType => (
      `<option value="${escapeHtml(this.asString(taskType.id))}"${renderSelected(rule.custom_task_type_id || '', this.asString(taskType.id))}>${escapeHtml(taskType.name)}</option>`
    )).join('');
    const customFieldOptions = this.customFieldsForRule(rule).map(field => (
      `<option value="${escapeHtml(this.asString(field.id))}"${renderSelected(rule.custom_field_id || '', this.asString(field.id))}>${escapeHtml(field.name)}</option>`
    )).join('');
    return `
      <div class="md:col-span-3 grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Objective Type</label>
          <select data-field="rule-custom-task-type" data-rule-uid="${rule.uid}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <option value="">Select type</option>
            ${taskTypeOptions}
          </select>
        </div>
        <div>
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Custom Field</label>
          <select data-field="rule-custom-field" data-rule-uid="${rule.uid}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"${renderDisabled(!rule.custom_task_type_id)}>
            <option value="">Select field</option>
            ${customFieldOptions}
          </select>
        </div>
      </div>
    `;
  }

  renderRuleOperator(rule) {
    const options = this.operatorsForRule(rule).map(operator => (
      `<option value="${escapeHtml(operator.value)}"${renderSelected(rule.operator, operator.value)}>${escapeHtml(operator.label)}</option>`
    )).join('');
    return `
      <div>
        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Operator</label>
        <select data-field="rule-operator" data-rule-uid="${rule.uid}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"${renderDisabled(this.customRuleTypeDisabled(rule))}>
          ${options}
        </select>
      </div>
    `;
  }

  renderRuleValue(rule) {
    return `
      <div>
        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Value</label>
        ${this.renderRuleValueContent(rule)}
      </div>
    `;
  }

  renderRuleValueContent(rule) {
    if (this.usesDropdownValue(rule)) {
      const options = this.valueOptionsForRule(rule).map(option => (
        `<option value="${escapeHtml(option.value)}"${renderSelected(rule.value ?? '', option.value)}>${escapeHtml(option.label)}</option>`
      )).join('');
      return `
        <select data-field="rule-value" data-rule-uid="${rule.uid}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"${renderDisabled(this.customRuleTypeDisabled(rule))}>
          <option value="">Select value</option>
          ${options}
        </select>
      `;
    }

    if (this.usesDateValueMode(rule)) {
      return `
        <div class="space-y-2">
          <select data-field="rule-date-mode" data-rule-uid="${rule.uid}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"${renderDisabled(this.operatorWithoutValue(rule.operator))}>
            <option value="date"${renderSelected(this.dateValueMode(rule), 'date')}>Specific date</option>
            <option value="today"${renderSelected(this.dateValueMode(rule), 'today')}>Today</option>
          </select>
          ${this.showSpecificDateInput(rule)
            ? `<input type="date" data-field="rule-value" data-rule-uid="${rule.uid}" value="${escapeHtml(rule.value || '')}" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">`
            : ''}
        </div>
      `;
    }

    if (this.usesColorValue(rule)) {
      const buttons = PRESET_COLORS.map(color => `
        <button
          type="button"
          data-action="set-rule-color"
          data-rule-uid="${rule.uid}"
          data-color="${color}"
          class="h-7 w-7 rounded-full border border-black/10 transition-transform hover:scale-110 disabled:opacity-50 disabled:hover:scale-100 ${this.filterColorButtonClass(rule, color)}"
          title="${color}"
          ${this.ruleValueDisabled(rule) ? 'disabled' : ''}
        ></button>
      `).join('');
      const help = this.showColorHelp(rule)
        ? `<div class="text-xs text-gray-500">${this.showColorSelection(rule) ? escapeHtml(this.colorSelectionLabel(rule)) : 'Choose a color'}</div>`
        : '';
      return `
        <div class="space-y-2">
          <div class="flex flex-wrap gap-2">
            ${buttons}
            <button
              type="button"
              data-action="clear-rule-color"
              data-rule-uid="${rule.uid}"
              class="h-7 w-7 rounded-full border border-dashed border-gray-300 bg-gray-100 text-xs text-gray-400 transition-colors hover:bg-gray-200 disabled:opacity-50 ${this.clearColorButtonClasses(rule)}"
              title="No color"
              ${this.ruleValueDisabled(rule) ? 'disabled' : ''}
            >✕</button>
          </div>
          ${help}
        </div>
      `;
    }

    return `
      <input
        type="${this.inputTypeForRule(rule)}"
        data-field="rule-value"
        data-rule-uid="${rule.uid}"
        value="${escapeHtml(rule.value ?? '')}"
        class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        placeholder="Value"
        ${this.ruleValueDisabled(rule) ? 'disabled' : ''}
      >
    `;
  }

  handleClick(event) {
    const actionTarget = event.target.closest('[data-action]');
    if (!actionTarget) return;
    const action = actionTarget.dataset.action;
    const filterId = Number.parseInt(actionTarget.dataset.filterId || '', 10);
    const ruleUid = Number.parseInt(actionTarget.dataset.ruleUid || '', 10);
    if (!this.canEdit || this.saving) return;
    if (['add-sort', 'remove-sort', 'move-sort-up', 'move-sort-down'].includes(action) && this.editingFilter) {
      const index = Number.parseInt(actionTarget.dataset.sortIndex || '', 10);
      if (action === 'add-sort') this.addSortRule();
      else if (action === 'remove-sort') this.editingFilter.definition.sort_rules.splice(index, 1);
      else this.moveSortRule(index, action === 'move-sort-up' ? -1 : 1);
      this.render();
      const rules = this.editingFilter.definition.sort_rules;
      const next = action === 'add-sort' ? rules.length - 1 : action === 'move-sort-up' ? index - 1 : action === 'move-sort-down' ? index + 1 : Math.min(index, rules.length - 1);
      this.root.querySelector(next < 0 ? '[data-action="add-sort"]' : `[data-field="sort-field"][data-sort-index="${next}"]`)?.focus?.();
      return;
    }

    if (action === 'add-rule') {
      this.addRule();
      this.render();
      return;
    }
    if (action === 'cancel-edit') {
      this.cancelEdit();
      return;
    }
    if (action === 'save-filter') {
      this.saveFilter();
      return;
    }
    if (action === 'edit-filter' && !Number.isNaN(filterId)) {
      this.startEdit(filterId);
      return;
    }
    if (action === 'delete-filter' && !Number.isNaN(filterId)) {
      this.deleteFilter(filterId);
      return;
    }
    if (action === 'remove-rule' && !Number.isNaN(ruleUid)) {
      this.removeRule(ruleUid);
      this.render();
      return;
    }
    if (action === 'set-rule-color' && !Number.isNaN(ruleUid)) {
      const rule = this.ruleByUid(ruleUid);
      if (!rule) return;
      rule.value = actionTarget.dataset.color || '';
      this.render();
      return;
    }
    if (action === 'clear-rule-color' && !Number.isNaN(ruleUid)) {
      const rule = this.ruleByUid(ruleUid);
      if (!rule) return;
      rule.value = '';
      this.render();
      return;
    }
  }

  handleInput(event) {
    if (!this.editingFilter || !this.canEdit || this.saving) return;
    const field = event.target.dataset.field;
    if (field === 'filter-name') {
      this.editingFilter.name = event.target.value;
      return;
    }
    if (field === 'rule-value') {
      const ruleUid = Number.parseInt(event.target.dataset.ruleUid || '', 10);
      const rule = this.ruleByUid(ruleUid);
      if (!rule) return;
      rule.value = event.target.value;
    }
  }

  handleChange(event) {
    const field = event.target.dataset.field;
    if (!field) return;
    if (!this.editingFilter && field !== 'source-board') return;
    if (!this.canEdit || this.saving) return;
    if (field === 'sort-field' || field === 'sort-direction') {
      const rule = this.editingFilter.definition.sort_rules[Number(event.target.dataset.sortIndex)];
      if (rule) rule[field === 'sort-field' ? 'field' : 'direction'] = event.target.value;
      this.render();
      this.root.querySelector(`[data-field="${field}"][data-sort-index="${event.target.dataset.sortIndex}"]`)?.focus?.();
      return;
    }

    if (field === 'filter-op') {
      this.editingFilter.definition.op = event.target.value;
      return;
    }
    if (field === 'source-board') {
      this.toggleSourceBoard(event.target.dataset.boardId || '');
      return;
    }

    const ruleUid = Number.parseInt(event.target.dataset.ruleUid || '', 10);
    const rule = this.ruleByUid(ruleUid);
    if (!rule) return;

    if (field === 'rule-field') {
      rule.field = event.target.value;
      this.resetRuleForField(rule);
      this.render();
      return;
    }
    if (field === 'rule-custom-task-type') {
      rule.custom_task_type_id = event.target.value;
      this.handleCustomTaskTypeChange(rule);
      this.render();
      return;
    }
    if (field === 'rule-custom-field') {
      rule.custom_field_id = event.target.value;
      this.handleCustomFieldChange(rule);
      this.render();
      return;
    }
    if (field === 'rule-operator') {
      rule.operator = event.target.value;
      if (this.operatorWithoutValue(rule.operator)) {
        rule.value = '';
      }
      this.render();
      return;
    }
    if (field === 'rule-date-mode') {
      this.setDateValueMode(rule, event.target.value);
      this.render();
      return;
    }
    if (field === 'rule-value') {
      rule.value = event.target.value;
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('filters-page');
  if (!root) return;
  const controller = new FiltersPageController(root);
  controller.init();
  const newButton = root.querySelector('#filters-new-button');
  if (newButton) {
    newButton.addEventListener('click', () => controller.startCreate());
  }
});

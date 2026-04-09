function filtersPage(boardId, boardRole, boards, currentUser, assigneeOptions) {
  return {
    boardId,
    boardRole,
    boards,
    currentUser,
    assigneeOptions,
    filters: [],
    taskTypes: [],
    editingFilter: null,
    nextRuleUid: 1,

    get canEdit() {
      return this.boardRole === 'owner' || this.boardRole === 'editor' || this.boardRole === 'admin';
    },

    async init() {
      await this.load();
    },

    async load() {
      const [filtersRes, taskTypesRes] = await Promise.all([
        fetch('/api/filters?board_id=' + this.boardId),
        fetch('/api/task-types?board_id=' + this.boardId),
      ]);
      this.filters = await filtersRes.json();
      this.taskTypes = await taskTypesRes.json();
    },

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
    },

    get customFieldTaskTypes() {
      return this.taskTypes.filter(taskType => (taskType.custom_fields || []).length > 0);
    },

    customFieldsForRule(rule) {
      const taskType = this.customFieldTaskTypes.find(taskType => String(taskType.id) === String(rule.custom_task_type_id || ''));
      return taskType?.custom_fields || [];
    },

    selectedCustomField(rule) {
      return this.customFieldsForRule(rule).find(field => String(field.id) === String(rule.custom_field_id || '')) || null;
    },

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
    },

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
    },

    operatorsForField(fieldKey) {
      const field = this.availableFields.find(entry => entry.key === fieldKey);
      const type = field?.type || 'text';
      return this.operatorsForType(type);
    },

    operatorsForRule(rule) {
      const field = this.fieldConfigForRule(rule);
      return this.operatorsForType(field?.type || 'text');
    },

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
    },

    usesDropdownValue(rule) {
      const field = this.fieldConfigForRule(rule);
      return !!field && ['status', 'boolean', 'dropdown', 'task_type', 'assignee'].includes(field.type) && !this.operatorWithoutValue(rule.operator);
    },

    usesDateValueMode(rule) {
      const field = this.fieldConfigForRule(rule);
      return !!field && field.type === 'date';
    },

    usesColorValue(rule) {
      const field = this.fieldConfigForRule(rule);
      return !!field && field.type === 'color' && !this.operatorWithoutValue(rule.operator);
    },

    customFieldOptionLabel(option) {
      if (typeof option === 'string') return option;
      return option?.label || option?.value || '';
    },

    inputTypeForRule(rule) {
      const field = this.fieldConfigForRule(rule);
      return field?.type === 'date' ? 'date' : (field?.type === 'number' ? 'number' : 'text');
    },

    operatorWithoutValue(operator) {
      return operator === 'empty' || operator === 'not_empty';
    },

    dateValueMode(rule) {
      return rule.value === 'today' ? 'today' : 'date';
    },

    setDateValueMode(rule, mode) {
      if (mode === 'today') {
        rule.value = 'today';
        return;
      }
      if (rule.value === 'today') {
        rule.value = '';
      }
    },

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
      const validOperators = this.operatorsForType(field.type || 'text').map(entry => entry.value);
      if (!validOperators.includes(normalized.operator)) {
        normalized.operator = validOperators[0];
      }
      if (this.operatorWithoutValue(normalized.operator)) {
        normalized.value = '';
      }
      return normalized;
    },

    blankFilter() {
      return {
        id: null,
        name: '',
        definition: {
          op: 'and',
          selected_task_type_id: null,
          source_board_ids: [this.boardId],
          rules: [],
        },
      };
    },

    includesSourceBoard(boardId) {
      return (this.editingFilter?.definition?.source_board_ids || []).some(id => String(id) === String(boardId));
    },

    toggleSourceBoard(boardId) {
      if (!this.editingFilter) return;
      const current = [...(this.editingFilter.definition.source_board_ids || [])].map(id => String(id));
      const target = String(boardId);
      this.editingFilter.definition.source_board_ids = current.includes(target)
        ? current.filter(id => id !== target)
        : [...current, target];
    },

    addRule() {
      const fallbackField = this.availableFields[0]?.key || 'title';
      this.editingFilter.definition.rules.push(this.normalizeRule({field: fallbackField, operator: this.operatorsForField(fallbackField)[0].value, value: ''}));
    },

    removeRule(idx) {
      this.editingFilter.definition.rules.splice(idx, 1);
    },

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
    },

    handleCustomTaskTypeChange(rule) {
      const firstField = this.customFieldsForRule(rule)[0];
      rule.custom_field_id = firstField ? String(firstField.id) : '';
      rule.value = '';
      const operators = this.operatorsForRule(rule);
      rule.operator = operators[0]?.value || 'contains';
    },

    handleCustomFieldChange(rule) {
      rule.value = '';
      const operators = this.operatorsForRule(rule);
      rule.operator = operators[0]?.value || 'contains';
    },

    startCreate() {
      if (!this.canEdit) return;
      this.editingFilter = this.blankFilter();
    },

    startEdit(savedFilter) {
      if (!this.canEdit) return;
      this.editingFilter = JSON.parse(JSON.stringify(savedFilter));
      const sourceBoardIds = this.editingFilter.definition.source_board_ids || [];
      this.editingFilter.definition.source_board_ids = (sourceBoardIds.length ? sourceBoardIds : [this.boardId]).map(id => String(id));
      this.editingFilter.definition.rules = (this.editingFilter.definition.rules || []).map(rule => this.normalizeRule(rule));
    },

    cancelEdit() {
      this.editingFilter = null;
    },

    normalizedDefinition() {
      return {
        op: this.editingFilter.definition.op,
        selected_task_type_id: null,
        source_board_ids: (this.editingFilter.definition.source_board_ids || [])
          .map(id => parseInt(id, 10))
          .filter(id => !Number.isNaN(id)),
        rules: this.editingFilter.definition.rules.map(rule => ({
          field: rule.field === '__custom__' && rule.custom_field_id ? `custom:${rule.custom_field_id}` : rule.field,
          operator: rule.operator,
          value: this.operatorWithoutValue(rule.operator) ? null : rule.value,
        })),
      };
    },

    async saveFilter() {
      if (!this.canEdit) return;
      if (!this.editingFilter.name.trim()) return;
      const payload = {
        name: this.editingFilter.name.trim(),
        definition: this.normalizedDefinition(),
      };
      if (this.editingFilter.id) {
        await fetch(`/api/filters/${this.editingFilter.id}`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
      } else {
        await fetch('/api/filters', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({...payload, board_id: this.boardId}),
        });
      }
      this.editingFilter = null;
      await this.load();
    },

    async deleteFilter(savedFilter) {
      if (!this.canEdit) return;
      if (!confirm(`Delete filter "${savedFilter.name}"?`)) return;
      await fetch(`/api/filters/${savedFilter.id}`, {method: 'DELETE'});
      this.filters = this.filters.filter(entry => entry.id !== savedFilter.id);
      if (this.editingFilter?.id === savedFilter.id) this.editingFilter = null;
    },

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
      return parts.join(' • ');
    },
  };
}

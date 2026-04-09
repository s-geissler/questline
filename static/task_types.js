function _parsePageJson(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function taskTypesPage() {
  return {
    boardId: 0,
    boardRole: null,
    boards: [],
    taskTypes: [],
    stages: [],
    stagesByBoard: {},
    showCreateForm: false,
    newType: {name: '', is_epic: false},

    get canEdit() {
      return this.boardRole === 'owner' || this.boardRole === 'editor' || this.boardRole === 'admin';
    },

    get hasTaskTypes() {
      return this.taskTypes.length > 0;
    },

    asString(value) {
      return value === null || value === undefined ? '' : String(value);
    },

    typeInputId(tt) {
      return `type-name-${tt.id}`;
    },

    fieldNameInputId(tt) {
      return `field-name-${tt.id}`;
    },

    taskTypeSwatchStyle(tt) {
      return tt.color ? `background:${tt.color}` : 'background:#e5e7eb';
    },

    fieldSwatchStyle(field) {
      return field.color ? `background:${field.color}` : 'background:#e5e7eb';
    },

    colorSwatchStyle(color) {
      return `background:${color}`;
    },

    selectedColorClass(currentColor, color) {
      return currentColor === color ? 'ring-2 ring-offset-1 ring-gray-500' : '';
    },

    hasCustomFields(tt) {
      return !!(tt.custom_fields && tt.custom_fields.length > 0);
    },

    blankNewField() {
      return {name: '', field_type: 'text', show_on_card: false, options: [], newOption: ''};
    },

    normalizeOption(option) {
      if (typeof option === 'string') return {label: option, color: null, showColorPicker: false};
      return {
        label: option?.label || option?.value || '',
        color: option?.color || null,
        showColorPicker: false,
      };
    },

    normalizeField(field) {
      return {
        ...field,
        newOption: '',
        showColorPicker: false,
        options: (field.options || []).map(option => this.normalizeOption(option)),
      };
    },

    optionSwatchStyle(option) {
      return option?.color ? `background:${option.color}` : 'background:#e5e7eb';
    },

    async init() {
      this.boardId = parseInt(this.$el.dataset.boardId || '0', 10);
      this.boardRole = _parsePageJson(this.$el.dataset.boardRole, null);
      this.boards = _parsePageJson(this.$el.dataset.boards, []);
      await this.load();
    },

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
      this.taskTypes = types.map(tt => ({
        ...tt,
        spawn_board_id: String(this.findBoardIdForSpawnStage(tt.spawn_stage_id) || this.boardId),
        available_spawn_stages: this.spawnStagesForBoard(this.findBoardIdForSpawnStage(tt.spawn_stage_id) || this.boardId),
        editing: false,
        editName: tt.name,
        showColorPicker: false,
        showAddField: false,
        newField: this.blankNewField(),
        custom_fields: tt.custom_fields.map(f => this.normalizeField(f)),
      }));
    },

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
      const tt = await res.json();
      this.taskTypes.push({
        ...tt,
        spawn_board_id: String(this.boardId),
        available_spawn_stages: this.spawnStagesForBoard(this.boardId),
        editing: false,
        editName: tt.name,
        showColorPicker: false,
        showAddField: false,
        newField: this.blankNewField(),
        custom_fields: [],
      });
      this.newType = {name: '', is_epic: false};
      this.showCreateForm = false;
    },

    openCreateTypeForm() {
      if (!this.canEdit) return;
      this.showCreateForm = true;
      this.$nextTick(() => this.$refs.newTypeName?.focus());
    },

    closeCreateTypeForm() {
      this.showCreateForm = false;
    },

    startEditType(tt) {
      if (!this.canEdit) return;
      tt.editing = true;
      tt.editName = tt.name;
      this.$nextTick(() => {
        const el = document.getElementById(this.typeInputId(tt));
        el?.focus();
      });
    },

    async saveTypeName(tt) {
      if (!this.canEdit) return;
      if (!tt.editName.trim() || tt.editName === tt.name) {
        tt.editing = false;
        return;
      }
      await fetch(`/api/task-types/${tt.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: tt.editName.trim()}),
      });
      tt.name = tt.editName.trim();
      tt.editing = false;
    },

    async toggleEpic(tt) {
      if (!this.canEdit) return;
      const res = await fetch(`/api/task-types/${tt.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({is_epic: !tt.is_epic}),
      });
      const updated = await res.json();
      tt.is_epic = updated.is_epic;
    },

    async toggleTypeDescriptionOnCard(tt) {
      if (!this.canEdit) return;
      const res = await fetch(`/api/task-types/${tt.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({show_description_on_card: !tt.show_description_on_card}),
      });
      const updated = await res.json();
      tt.show_description_on_card = updated.show_description_on_card;
    },

    async toggleTypeChecklistOnCard(tt) {
      if (!this.canEdit) return;
      const res = await fetch(`/api/task-types/${tt.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({show_checklist_on_card: !tt.show_checklist_on_card}),
      });
      const updated = await res.json();
      tt.show_checklist_on_card = updated.show_checklist_on_card;
    },

    async setSpawnStage(tt, value) {
      if (!this.canEdit) return;
      const spawn_stage_id = value ? parseInt(value) : null;
      const res = await fetch(`/api/task-types/${tt.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({spawn_stage_id}),
      });
      const updated = await res.json();
      tt.spawn_stage_id = updated.spawn_stage_id;
      tt.spawn_board_id = String(this.findBoardIdForSpawnStage(updated.spawn_stage_id) || tt.spawn_board_id || this.boardId);
      tt.available_spawn_stages = this.spawnStagesForBoard(tt.spawn_board_id);
    },

    handleSpawnBoardChange(tt) {
      if (!this.canEdit) return;
      tt.available_spawn_stages = this.spawnStagesForBoard(tt.spawn_board_id);
      const availableStages = tt.available_spawn_stages;
      if (!tt.spawn_stage_id) return;
      if (!availableStages.some(stage => String(stage.id) === String(tt.spawn_stage_id))) {
        tt.spawn_stage_id = '';
        this.setSpawnStage(tt, '');
      }
    },

    async deleteType(tt) {
      if (!this.canEdit) return;
      if (!confirm(`Delete objective type "${tt.name}"? Objectives using this type will lose their type.`)) return;
      await fetch(`/api/task-types/${tt.id}`, {method: 'DELETE'});
      this.taskTypes = this.taskTypes.filter(t => t.id !== tt.id);
    },

    async addField(tt) {
      if (!this.canEdit) return;
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
      const field = await res.json();
      tt.custom_fields.push(this.normalizeField(field));
      tt.newField = this.blankNewField();
      tt.showAddField = false;
    },

    toggleAddFieldForm(tt) {
      if (!this.canEdit) return;
      tt.showAddField = !tt.showAddField;
      if (!tt.showAddField) return;
      tt.newField = this.blankNewField();
      this.$nextTick(() => document.getElementById(this.fieldNameInputId(tt))?.focus());
    },

    addNewFieldOption(tt) {
      if (!this.canEdit) return;
      if (!tt.newField.newOption.trim()) return;
      tt.newField.options.push(this.normalizeOption({label: tt.newField.newOption.trim(), color: null}));
      tt.newField.newOption = '';
    },

    async addFieldOption(tt, field) {
      if (!this.canEdit) return;
      if (!field.newOption.trim()) return;
      const newOptions = [...(field.options || []), this.normalizeOption({label: field.newOption.trim(), color: null})];
      const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: field.name, field_type: field.field_type, show_on_card: field.show_on_card, options: newOptions}),
      });
      const updated = await res.json();
      field.options = (updated.options || []).map(option => this.normalizeOption(option));
      field.newOption = '';
    },

    async removeFieldOption(tt, field, idx) {
      if (!this.canEdit) return;
      const newOptions = field.options.filter((_, i) => i !== idx);
      const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: field.name, field_type: field.field_type, show_on_card: field.show_on_card, options: newOptions}),
      });
      const updated = await res.json();
      field.options = (updated.options || []).map(option => this.normalizeOption(option));
    },

    async setFieldOptionColor(tt, field, idx, color) {
      if (!this.canEdit) return;
      const newOptions = field.options.map((option, optionIndex) => (
        optionIndex === idx ? {...option, color} : option
      ));
      const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: field.name, field_type: field.field_type, show_on_card: field.show_on_card, options: newOptions}),
      });
      const updated = await res.json();
      field.options = (updated.options || []).map(option => this.normalizeOption(option));
    },

    setNewFieldOptionColor(tt, idx, color) {
      if (!this.canEdit) return;
      tt.newField.options[idx].color = color;
    },

    async toggleShowOnCard(tt, field) {
      if (!this.canEdit) return;
      const res = await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: field.name, field_type: field.field_type, show_on_card: !field.show_on_card}),
      });
      const updated = await res.json();
      field.show_on_card = updated.show_on_card;
    },

    async deleteField(tt, field) {
      if (!this.canEdit) return;
      if (!confirm(`Delete field "${field.name}"?`)) return;
      await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {method: 'DELETE'});
      tt.custom_fields = tt.custom_fields.filter(f => f.id !== field.id);
    },

    async setFieldColor(tt, field, color) {
      if (!this.canEdit) return;
      await fetch(`/api/task-types/${tt.id}/fields/${field.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: field.name, field_type: field.field_type, show_on_card: field.show_on_card, color}),
      });
      field.color = color;
    },

    async setTypeColor(tt, color) {
      if (!this.canEdit) return;
      await fetch(`/api/task-types/${tt.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({color}),
      });
      tt.color = color;
    },

    spawnStagesForBoard(boardId) {
      return (this.stagesByBoard[String(boardId || this.boardId)] || []).filter(stage => !stage.is_log);
    },

    findBoardIdForSpawnStage(stageId) {
      if (!stageId) return this.boardId;
      for (const [boardId, stages] of Object.entries(this.stagesByBoard)) {
        if (stages.some(stage => stage.id === stageId)) return parseInt(boardId);
      }
      return this.boardId;
    },
  };
}

document.addEventListener('alpine:init', () => {
  Alpine.data('taskTypesPage', taskTypesPage);
});

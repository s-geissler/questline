function automationsPage() {
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
      this.boardId = parseInt(this.$el.dataset.boardId || '0', 10);
      this.boardRole = JSON.parse(this.$el.dataset.boardRole || 'null');
      const [autoRes, stageRes, taskTypesRes] = await Promise.all([
        fetch('/api/automations?board_id=' + this.boardId),
        fetch('/api/stages?board_id=' + this.boardId),
        fetch('/api/task-types?board_id=' + this.boardId),
      ]);
      this.automations = await autoRes.json();
      this.stages = await stageRes.json();
      this.taskTypes = await taskTypesRes.json();
    },

    triggerLabel(auto) {
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

    actionLabel(auto) {
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
          trigger_stage_id: this.newAuto.trigger_stage_id ? parseInt(this.newAuto.trigger_stage_id) : null,
          action_type: this.newAuto.action_type,
          action_stage_id: this.newAuto.action_stage_id ? parseInt(this.newAuto.action_stage_id) : null,
          action_task_type_id: this.newAuto.action_task_type_id ? parseInt(this.newAuto.action_task_type_id) : null,
          action_color: this.newAuto.action_color || null,
          action_days_offset: this.newAuto.action_type === 'set_due_in_days' ? parseInt(this.newAuto.action_days_offset) : null,
          board_id: this.boardId,
        }),
      });
      const auto = await res.json();
      this.automations.push(auto);
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
      this.showCreateForm = false;
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
    },

    async deleteAuto(auto) {
      if (!this.canEdit) return;
      if (!confirm(`Delete automation "${auto.name}"?`)) return;
      await fetch(`/api/automations/${auto.id}`, {method: 'DELETE'});
      this.automations = this.automations.filter(a => a.id !== auto.id);
    },
  };
}

document.addEventListener('alpine:init', () => {
  Alpine.data('automationsPage', automationsPage);
});

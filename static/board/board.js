function _parseBoardPageJson(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function _escapeBoardHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function _createBoard() {
  return {
    boardId: 0,
    boards: [],
    stages: [],
    taskTypes: [],
    savedFilters: [],
    showNewStage: false,
    newStageName: '',
    newStageRow: 0,
    newStagePosition: null,
    showNewTask: {},
    newTaskTitles: {},
    showModal: false,
    showSettings: false,
    showLogConfig: false,
    logConfigStage: null,
    settingsBoardName: '',
    settingsBoardColor: null,
    currentBoardRole: null,
    boardMembers: [],
    shareEmail: '',
    shareRole: 'viewer',
    shareError: '',
    boardView: 'stages',
    calendarCursor: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
    showCalendarCreate: false,
    calendarCreateDate: '',
    calendarCreateStageId: '',
    selectedTask: null,
    recurrenceExpanded: false,
    descriptionEditing: false,
    newChecklistItem: '',
    _sortables: [],
    showStageDropTargets: false,
    _stagePersistTimer: null,
    _pendingStagePlacements: null,
    _stageDragContext: null,
    _stageDragBound: false,
    _armedStageDragId: null,
    _initialized: false,
    _surfaceBound: false,
    activeStageMenuId: null,
    taskActionMenuOpen: false,
    taskColorPickerOpen: false,

    get canEditBoard() {
      return this.currentBoardRole === 'owner' || this.currentBoardRole === 'editor' || this.currentBoardRole === 'admin';
    },

    asString(value) {
      return value === null || value === undefined ? '' : String(value);
    },

    sameString(left, right) {
      return this.asString(left) === this.asString(right);
    },

    get canManageBoard() {
      return this.currentBoardRole === 'owner' || this.currentBoardRole === 'admin';
    },

    get isStagesView() {
      return this.boardView === 'stages';
    },

    get isCalendarView() {
      return this.boardView === 'calendar';
    },

    get canViewSettings() {
      return !!this.currentBoardRole;
    },

    get nextBoardView() {
      return this.boardView === 'stages' ? 'calendar' : 'stages';
    },

    get boardViewToggleTitle() {
      return this.boardView === 'stages' ? 'Switch to calendar view' : 'Switch to stage view';
    },

    get stagesLabelClass() {
      return this.boardView === 'stages' ? 'view-toggle-label-active' : 'view-toggle-label-inactive';
    },

    get calendarLabelClass() {
      return this.boardView === 'calendar' ? 'view-toggle-label-active' : 'view-toggle-label-inactive';
    },

    get boardViewTrackClass() {
      return this.boardView === 'calendar' ? 'view-toggle-track-on' : 'view-toggle-track-off';
    },

    get boardViewKnobClass() {
      return this.boardView === 'calendar' ? 'translate-x-8' : 'translate-x-1';
    },

    get selectedTaskDoneLabel() {
      return this.selectedTask?.done ? '✓ Done' : 'Mark Done';
    },

    get selectedTaskDoneButtonClass() {
      return this.selectedTask?.done
        ? 'bg-green-100 text-green-700 hover:bg-green-200'
        : 'bg-gray-100 text-gray-600 hover:bg-gray-200';
    },

    get settingsBoardColorStyle() {
      return this.colorSwatchClass(this.settingsBoardColor || '#3b82f6');
    },

    get recurrenceContainerClass() {
      return this.recurrenceExpanded ? 'p-4' : 'px-4 py-2.5';
    },

    get recurrenceHeaderClass() {
      return this.recurrenceExpanded ? 'mb-3' : '';
    },

    get recurrenceToggleLabel() {
      return this.recurrenceExpanded ? 'Hide details' : 'Show details';
    },

    get selectedTaskParentTitle() {
      return this.selectedTask?.parent_task?.title || '';
    },

    get selectedTaskChecklistSummary() {
      if (!this.selectedTask?.checklist?.length) return '';
      return `(${this.checklistProgress(this.selectedTask)})`;
    },

    get showStageDropTargetsClass() {
      return this.showStageDropTargets ? 'opacity-100' : '';
    },

    get showLogConfigFiltersEmptyState() {
      return this.savedFilters.length === 0;
    },

    get logConfigFiltersHref() {
      return `/board/${this.boardId}/filters`;
    },

    get isDefaultTaskTypeSelected() {
      return !this.selectedTask?.task_type_id;
    },

    get isUnassignedSelected() {
      return !this.selectedTask?.assignee_user_id;
    },

    get isLogConfigAllSelected() {
      return !this.logConfigStage?.filter_id;
    },

    get selectedTaskType() {
      if (!this.selectedTask || !this.selectedTask.task_type_id) return null;
      return this.taskTypes.find(t => String(t.id) === String(this.selectedTask.task_type_id)) || null;
    },

    get assignableMembers() {
      return this.boardMembers.filter(member => member.is_active);
    },

    get realStages() {
      return this.stages.filter(stage => !stage.is_log);
    },

    get topRowStages() {
      return this.stages
        .filter(stage => (Number.isInteger(stage.row) ? stage.row : 0) === 0)
        .sort((a, b) => a.position - b.position);
    },

    get stageColumns() {
      const topStages = this.stages
        .filter(stage => (Number.isInteger(stage.row) ? stage.row : 0) === 0)
        .sort((a, b) => a.position - b.position);
      const bottomStages = this.stages
        .filter(stage => (Number.isInteger(stage.row) ? stage.row : 0) === 1)
        .sort((a, b) => a.position - b.position);
      const topByPosition = new Map(topStages.map(stage => [stage.position, stage]));
      const bottomByPosition = new Map(bottomStages.map(stage => [stage.position, stage]));
      const maxPosition = Math.max(-1, ...this.stages.map(stage => Number.isInteger(stage.position) ? stage.position : 0));
      const columnCount = Math.max(topStages.length, maxPosition + 1);
      return Array.from({length: columnCount}, (_, position) => ({
        position,
        topStage: topByPosition.get(position) || null,
        bottomStage: bottomByPosition.get(position) || null,
      }));
    },

    get topAddStagePosition() {
      return this.stageColumns.length;
    },

    stageContainerClass(stage) {
      return stage?.is_log ? 'log-stage' : 'bg-gray-100';
    },

    stageHeaderClass(stage) {
      return stage?.is_log ? 'log-stage-header' : 'border-transparent';
    },

    stageTitleInputClass(stage) {
      return stage?.is_log ? 'log-stage-title' : 'text-gray-700 hover:bg-black/5 focus:bg-black/5';
    },

    stageBodyClass(stage) {
      return stage?.is_log ? 'log-stage-body' : '';
    },

    stageColumnId(stage) {
      return stage?.id || '';
    },

    stageDomId(stage) {
      return stage?.id ? `stage-${stage.id}` : '';
    },

    stageTasks(stage) {
      return stage?.tasks || [];
    },

    canSortStage(stage) {
      return !!stage && !stage.is_log;
    },

    canClearCompletedStage(stage) {
      return !!stage && !stage.is_log;
    },

    showLogSourceBadge(stage) {
      return !!stage?.is_log;
    },

    isNewTaskFormVisible(stage) {
      return !!stage && this.isNewTaskFormOpen(stage.id);
    },

    canShowNewTaskButton(stage) {
      return !!stage && !stage.is_log && this.canEditBoard;
    },

    taskCardOpacityClass(task) {
      return task?.done ? 'opacity-60' : '';
    },

    calendarDayClass(day) {
      return day?.inCurrentMonth ? 'calendar-current-month' : 'calendar-other-month';
    },

    calendarTaskId(entry) {
      return entry?.is_calendar_preview ? '' : entry?.id || '';
    },

    assigneeSelectKey() {
      const taskId = this.selectedTask?.id || 'none';
      const assignee = this.selectedTask?.assignee_user_id || 'none';
      return `assignee-${taskId}-${assignee}-${this.assignableMembers.length}`;
    },

    logConfigSelectKey() {
      const stageId = this.logConfigStage?.id || 'none';
      const filterId = this.logConfigStage?.filter_id || 'all';
      return `log-filter-${stageId}-${filterId}`;
    },

    newTaskInputId(stage) {
      return stage?.id ? `new-task-input-${stage.id}` : '';
    },

    showChecklistSummary(task) {
      return !!(task?.checklist && task.checklist.length > 0);
    },

    get calendarWeekdayLabels() {
      return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    },

    get allBoardTasks() {
      return this.realStages.flatMap(stage =>
        (stage.tasks || []).map(task => this._decorateTask({
          ...task,
          stage_id: task.stage_id || stage.id,
          stage_name: task.stage_name || stage.name,
        }))
      );
    },

    get calendarEntries() {
      return this.allBoardTasks.flatMap(task => {
        const entries = [];
        const primaryDate = this.taskCalendarDate(task);
        if (primaryDate) {
          entries.push({
            ...task,
            key: `task-${task.id}-${primaryDate}`,
            calendar_date: primaryDate,
            calendar_date_source: task.due_date ? 'due_date' : 'recurrence',
            is_calendar_preview: false,
          });
        }
        if (this.shouldShowRecurrencePreview(task)) {
          entries.push({
            ...task,
            key: `preview-${task.id}-${task.recurrence.next_run_on}`,
            calendar_date: task.recurrence.next_run_on,
            calendar_date_source: 'recurrence_preview',
            is_calendar_preview: true,
          });
        }
        return entries;
      });
    },

    get calendarMonthLabel() {
      return this.calendarCursor.toLocaleDateString(undefined, {month: 'long', year: 'numeric'});
    },

    get calendarDays() {
      const monthStart = new Date(this.calendarCursor.getFullYear(), this.calendarCursor.getMonth(), 1);
      const gridStart = new Date(monthStart);
      const startOffset = (monthStart.getDay() + 6) % 7;
      gridStart.setDate(monthStart.getDate() - startOffset);

      const todayKey = this.formatDateKey(new Date());
      const taskMap = new Map();
      for (const entry of this.calendarEntries) {
        const key = entry.calendar_date;
        if (!taskMap.has(key)) taskMap.set(key, []);
        taskMap.get(key).push(entry);
      }
      for (const entries of taskMap.values()) {
        entries.sort((a, b) => {
          if (!!a.is_calendar_preview !== !!b.is_calendar_preview) return a.is_calendar_preview ? 1 : -1;
          if (!!a.done !== !!b.done) return a.done ? 1 : -1;
          return String(a.title || '').localeCompare(String(b.title || ''));
        });
      }

      const days = [];
      for (let index = 0; index < 42; index += 1) {
        const current = new Date(gridStart);
        current.setDate(gridStart.getDate() + index);
        const key = this.formatDateKey(current);
        days.push({
          date: key,
          dayNumber: current.getDate(),
          inCurrentMonth: current.getMonth() === this.calendarCursor.getMonth(),
          isToday: key === todayKey,
          entries: taskMap.get(key) || [],
        });
      }
      return days;
    },

    async init() {
      if (this._initialized) return;
      this._initialized = true;
      this.boardId = parseInt(this._el.dataset.boardId || '0', 10);
      this.boards = _parseBoardPageJson(this._el.dataset.boards, []);
      this.settingsBoardName = _parseBoardPageJson(this._el.dataset.boardName, '');
      this.settingsBoardColor = _parseBoardPageJson(this._el.dataset.boardColor, '') || null;
      this.currentBoardRole = _parseBoardPageJson(this._el.dataset.boardRole, null);
      this.boardView = this.getRequestedBoardView();
      this.calendarCursor = this.getInitialCalendarCursor();
      this.cacheSurfaceElements();
      this.bindSurfaceEvents();
      await this.loadData();
      this.bindStageDragEvents();
      const taskId = this.getRequestedTaskId();
      if (taskId) {
        await this.openTaskById(taskId);
      }
    },

    async loadData() {
      await Promise.all([
        this.loadStages(),
        this.loadMetadata(),
        this.loadBoardMembers(),
      ]);
      this.renderBoardSurface();
    },

    async loadStages() {
      const stagesRes = await fetch('/api/stages?board_id=' + this.boardId);
      this.stages = (await stagesRes.json()).map(stage => ({
        ...stage,
        row: Number.isInteger(stage.row) ? stage.row : 0,
        tasks: (stage.tasks || []).map(task => this._decorateTask(task)),
      }));
      this.renderBoardSurface();
      requestAnimationFrame(() => {
        this.initSortable();
      });
    },

    async reloadStagesAfterDrag() {
      await new Promise(resolve => {
        requestAnimationFrame(() => {
          requestAnimationFrame(resolve);
        });
      });
      await this.loadStages();
    },

    async loadMetadata() {
      const [typesRes, filtersRes] = await Promise.all([
        fetch('/api/task-types?board_id=' + this.boardId),
        fetch('/api/filters?board_id=' + this.boardId),
      ]);
      this.taskTypes = await typesRes.json();
      this.savedFilters = await filtersRes.json();
      this.renderBoardSurface();
    },

    async loadBoardMembers() {
      const res = await fetch(`/api/boards/${this.boardId}/members`);
      if (!res.ok) return;
      const payload = await res.json();
      this.currentBoardRole = payload.current_role;
      this.boardMembers = payload.members || [];
      this.renderBoardSurface();
    },

    cacheSurfaceElements() {
      this.readonlyBannerEl = this._el.querySelector('#board-readonly-banner');
      this.viewToggleEl = this._el.querySelector('#board-view-toggle');
      this.calendarToolbarEl = this._el.querySelector('#board-calendar-toolbar');
      this.stagesViewEl = this._el.querySelector('#board-stages-view');
      this.calendarViewEl = this._el.querySelector('#board-calendar-view');
      this.calendarCreateModalEl = this._el.querySelector('#board-calendar-create-modal');
      this.settingsModalEl = this._el.querySelector('#board-settings-modal');
      this.taskModalEl = this._el.querySelector('#board-task-modal');
      this.logConfigModalEl = this._el.querySelector('#board-log-config-modal');
    },

    bindSurfaceEvents() {
      if (this._surfaceBound) return;
      this._surfaceBound = true;
      const settingsButton = document.getElementById('board-settings-button');
      settingsButton?.addEventListener('click', () => {
        this.showSettings = true;
        this.renderSettingsModal();
      });
      this._el.addEventListener('click', event => this.handleSurfaceClick(event));
      this._el.addEventListener('change', event => this.handleSurfaceChange(event));
      this._el.addEventListener('dblclick', event => this.handleSurfaceDoubleClick(event));
      this._el.addEventListener('input', event => this.handleSurfaceInput(event));
      this._el.addEventListener('keydown', event => this.handleSurfaceKeydown(event));
      this._el.addEventListener('blur', event => this.handleSurfaceBlur(event), true);
      document.addEventListener('click', event => {
        // Stage menu outside click
        if (this.activeStageMenuId) {
          if (!event.target.closest('[data-role="stage-menu"]') && !event.target.closest('[data-action="toggle-stage-menu"]')) {
            this.closeStageMenu();
            this.renderBoardSurface();
          }
        }
        // Task action menu outside click
        if (this.taskActionMenuOpen) {
          if (!event.target.closest('[data-role="modal-action-menu-anchor"]')) {
            this.taskActionMenuOpen = false;
            this.renderTaskModal();
          }
        }
        // Task color picker outside click
        if (this.taskColorPickerOpen) {
          if (!event.target.closest('[data-role="modal-color-picker-anchor"]')) {
            this.taskColorPickerOpen = false;
            this.renderTaskModal();
          }
        }
      });
    },

    handleSurfaceClick(event) {
      const actionTarget = event.target.closest('[data-action]');
      if (!actionTarget) return;
      // If the click landed inside a data-stop-propagation container that is
      // a descendant of the action target, the backdrop click should be ignored.
      const stopEl = event.target.closest('[data-stop-propagation="true"]');
      if (stopEl && actionTarget.contains(stopEl)) return;
      const action = actionTarget.dataset.action;
      const stageId = parseInt(actionTarget.dataset.stageId || '0', 10);
      const taskId = parseInt(actionTarget.dataset.openTaskId || actionTarget.dataset.taskId || '0', 10);
      const row = parseInt(actionTarget.dataset.stageRow || '0', 10);
      const position = parseInt(actionTarget.dataset.stagePosition || '0', 10);

      if (action === 'toggle-board-view') {
        this.setBoardView(this.nextBoardView);
        return;
      }
      if (action === 'calendar-prev') {
        this.changeCalendarMonth(-1);
        return;
      }
      if (action === 'calendar-next') {
        this.changeCalendarMonth(1);
        return;
      }
      if (action === 'calendar-today') {
        this.jumpCalendarToToday();
        return;
      }
      if (action === 'close-calendar-create') {
        this.closeCalendarCreate();
        this.renderBoardSurface();
        return;
      }
      if (action === 'submit-calendar-create') {
        this.createTaskFromCalendar();
        return;
      }
      if (action === 'close-settings') {
        this.showSettings = false;
        this.renderBoardSurface();
        return;
      }
      if (action === 'select-board-color') {
        if (!this.canManageBoard) return;
        this.settingsBoardColor = actionTarget.dataset.color || null;
        this.renderBoardSurface();
        return;
      }
      if (action === 'clear-board-color') {
        if (!this.canManageBoard) return;
        this.settingsBoardColor = null;
        this.renderBoardSurface();
        return;
      }
      if (action === 'share-board') {
        this.addBoardMember();
        return;
      }
      if (action === 'remove-board-member') {
        const member = this.boardMembers.find(entry => String(entry.user_id) === String(actionTarget.dataset.userId || ''));
        if (member) this.removeBoardMember(member);
        return;
      }
      if (action === 'save-settings') {
        this.saveSettings();
        return;
      }
      if (action === 'open-new-stage') {
        this.openNewStageForm(row, position);
        return;
      }
      if (action === 'cancel-new-stage') {
        this.cancelNewStage();
        this.renderBoardSurface();
        return;
      }
      if (action === 'create-stage') {
        this.createStage(row, position);
        return;
      }
      if (action === 'toggle-stage-menu') {
        this.toggleStageMenu(stageId);
        this.renderBoardSurface();
        return;
      }
      if (action === 'open-log-config') {
        const stage = this.stages.find(entry => entry.id === stageId);
        if (stage) this.openLogConfig(stage);
        this.closeStageMenu();
        this.renderBoardSurface();
        return;
      }
      if (action === 'sort-stage') {
        const stage = this.stages.find(entry => entry.id === stageId);
        if (stage) this.sortStageByDueDate(stage);
        this.closeStageMenu();
        this.renderBoardSurface();
        return;
      }
      if (action === 'clear-completed-stage') {
        const stage = this.stages.find(entry => entry.id === stageId);
        if (stage) this.clearCompletedStage(stage);
        this.closeStageMenu();
        this.renderBoardSurface();
        return;
      }
      if (action === 'delete-stage') {
        this.deleteStage(stageId);
        this.closeStageMenu();
        this.renderBoardSurface();
        return;
      }
      if (action === 'close-task-modal') {
        this.closeModal();
        return;
      }
      if (action === 'modal-toggle-done') {
        this.toggleDone();
        return;
      }
      if (action === 'modal-toggle-action-menu') {
        this.toggleTaskActionMenu();
        return;
      }
      if (action === 'modal-enable-recurrence-menu') {
        this.enableRecurrence();
        this.closeTaskActionMenu();
        return;
      }
      if (action === 'modal-disable-recurrence-menu') {
        this.disableRecurrence();
        this.closeTaskActionMenu();
        return;
      }
      if (action === 'modal-delete-task') {
        this.deleteTask();
        this.closeTaskActionMenu();
        return;
      }
      if (action === 'modal-toggle-color-picker') {
        this.toggleTaskColorPicker();
        return;
      }
      if (action === 'modal-pick-color') {
        const color = actionTarget.dataset.color || null;
        if (this.selectedTask) this.selectedTask.color = color;
        this.updateTaskField('color', color);
        this.closeTaskColorPicker();
        return;
      }
      if (action === 'modal-clear-color') {
        if (this.selectedTask) this.selectedTask.color = null;
        this.updateTaskField('color', null);
        this.closeTaskColorPicker();
        return;
      }
      if (action === 'modal-open-parent-task') {
        this.openParentTask();
        return;
      }
      if (action === 'modal-toggle-recurrence-expanded') {
        this.recurrenceExpanded = !this.recurrenceExpanded;
        this.renderTaskModal();
        return;
      }
      if (action === 'modal-disable-recurrence') {
        this.disableRecurrence();
        return;
      }
      if (action === 'modal-save-recurrence') {
        this.saveRecurrence();
        return;
      }
      if (action === 'modal-update-description-visibility') {
        this.updateDescriptionVisibility(actionTarget.dataset.value);
        return;
      }
      if (action === 'modal-edit-description') {
        if (!this.canEditBoard) return;
        this.descriptionEditing = true;
        this.renderTaskModal();
        return;
      }
      if (action === 'modal-update-checklist-visibility') {
        this.updateChecklistVisibility(actionTarget.dataset.value);
        return;
      }
      if (action === 'modal-toggle-checklist-item') {
        const itemId = parseInt(actionTarget.dataset.itemId || '0', 10);
        const item = this.selectedTask?.checklist?.find(i => i.id === itemId);
        if (item) this.toggleChecklistItem(item);
        return;
      }
      if (action === 'modal-open-spawned-task') {
        const spawnedId = parseInt(actionTarget.dataset.taskId || '0', 10);
        if (spawnedId) this.openSpawnedTask(spawnedId);
        return;
      }
      if (action === 'modal-edit-checklist-item') {
        const itemId = parseInt(actionTarget.dataset.itemId || '0', 10);
        const item = this.selectedTask?.checklist?.find(i => i.id === itemId);
        if (item) { this.startChecklistItemEdit(item); this.renderTaskModal(); }
        return;
      }
      if (action === 'modal-delete-checklist-item') {
        const itemId = parseInt(actionTarget.dataset.itemId || '0', 10);
        const item = this.selectedTask?.checklist?.find(i => i.id === itemId);
        if (item) this.deleteChecklistItem(item);
        return;
      }
      if (action === 'modal-add-checklist-item') {
        this.addChecklistItem();
        return;
      }
      if (action === 'close-log-config') {
        this.closeLogConfig();
        return;
      }
      if (action === 'save-log-config') {
        this.saveLogConfig();
        return;
      }
      if (action === 'open-task') {
        const task = this.allBoardTasks.find(entry => entry.id === taskId);
        if (task) this.openTask(task);
        return;
      }
      if (action === 'toggle-task-done') {
        event.stopPropagation();
        const task = this.allBoardTasks.find(entry => entry.id === taskId);
        if (task) this.toggleTaskDoneFromCard(task);
        return;
      }
      if (action === 'open-new-task-form') {
        this.openNewTaskForm(stageId);
        return;
      }
      if (action === 'close-new-task-form') {
        this.closeNewTaskForm(stageId);
        this.renderBoardSurface();
        return;
      }
      if (action === 'create-task') {
        this.createTask(stageId);
      }
    },

    handleSurfaceDoubleClick(event) {
      const dayEl = event.target.closest('[data-calendar-day]');
      if (!dayEl) return;
      const day = this.calendarDays.find(entry => entry.date === dayEl.dataset.calendarDate);
      if (day) this.openCalendarCreate(day, event);
    },

    handleSurfaceInput(event) {
      const field = event.target.dataset.field;
      const stageId = parseInt(event.target.dataset.stageId || '0', 10);
      if (field === 'new-stage-name') {
        this.newStageName = event.target.value;
        return;
      }
      if (field === 'stage-name') {
        const stage = this.stages.find(entry => entry.id === stageId);
        if (stage) stage.name = event.target.value;
        return;
      }
      if (field === 'new-task-title') {
        this.updateNewTaskTitle(stageId, event.target.value);
        return;
      }
      if (field === 'calendar-create-stage-id') {
        this.calendarCreateStageId = event.target.value;
        return;
      }
      if (field === 'settings-board-name') {
        this.settingsBoardName = event.target.value;
        return;
      }
      if (field === 'share-email') {
        this.shareEmail = event.target.value;
        return;
      }
      if (field === 'share-role') {
        this.shareRole = event.target.value;
        return;
      }
      if (field === 'modal-new-checklist-item') {
        this.newChecklistItem = event.target.value;
        return;
      }
      if (field === 'modal-checklist-item-edit') {
        const itemId = parseInt(event.target.dataset.itemId || '0', 10);
        const item = this.selectedTask?.checklist?.find(i => i.id === itemId);
        if (item) item._draft_title = event.target.value;
        return;
      }
      if (field === 'modal-description') {
        if (this.selectedTask) this.selectedTask.description = event.target.value;
        return;
      }
    },

    handleSurfaceChange(event) {
      const field = event.target.dataset.field;
      if (field === 'board-member-role') {
        const member = this.boardMembers.find(entry => String(entry.user_id) === String(event.target.dataset.userId || ''));
        if (member) this.updateBoardMemberRole(member, event.target.value);
        return;
      }
      if (field === 'modal-assignee') {
        if (this.selectedTask) this.selectedTask.assignee_user_id = event.target.value;
        this.updateAssignee();
        return;
      }
      if (field === 'modal-due-date') {
        if (this.selectedTask) this.selectedTask.due_date = event.target.value;
        this.updateTaskField('due_date', event.target.value || null);
        return;
      }
      if (field === 'modal-task-type') {
        if (this.selectedTask) this.selectedTask.task_type_id = event.target.value;
        this.updateTaskType();
        this.closeTaskActionMenu();
        return;
      }
      if (field === 'modal-stage') {
        if (this.selectedTask) this.selectedTask.stage_id = event.target.value;
        this.moveTask();
        this.closeTaskActionMenu();
        return;
      }
      if (field === 'modal-recurrence-mode') {
        if (this.selectedTask?.recurrence) this.selectedTask.recurrence.mode = event.target.value;
        this.renderTaskModal();
        return;
      }
      if (field === 'modal-recurrence-frequency') {
        if (this.selectedTask?.recurrence) this.selectedTask.recurrence.frequency = event.target.value;
        this.renderTaskModal();
        return;
      }
      if (field === 'modal-recurrence-interval') {
        if (this.selectedTask?.recurrence) this.selectedTask.recurrence.interval = parseInt(event.target.value, 10) || 1;
        this.renderTaskModal();
        return;
      }
      if (field === 'modal-recurrence-next-run-on') {
        if (this.selectedTask?.recurrence) this.selectedTask.recurrence.next_run_on = event.target.value;
        this.renderTaskModal();
        return;
      }
      if (field === 'modal-recurrence-spawn-stage') {
        if (this.selectedTask?.recurrence) this.selectedTask.recurrence.spawn_stage_id = event.target.value;
        this.renderTaskModal();
        return;
      }
      if (field === 'modal-custom-field') {
        const fieldId = parseInt(event.target.dataset.fieldId || '0', 10);
        if (fieldId) this.updateCustomField(fieldId, event.target.value);
        return;
      }
      if (field === 'log-config-is-log') {
        if (this.logConfigStage) this.logConfigStage.is_log = event.target.checked;
        this.renderLogConfigModal();
        return;
      }
      if (field === 'log-config-filter-id') {
        if (this.logConfigStage) this.logConfigStage.filter_id = event.target.value;
        return;
      }
    },

    handleSurfaceKeydown(event) {
      const field = event.target.dataset.field;
      const stageId = parseInt(event.target.dataset.stageId || '0', 10);
      const row = parseInt(event.target.dataset.stageRow || '0', 10);
      const position = parseInt(event.target.dataset.stagePosition || '0', 10);
      if (field === 'new-stage-name') {
        if (event.key === 'Enter') {
          this.createStage(row, position);
        } else if (event.key === 'Escape') {
          this.cancelNewStage();
          this.renderBoardSurface();
        }
        return;
      }
      if (field === 'stage-name' && event.key === 'Enter') {
        event.target.blur();
        return;
      }
      if (field === 'new-task-title') {
        if (event.key === 'Enter') {
          this.createTask(stageId);
        } else if (event.key === 'Escape') {
          this.closeNewTaskForm(stageId);
          this.renderBoardSurface();
        }
        return;
      }
      if (field === 'settings-board-name' && event.key === 'Enter') {
        this.saveSettings();
        return;
      }
      if (field === 'share-email' && event.key === 'Enter') {
        this.addBoardMember();
        return;
      }
      if (field === 'modal-title' && event.key === 'Enter') {
        event.target.blur();
        return;
      }
      if (field === 'modal-new-checklist-item') {
        if (event.key === 'Enter') {
          this.addChecklistItem();
        } else if (event.key === 'Escape') {
          this.newChecklistItem = '';
          this.renderTaskModal();
        }
        return;
      }
      if (field === 'modal-checklist-item-edit') {
        const itemId = parseInt(event.target.dataset.itemId || '0', 10);
        const item = this.selectedTask?.checklist?.find(i => i.id === itemId);
        if (!item) return;
        if (event.key === 'Enter') {
          event.preventDefault();
          this.saveChecklistItemTitle(item).then(() => this.renderTaskModal());
        } else if (event.key === 'Escape') {
          event.preventDefault();
          this.cancelChecklistItemEdit(item);
          this.renderTaskModal();
        }
        return;
      }
      if (field === 'modal-description') {
        if (event.key === 'Escape') {
          const value = event.target.value;
          if (this.selectedTask) this.selectedTask.description = value;
          this.descriptionEditing = false;
          this.renderTaskModal();
          this.updateTaskField('description', value);
        }
        return;
      }
      if (this.showModal && event.key === 'Escape') {
        this.closeModal();
        return;
      }
      if (this.showLogConfig && event.key === 'Escape') {
        this.closeLogConfig();
        return;
      }
      if (this.showCalendarCreate && event.key === 'Escape') {
        this.closeCalendarCreate();
        this.renderBoardSurface();
        return;
      }
      if (this.showSettings && event.key === 'Escape') {
        this.showSettings = false;
        this.renderBoardSurface();
      }
    },

    handleSurfaceBlur(event) {
      const field = event.target.dataset.field;
      const stageId = parseInt(event.target.dataset.stageId || '0', 10);
      if (field === 'stage-name') {
        const stage = this.stages.find(entry => entry.id === stageId);
        if (stage) this.saveStageName(stage);
        return;
      }
      if (field === 'modal-title') {
        if (this.selectedTask) this.selectedTask.title = event.target.value;
        this.updateTaskField('title', event.target.value);
        return;
      }
      if (field === 'modal-description') {
        const value = event.target.value;
        if (this.selectedTask) this.selectedTask.description = value;
        this.descriptionEditing = false;
        this.renderTaskModal();
        this.updateTaskField('description', value);
        return;
      }
      if (field === 'modal-checklist-item-edit') {
        const itemId = parseInt(event.target.dataset.itemId || '0', 10);
        const item = this.selectedTask?.checklist?.find(i => i.id === itemId);
        if (item) this.saveChecklistItemTitle(item).then(() => this.renderTaskModal());
        return;
      }
    },

    renderBoardSurface() {
      if (!this.readonlyBannerEl) return;
      this.renderReadonlyBanner();
      this.renderViewToggle();
      this.renderCalendarToolbar();
      this.renderStagesView();
      this.renderCalendarView();
      this.renderCalendarCreateModal();
      this.renderSettingsModal();
      this.renderTaskModal();
      this.renderLogConfigModal();
      this.updateStageDropTargetVisibility();
    },

    updateStageDropTargetVisibility() {
      this._el.querySelectorAll('[data-stage-drop-target]').forEach(element => {
        element.classList.toggle('opacity-100', this.showStageDropTargets);
      });
    },

    renderReadonlyBanner() {
      this.readonlyBannerEl.classList.toggle('hidden', this.canEditBoard);
      this.readonlyBannerEl.innerHTML = this.canEditBoard ? '' : `
        <div class="bg-white/85 text-slate-700 text-sm rounded-xl px-4 py-3 shadow">
          Read-only access. Viewers can browse this hub but cannot change objectives, stages, or settings.
        </div>
      `;
    },

    renderViewToggle() {
      this.viewToggleEl.innerHTML = `
        <button
          type="button"
          data-action="toggle-board-view"
          class="view-toggle-shell flex items-center gap-3 rounded-2xl border px-3 py-2 shadow-lg backdrop-blur-sm transition-colors"
          aria-pressed="${this.isCalendarView ? 'true' : 'false'}"
          title="${_escapeBoardHtml(this.boardViewToggleTitle)}"
        >
          <span class="text-xs font-semibold uppercase tracking-[0.18em] transition-colors ${this.stagesLabelClass}">Stages</span>
          <span class="relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${this.boardViewTrackClass}">
            <span class="view-toggle-knob inline-block h-5 w-5 transform rounded-full shadow-sm transition-transform duration-200 ${this.boardViewKnobClass}"></span>
          </span>
          <span class="text-xs font-semibold uppercase tracking-[0.18em] transition-colors ${this.calendarLabelClass}">Calendar</span>
        </button>
      `;
    },

    renderCalendarToolbar() {
      this.calendarToolbarEl.classList.toggle('hidden', !this.isCalendarView);
      this.calendarToolbarEl.innerHTML = this.isCalendarView ? `
        <div class="flex items-center gap-2 rounded-2xl bg-white/80 px-2 py-2 shadow-lg backdrop-blur-sm">
          <button type="button" data-action="calendar-prev" class="px-3 py-2 rounded-xl bg-white/85 text-slate-600 hover:bg-white shadow-sm transition-colors" aria-label="Previous month">←</button>
          <div class="px-4 py-2 rounded-xl bg-white/90 text-sm font-semibold text-slate-700 shadow-sm min-w-[12rem] text-center">${_escapeBoardHtml(this.calendarMonthLabel)}</div>
          <button type="button" data-action="calendar-next" class="px-3 py-2 rounded-xl bg-white/85 text-slate-600 hover:bg-white shadow-sm transition-colors" aria-label="Next month">→</button>
          <button type="button" data-action="calendar-today" class="px-3 py-2 rounded-xl bg-white/85 text-sm text-slate-600 hover:bg-white shadow-sm transition-colors">Today</button>
        </div>
      ` : '';
    },

    renderStagesView() {
      this.stagesViewEl.classList.toggle('hidden', !this.isStagesView);
      if (!this.isStagesView) {
        this.stagesViewEl.innerHTML = '';
        return;
      }
      const columns = this.stageColumns.map(column => this.renderStageColumn(column)).join('');
      const addColumn = this.canEditBoard ? this.renderTrailingStageColumn() : '';
      this.stagesViewEl.innerHTML = `
        <div id="stages-container" class="min-w-max space-y-4">
          <div class="flex items-start gap-3">
            ${columns}
            ${addColumn}
          </div>
        </div>
      `;
    },

    renderStageColumn(column) {
      return `
        <div class="w-72 flex-shrink-0 space-y-3">
          ${this.renderStageSlot(column.position, 0, column.topStage, 'group/add-top')}
          ${this.renderStageSlot(column.position, 1, column.bottomStage, 'group/add-bottom', !!column.topStage)}
        </div>
      `;
    },

    renderStageSlot(position, row, stage, groupClass, requireAnchor = false) {
      const canInsert = this.canEditBoard && (!requireAnchor || row === 0 || this.stageColumns.some(column => column.position === position && column.topStage));
      const showAddButton = !stage && canInsert && (!this.showNewStage || this.newStageRow !== row || this.newStagePosition !== position);
      const showAddForm = !stage && this.showNewStage && this.newStageRow === row && this.newStagePosition === position;
      return `
        <div class="${groupClass}">
          <div class="min-h-[48px] rounded-xl" data-stage-slot data-stage-row="${row}" data-stage-slot-position="${position}">
            ${stage ? this.renderStage(stage) : ''}
            ${showAddButton ? `
              <button
                data-stage-drop-target="true"
                data-action="open-new-stage"
                data-stage-row="${row}"
                data-stage-position="${position}"
                class="w-full rounded-xl border border-dashed border-white/30 bg-white/10 px-3 py-3 text-left text-sm font-medium text-white/80 opacity-0 transition-all duration-150 hover:bg-white/15 ${groupClass === 'group/add-top' ? 'group-hover/add-top:opacity-100 group-focus-within/add-top:opacity-100' : 'group-hover/add-bottom:opacity-100 group-focus-within/add-bottom:opacity-100'} ${this.showStageDropTargetsClass}"
              >+ Add stage here</button>
            ` : ''}
            ${showAddForm ? this.renderNewStageForm(row, position) : ''}
          </div>
        </div>
      `;
    },

    renderTrailingStageColumn() {
      const position = this.topAddStagePosition;
      const showAddButton = !this.showNewStage || this.newStageRow !== 0 || this.newStagePosition !== position;
      const showAddForm = this.showNewStage && this.newStageRow === 0 && this.newStagePosition === position;
      return `
        <div class="w-72 flex-shrink-0 group/add-top">
          <div class="min-h-[48px] rounded-xl" data-stage-slot data-stage-row="0" data-stage-slot-position="${position}">
            ${showAddButton ? `
              <button
                data-stage-drop-target="true"
                data-action="open-new-stage"
                data-stage-row="0"
                data-stage-position="${position}"
                class="w-full rounded-xl border border-dashed border-white/30 bg-white/10 px-3 py-3 text-left text-sm font-medium text-white/80 opacity-0 transition-all duration-150 hover:bg-white/15 group-hover/add-top:opacity-100 group-focus-within/add-top:opacity-100 ${this.showStageDropTargetsClass}"
              >+ Add stage here</button>
            ` : ''}
            ${showAddForm ? this.renderNewStageForm(0, position) : ''}
          </div>
        </div>
      `;
    },

    renderNewStageForm(row, position) {
      return `
        <div class="bg-gray-100 rounded-xl p-3 shadow">
          <input
            data-field="new-stage-name"
            data-stage-row="${row}"
            data-stage-position="${position}"
            value="${_escapeBoardHtml(this.newStageName)}"
            placeholder="Stage title..."
            class="w-full border rounded-lg px-2 py-1.5 text-sm mb-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
          <div class="flex gap-1.5">
            <button data-action="create-stage" data-stage-row="${row}" data-stage-position="${position}" class="bg-blue-500 hover:bg-blue-600 text-white text-sm px-3 py-1 rounded-lg transition-colors">Add stage</button>
            <button data-action="cancel-new-stage" class="text-gray-600 hover:text-gray-800 text-sm px-2 py-1">✕</button>
          </div>
        </div>
      `;
    },

    renderStage(stage) {
      const stageTasks = this.stageTasks(stage).map(task => this.renderTaskCard(task, stage)).join('');
      return `
        <div class="board-stage rounded-xl shadow w-72 flex-shrink-0 flex flex-col overflow-visible ${this.stageContainerClass(stage)}" data-stage-column-id="${stage.id}">
          <div class="flex items-center justify-between px-3 pt-3 pb-2 border-b ${this.stageHeaderClass(stage)}" data-stage-drag-handle>
            <div class="min-w-0 flex-1">
              <input
                data-field="stage-name"
                data-stage-id="${stage.id}"
                value="${_escapeBoardHtml(stage.name)}"
                ${this.canEditBoard ? '' : 'disabled'}
                class="stage-title-input font-medium bg-transparent w-full rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-400 text-sm ${this.stageTitleInputClass(stage)}"
              >
              ${stage.is_log ? `
                <div class="mt-1 px-1 space-y-1">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <span class="log-stage-badge text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full font-semibold">Filter Log</span>
                    <span class="log-stage-summary text-[10px] font-medium">⌕ Read-only view</span>
                  </div>
                  <div class="log-stage-summary text-[11px] leading-snug">${_escapeBoardHtml(this.logStageSummary(stage))}</div>
                </div>
              ` : ''}
            </div>
            ${this.canEditBoard ? this.renderStageMenu(stage) : ''}
          </div>
          <div class="board-stage-body px-2 pt-2 pb-1 space-y-2 min-h-[8px] ${this.stageBodyClass(stage)}" id="${this.stageDomId(stage)}" data-stage-id="${stage.id}">
            ${stageTasks}
            <div class="hidden" aria-hidden="true" data-stage-sortable-sentinel><span></span></div>
          </div>
          ${this.canShowNewTaskButton(stage) ? this.renderNewTaskSection(stage) : ''}
        </div>
      `;
    },

    renderStageMenu(stage) {
      return `
        <div class="relative ml-2 flex-shrink-0" data-role="stage-menu">
          <button
            data-action="toggle-stage-menu"
            data-stage-id="${stage.id}"
            class="text-gray-400 hover:text-gray-700 px-2 py-1 rounded hover:bg-white transition-colors text-lg leading-none"
            title="Stage actions"
          >☰</button>
          ${this.isStageMenuOpen(stage.id) ? `
            <div class="absolute top-full right-0 mt-1 bg-white text-gray-800 shadow-xl rounded-xl py-1 min-w-[170px] z-20">
              <button data-action="open-log-config" data-stage-id="${stage.id}" class="block w-full text-left text-xs text-gray-600 hover:text-sky-600 px-3 py-2 hover:bg-gray-100 transition-colors">Configure log</button>
              ${this.canSortStage(stage) ? `<button data-action="sort-stage" data-stage-id="${stage.id}" class="block w-full text-left text-xs text-gray-600 hover:text-blue-600 px-3 py-2 hover:bg-gray-100 transition-colors" title="Sort dated objectives by due date">Sort by due date</button>` : ''}
              ${this.canClearCompletedStage(stage) ? `<button data-action="clear-completed-stage" data-stage-id="${stage.id}" class="block w-full text-left text-xs text-gray-600 hover:text-amber-600 px-3 py-2 hover:bg-gray-100 transition-colors" title="Clear completed objectives">Clear completed</button>` : ''}
              <button data-action="delete-stage" data-stage-id="${stage.id}" class="block w-full text-left text-xs text-gray-600 hover:text-red-600 px-3 py-2 hover:bg-gray-100 transition-colors" title="Delete stage">Delete stage</button>
            </div>
          ` : ''}
        </div>
      `;
    },

    renderTaskCard(task, stage) {
      const taskTypeBadge = task.task_type ? `<span class="text-xs px-2 py-0.5 rounded font-medium ${this.taskTypeBadgeClass(task.task_type)}">${_escapeBoardHtml(task.task_type.name)}</span>` : '';
      const parentBadge = task.parent_task ? `<span class="text-xs px-2 py-0.5 rounded font-medium bg-violet-100 text-violet-700">${_escapeBoardHtml(task.parent_task.title)}</span>` : '';
      const assigneeBadge = task.assignee ? `<span class="text-xs px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-700">${_escapeBoardHtml(this.assigneeChipLabel(task))}</span>` : '';
      const recurrenceBadge = task.recurrence ? '<span class="text-xs px-2 py-0.5 rounded font-medium bg-blue-100 text-blue-700">↻ Recurring</span>' : '';
      const dueDateBadge = this.hasDueDate(task.due_date) ? `<span class="text-xs px-2 py-0.5 rounded font-medium ${this.dueDateClass(task.due_date)}">${_escapeBoardHtml(this.dueDateLabel(task.due_date))}</span>` : '';
      const checklistBadge = this.showChecklistSummary(task) ? `<span class="text-xs text-gray-400 flex items-center gap-0.5"><span>☑</span><span>${_escapeBoardHtml(this.checklistProgress(task))}</span></span>` : '';
      const logSourceBadge = this.showLogSourceBadge(stage) ? `<span class="text-xs px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-600">${_escapeBoardHtml(this.logSourceLabel(task))}</span>` : '';
      const description = this.shouldShowDescriptionOnCard(task) ? `<div class="mt-1.5 text-xs text-gray-500 leading-snug prose prose-sm max-w-none">${renderMarkdown(task.description)}</div>` : '';
      const checklist = this.shouldShowChecklistOnCard(task) ? `
        <div class="mt-2 space-y-1">
          ${(task.checklist || []).map(item => `
            <div class="flex items-start gap-1.5 text-xs text-gray-500">
              <span class="mt-0.5 flex-shrink-0 ${this.checklistItemIconClass(item)}">${_escapeBoardHtml(this.checklistItemIcon(item))}</span>
              <span class="leading-snug ${this.checklistItemTitleClass(item)}">${_escapeBoardHtml(item.title)}</span>
            </div>
          `).join('')}
        </div>
      ` : '';
      const customFields = this.shouldShowTaskCardCustomFields(task) ? `
        <div class="task-chip-row mt-1.5 pt-1.5 border-t border-gray-200/70">
          ${this.taskCardCustomFields(task).map(field => `
            <span class="text-xs px-2 py-0.5 rounded font-medium ${this.taskChipClass(field, this.taskCardCustomFieldValue(task, field))}">
              ${_escapeBoardHtml(this.taskCardCustomFieldLabel(task, field))}
            </span>
          `).join('')}
        </div>
      ` : '';
      return `
        <div class="board-task-card bg-white rounded-lg p-2.5 shadow-sm cursor-pointer hover:shadow-md transition-shadow ${this.taskCardOpacityClass(task)} ${this.taskCardClass(task)}" data-action="open-task" data-task-id="${task.id}">
          <div class="group/title flex items-start gap-0">
            ${this.canEditBoard ? `
              <button
                data-action="toggle-task-done"
                data-task-id="${task.id}"
                class="mt-0.5 h-4 overflow-hidden rounded border flex items-center justify-center flex-shrink-0 transition-all duration-150 group-hover/title:w-4 group-hover/title:mr-2 group-hover/title:opacity-100 group-focus-within/title:w-4 group-focus-within/title:mr-2 group-focus-within/title:opacity-100 ${this.taskDoneToggleClass(task)}"
                title="${_escapeBoardHtml(this.taskDoneToggleTitle(task))}"
              ><span class="text-[11px] leading-none">✓</span></button>
            ` : ''}
            <div class="min-w-0 flex-1">
              <div class="flex items-start gap-1.5">
                <span class="text-sm text-gray-800 leading-snug block min-w-0 flex-1 ${this.taskTitleClass(task)}">${_escapeBoardHtml(task.title)}</span>
                ${this.hasDescription(task) ? '<span class="mt-0.5 flex-shrink-0 text-[11px] text-gray-400" title="Has description" aria-label="Has description">≡</span>' : ''}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-1.5 mt-1.5 flex-wrap">${taskTypeBadge}${parentBadge}${assigneeBadge}${recurrenceBadge}${dueDateBadge}${checklistBadge}${logSourceBadge}</div>
          ${description}
          ${checklist}
          ${customFields}
        </div>
      `;
    },

    renderNewTaskSection(stage) {
      const formOpen = this.isNewTaskFormOpen(stage.id);
      return `
        <div class="px-2 pb-2 pt-1">
          ${!formOpen ? `
            <button data-action="open-new-task-form" data-stage-id="${stage.id}" class="text-gray-500 hover:text-gray-800 text-sm w-full text-left px-1 py-1 rounded hover:bg-gray-200 transition-colors">+ Add an objective</button>
          ` : `
            <input
              data-field="new-task-title"
              data-stage-id="${stage.id}"
              value="${_escapeBoardHtml(this.newTaskTitles[stage.id] || '')}"
              placeholder="Objective title..."
              class="w-full border rounded-lg px-2 py-1.5 text-sm mb-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
            <div class="flex gap-1.5">
              <button data-action="create-task" data-stage-id="${stage.id}" class="bg-blue-500 hover:bg-blue-600 text-white text-sm px-3 py-1 rounded-lg transition-colors">Add</button>
              <button data-action="close-new-task-form" data-stage-id="${stage.id}" class="text-gray-500 hover:text-gray-700 text-sm px-2 py-1">✕</button>
            </div>
          `}
        </div>
      `;
    },

    renderCalendarView() {
      this.calendarViewEl.classList.toggle('hidden', !this.isCalendarView);
      if (!this.isCalendarView) {
        this.calendarViewEl.innerHTML = '';
        return;
      }
      this.calendarViewEl.innerHTML = `
        <div class="mx-auto max-w-7xl rounded-2xl bg-white/85 shadow-lg overflow-hidden">
          <div class="calendar-header-strip grid grid-cols-7 border-b">
            ${this.calendarWeekdayLabels.map(weekday => `<div class="px-3 py-2 text-xs font-semibold uppercase tracking-wide calendar-weekday-label">${weekday}</div>`).join('')}
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-7">
            ${this.calendarDays.map(day => this.renderCalendarDay(day)).join('')}
          </div>
        </div>
      `;
    },

    renderCalendarCreateModal() {
      if (!this.calendarCreateModalEl) return;
      if (!this.showCalendarCreate) {
        this.calendarCreateModalEl.innerHTML = '';
        return;
      }
      this.calendarCreateModalEl.innerHTML = `
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" data-action="close-calendar-create">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md" data-stop-propagation="true">
            <div class="p-6">
              <div class="flex items-center justify-between mb-5">
                <div>
                  <h2 class="text-lg font-bold text-gray-800">New Objective</h2>
                  <p class="text-sm text-gray-400 mt-1">Create for ${_escapeBoardHtml(this.formatCalendarCreateDate(this.calendarCreateDate))}</p>
                </div>
                <button data-action="close-calendar-create" class="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
              </div>
              <div class="mb-6">
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Stage</label>
                <select data-field="calendar-create-stage-id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                  ${this.realStages.map(stage => `<option value="${stage.id}"${String(stage.id) === String(this.calendarCreateStageId) ? ' selected' : ''}>${_escapeBoardHtml(stage.name)}</option>`).join('')}
                </select>
              </div>
              <div class="flex justify-end gap-2 border-t pt-4">
                <button data-action="close-calendar-create" class="text-gray-500 hover:text-gray-700 px-4 py-2 text-sm">Cancel</button>
                <button data-action="submit-calendar-create" class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Continue</button>
              </div>
            </div>
          </div>
        </div>
      `;
    },

    renderSettingsModal() {
      if (!this.settingsModalEl) return;
      if (!this.showSettings) {
        this.settingsModalEl.innerHTML = '';
        return;
      }
      const colorButtons = PRESET_COLORS.map(color => `
        <button
          data-action="select-board-color"
          data-color="${color}"
          ${this.canManageBoard ? '' : 'disabled'}
          class="w-8 h-8 rounded-full hover:scale-110 transition-transform border-2 border-black/10 ${this.settingsColorSwatchClass(color)}"
        ></button>
      `).join('');
      const shareSection = this.canManageBoard ? `
        <div class="mb-6 border-t pt-5">
          <div class="flex items-center justify-between mb-3">
            <div>
              <h3 class="text-sm font-semibold text-gray-800">Sharing</h3>
              <p class="text-xs text-gray-400 mt-0.5">Share this hub with other registered users.</p>
            </div>
          </div>
          <div class="flex gap-2 mb-4">
            <input
              data-field="share-email"
              value="${_escapeBoardHtml(this.shareEmail)}"
              placeholder="user@example.com"
              class="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
            <select data-field="share-role" class="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
              <option value="viewer"${this.shareRole === 'viewer' ? ' selected' : ''}>Viewer</option>
              <option value="editor"${this.shareRole === 'editor' ? ' selected' : ''}>Editor</option>
              <option value="owner"${this.shareRole === 'owner' ? ' selected' : ''}>Owner</option>
            </select>
            <button data-action="share-board" class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Share</button>
          </div>
          ${this.shareError ? `<p class="text-sm text-red-500 mb-3">${_escapeBoardHtml(this.shareError)}</p>` : ''}
          <div class="space-y-2">
            ${this.boardMembers.map(member => `
              <div class="flex items-center gap-3 border rounded-xl px-3 py-2">
                <div class="min-w-0 flex-1">
                  <div class="text-sm font-medium text-gray-800">${_escapeBoardHtml(member.display_name)}</div>
                  <div class="text-xs text-gray-400">${_escapeBoardHtml(member.email)}</div>
                </div>
                <select data-field="board-member-role" data-user-id="${member.user_id}" class="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                  <option value="viewer"${member.role === 'viewer' ? ' selected' : ''}>Viewer</option>
                  <option value="editor"${member.role === 'editor' ? ' selected' : ''}>Editor</option>
                  <option value="owner"${member.role === 'owner' ? ' selected' : ''}>Owner</option>
                </select>
                <button data-action="remove-board-member" data-user-id="${member.user_id}" class="text-sm text-red-400 hover:text-red-600 transition-colors">Remove</button>
              </div>
            `).join('')}
          </div>
        </div>
      ` : '';
      this.settingsModalEl.innerHTML = `
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" data-action="close-settings">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto" data-stop-propagation="true">
            <div class="p-6">
              <div class="flex items-center justify-between mb-5">
                <h2 class="text-lg font-bold text-gray-800">Hub Settings</h2>
                <button data-action="close-settings" class="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
              </div>
              <div class="mb-5">
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Hub Name</label>
                <input
                  data-field="settings-board-name"
                  value="${_escapeBoardHtml(this.settingsBoardName)}"
                  ${this.canManageBoard ? '' : 'disabled'}
                  class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                >
              </div>
              <div class="mb-6">
                <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Hub Color</label>
                <div class="flex flex-wrap gap-2 mb-3">
                  ${colorButtons}
                  <button
                    data-action="clear-board-color"
                    ${this.canManageBoard ? '' : 'disabled'}
                    class="w-8 h-8 rounded-full bg-gray-100 border-2 border-dashed border-gray-300 flex items-center justify-center text-gray-400 hover:bg-gray-200 transition-colors ${this.emptyColorSettingsClass(this.settingsBoardColor)}"
                    title="No color"
                  >✕</button>
                </div>
                <div class="h-6 rounded-lg transition-colors ${this.settingsBoardColorStyle}"></div>
              </div>
              ${shareSection}
              <div class="flex justify-end gap-2 border-t pt-4">
                <button data-action="close-settings" class="text-gray-500 hover:text-gray-700 px-4 py-2 text-sm">Cancel</button>
                ${this.canManageBoard ? `<button data-action="save-settings" class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Save</button>` : ''}
              </div>
            </div>
          </div>
        </div>
      `;
    },

    renderTaskModal() {
      if (!this.taskModalEl) return;
      if (!this.showModal || !this.selectedTask) {
        this.taskModalEl.innerHTML = '';
        return;
      }
      const task = this.selectedTask;
      const canEdit = this.canEditBoard;
      const dis = canEdit ? '' : 'disabled';

      // --- title row ---
      const doneLabel = task.done ? '✓ Done' : 'Mark Done';
      const doneCls = task.done
        ? 'bg-green-100 text-green-700 hover:bg-green-200'
        : 'bg-gray-100 text-gray-600 hover:bg-gray-200';
      const doneBtn = canEdit
        ? `<button data-action="modal-toggle-done" class="flex-shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${doneCls}">${doneLabel}</button>`
        : '';
      const actionMenuBtn = canEdit ? `
        <div class="relative flex-shrink-0" data-role="modal-action-menu-anchor">
          <button
            data-action="modal-toggle-action-menu"
            class="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 text-sm font-medium transition-colors"
            title="Objective actions"
          >☰</button>
          ${this._renderTaskActionMenuDropdown(task)}
        </div>
      ` : '';

      // --- assignee ---
      const memberOptions = this.assignableMembers.map(m => {
        const sel = this.sameString(task.assignee_user_id, m.user_id) ? ' selected' : '';
        return `<option value="${_escapeBoardHtml(String(m.user_id))}"${sel}>${_escapeBoardHtml(m.display_name)}</option>`;
      }).join('');
      const assigneeUnselected = !task.assignee_user_id ? ' selected' : '';

      // --- color picker ---
      const colorBtnClass = this.colorSwatchClass(task.color);
      const colorSwatches = PRESET_COLORS.map(c => {
        const cls = `${this.colorSwatchClass(c)} ${this.selectedColorClass(task.color, c)}`.trim();
        return `<button data-action="modal-pick-color" data-color="${c}" class="w-6 h-6 rounded-full hover:scale-110 transition-transform border border-black/10 ${cls}"></button>`;
      }).join('');
      const colorPickerDropdown = this.taskColorPickerOpen ? `
        <div class="absolute top-full right-0 mt-1 bg-white shadow-xl rounded-xl p-3 z-30 w-48">
          <div class="flex flex-wrap gap-2">
            ${colorSwatches}
            <button data-action="modal-clear-color" class="w-6 h-6 rounded-full bg-gray-100 border border-dashed border-gray-300 flex items-center justify-center text-gray-400 text-xs hover:bg-gray-200" title="No color">✕</button>
          </div>
        </div>
      ` : '';

      // --- parent task ---
      const parentSection = task.parent_task ? `
        <div class="mb-5">
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Quest</label>
          <button data-action="modal-open-parent-task" class="w-full text-left border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400">
            <span class="text-blue-600 font-medium">${_escapeBoardHtml(task.parent_task.title || '')}</span>
          </button>
        </div>
      ` : '';

      // --- recurrence ---
      const recurrenceSection = task.recurrence ? this._renderRecurrenceSection(task, canEdit) : '';

      // --- description ---
      const descVis = this.descriptionVisibilityValue(task);
      const descVisBtns = ['default', 'show', 'hide'].map((v, i) => {
        const border = i < 2 ? 'border-r border-gray-200' : '';
        const cls = this.visibilityButtonClass(descVis, v);
        return `<button type="button" data-action="modal-update-description-visibility" data-value="${v}" ${dis} class="px-2.5 py-1 text-xs font-medium transition-colors ${border} ${cls}">${v.charAt(0).toUpperCase() + v.slice(1)}</button>`;
      }).join('');

      let descContent;
      if (this.descriptionEditing) {
        descContent = `
          <textarea
            data-field="modal-description"
            ${dis}
            rows="5"
            placeholder="Add a description... (supports Markdown)"
            class="w-full border rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-400"
          >${_escapeBoardHtml(task.description || '')}</textarea>
        `;
      } else {
        const descClickAttr = canEdit ? 'data-action="modal-edit-description"' : '';
        let descInner;
        if (task.description && task.description.trim()) {
          descInner = renderMarkdown(task.description);
        } else {
          descInner = `<span class="text-gray-400 italic">Add a description...</span>`;
        }
        descContent = `<div ${descClickAttr} class="min-h-[60px] cursor-text rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 border border-transparent hover:border-gray-200 transition-colors prose prose-sm max-w-none">${descInner}</div>`;
      }

      // --- custom fields ---
      const customFieldsSection = this._renderCustomFieldsSection(task, canEdit);

      // --- checklist ---
      const checklistSection = this._renderChecklistSection(task, canEdit);

      this.taskModalEl.innerHTML = `
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" data-action="close-task-modal">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" data-stop-propagation="true">
            <div class="p-6">
              <div class="flex items-start gap-3 mb-5">
                <div class="flex-1">
                  <input
                    data-field="modal-title"
                    value="${_escapeBoardHtml(task.title || '')}"
                    ${dis}
                    class="text-xl font-bold w-full border-b-2 border-transparent hover:border-gray-200 focus:border-blue-400 focus:outline-none py-0.5 transition-colors"
                  >
                </div>
                ${doneBtn}
                ${actionMenuBtn}
                <button data-action="close-task-modal" class="text-gray-400 hover:text-gray-600 text-xl leading-none flex-shrink-0">×</button>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-4 mb-5 items-end">
                <div>
                  <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Assignee</label>
                  <select data-field="modal-assignee" ${dis} class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                    <option value=""${assigneeUnselected}>Unassigned</option>
                    ${memberOptions}
                  </select>
                </div>
                <div>
                  <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Due Date</label>
                  <input
                    type="date"
                    data-field="modal-due-date"
                    value="${_escapeBoardHtml(task.due_date || '')}"
                    ${dis}
                    class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                  >
                </div>
                <div class="relative pb-0.5" data-role="modal-color-picker-anchor">
                  <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Color</label>
                  <button
                    data-action="modal-toggle-color-picker"
                    ${dis}
                    class="w-8 h-8 rounded-full border-2 border-gray-200 hover:scale-110 transition-transform shadow-sm ${colorBtnClass}"
                    title="Pick color"
                  ></button>
                  ${colorPickerDropdown}
                </div>
              </div>

              ${parentSection}
              ${recurrenceSection}

              <div class="mb-5">
                <div class="flex items-center justify-between gap-3 mb-1">
                  <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide">Description</label>
                  <div class="inline-flex rounded-lg border border-gray-200 overflow-hidden flex-shrink-0">${descVisBtns}</div>
                </div>
                ${descContent}
              </div>

              ${customFieldsSection}
              ${checklistSection}
            </div>
          </div>
        </div>
      `;

      // Focus description textarea after render if editing
      if (this.descriptionEditing) {
        requestAnimationFrame(() => {
          this.taskModalEl.querySelector('[data-field="modal-description"]')?.focus();
        });
      }
    },

    _renderTaskActionMenuDropdown(task) {
      if (!this.taskActionMenuOpen) return '';
      const typeOptions = [
        `<option value=""${!task.task_type_id ? ' selected' : ''}>Objective (default)</option>`,
        ...this.taskTypes.map(tt => {
          const sel = this.sameString(task.task_type_id, tt.id) ? ' selected' : '';
          return `<option value="${_escapeBoardHtml(String(tt.id))}"${sel}>${_escapeBoardHtml(this.taskTypeOptionLabel(tt))}</option>`;
        }),
      ].join('');
      const stageOptions = this.realStages.map(stage => {
        const sel = this.sameString(task.stage_id, stage.id) ? ' selected' : '';
        return `<option value="${stage.id}"${sel}>${_escapeBoardHtml(stage.name)}</option>`;
      }).join('');
      const recurrenceToggle = task.recurrence
        ? `<button data-action="modal-disable-recurrence-menu" class="w-full text-left text-sm text-amber-600 hover:text-amber-800 transition-colors">Stop this objective from recurring</button>`
        : `<button data-action="modal-enable-recurrence-menu" class="w-full text-left text-sm text-blue-600 hover:text-blue-800 transition-colors">Make this a recurring objective</button>`;
      return `
        <div class="absolute top-full right-0 mt-1 bg-white text-gray-800 shadow-xl rounded-xl p-3 min-w-[260px] z-30 space-y-3">
          <div>
            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Objective Type</label>
            <select data-field="modal-task-type" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">${typeOptions}</select>
          </div>
          <div>
            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Stage</label>
            <select data-field="modal-stage" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">${stageOptions}</select>
          </div>
          <div class="border-t pt-3">${recurrenceToggle}</div>
          <div class="border-t pt-3">
            <button data-action="modal-delete-task" class="w-full text-left text-sm text-red-500 hover:text-red-700 transition-colors">Delete objective</button>
          </div>
        </div>
      `;
    },

    _renderRecurrenceSection(task, canEdit) {
      const dis = canEdit ? '' : 'disabled';
      const rec = task.recurrence;
      const containerCls = this.recurrenceExpanded ? 'p-4' : 'px-4 py-2.5';
      const headerCls = this.recurrenceExpanded ? 'mb-3' : '';
      const toggleLabel = this.recurrenceExpanded ? 'Hide details' : 'Show details';
      const stopBtn = canEdit
        ? `<button data-action="modal-disable-recurrence" class="text-sm text-amber-600 hover:text-amber-800 px-3 py-1.5">Stop repeating</button>`
        : '';

      let expandedContent = '';
      if (this.recurrenceExpanded) {
        const modeOptions = [
          `<option value="create_new"${rec.mode === 'create_new' ? ' selected' : ''}>Create a new objective</option>`,
          `<option value="reuse_existing"${rec.mode === 'reuse_existing' ? ' selected' : ''}>Reuse this objective</option>`,
        ].join('');
        const freqOptions = ['daily', 'weekly', 'monthly'].map(f =>
          `<option value="${f}"${rec.frequency === f ? ' selected' : ''}>${f.charAt(0).toUpperCase() + f.slice(1)}</option>`
        ).join('');
        const unitLabel = this.recurrenceUnitLabel(rec.frequency, rec.interval);
        const spawnStageOptions = this.realStages.map(stage => {
          const sel = this.sameString(rec.spawn_stage_id, stage.id) ? ' selected' : '';
          return `<option value="${_escapeBoardHtml(String(stage.id))}"${sel}>${_escapeBoardHtml(stage.name)}</option>`;
        }).join('');
        const saveBtn = canEdit
          ? `<button data-action="modal-save-recurrence" class="bg-blue-500 hover:bg-blue-600 text-white text-sm px-3 py-1.5 rounded-lg transition-colors">Save recurrence</button>`
          : '';
        expandedContent = `
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Behavior</label>
              <select data-field="modal-recurrence-mode" ${dis} class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">${modeOptions}</select>
            </div>
            <div>
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Frequency</label>
              <select data-field="modal-recurrence-frequency" ${dis} class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">${freqOptions}</select>
            </div>
            <div>
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Every</label>
              <div class="flex items-center gap-2">
                <input type="number" min="1" step="1" data-field="modal-recurrence-interval" value="${_escapeBoardHtml(String(rec.interval || 1))}" ${dis} class="w-24 border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                <span class="text-sm text-gray-500">${_escapeBoardHtml(unitLabel)}</span>
              </div>
            </div>
            <div>
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Next Occurrence</label>
              <input type="date" data-field="modal-recurrence-next-run-on" value="${_escapeBoardHtml(rec.next_run_on || '')}" ${dis} class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            </div>
            <div>
              <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Start Stage</label>
              <select data-field="modal-recurrence-spawn-stage" ${dis} class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">${spawnStageOptions}</select>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-4">${saveBtn}</div>
        `;
      }

      return `
        <div class="mb-5 border rounded-xl bg-gray-50 ${containerCls}">
          <div class="flex items-center justify-between gap-3 ${headerCls}">
            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide">Recurrence</label>
            <div class="flex items-center gap-2">
              <button data-action="modal-toggle-recurrence-expanded" class="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5">${_escapeBoardHtml(toggleLabel)}</button>
              ${stopBtn}
            </div>
          </div>
          ${expandedContent}
        </div>
      `;
    },

    _renderCustomFieldsSection(task, canEdit) {
      const taskType = this.selectedTaskType;
      if (!taskType || !taskType.custom_fields || !taskType.custom_fields.length) return '';
      const dis = canEdit ? '' : 'disabled';
      const fields = taskType.custom_fields.map(field => {
        const currentValue = this.selectedTaskCustomFieldValue(field);
        let input;
        if (field.field_type === 'dropdown') {
          const blankOpt = `<option value="">— select —</option>`;
          const opts = (field.options || []).map(opt => {
            const label = this.customFieldOptionLabel(opt);
            const sel = currentValue === label ? ' selected' : '';
            return `<option value="${_escapeBoardHtml(label)}"${sel}>${_escapeBoardHtml(label)}</option>`;
          }).join('');
          input = `<select data-field="modal-custom-field" data-field-id="${field.id}" ${dis} class="flex-1 border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">${blankOpt}${opts}</select>`;
        } else {
          const type = this.selectedTaskInputType(field);
          input = `<input type="${type}" data-field="modal-custom-field" data-field-id="${field.id}" value="${_escapeBoardHtml(String(currentValue))}" ${dis} placeholder="${_escapeBoardHtml(field.name)}" class="flex-1 border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">`;
        }
        return `
          <div class="flex items-center gap-3">
            <label class="text-sm text-gray-600 w-1/3 flex-shrink-0">${_escapeBoardHtml(field.name)}</label>
            ${input}
          </div>
        `;
      }).join('');
      return `
        <div class="mb-5">
          <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Custom Fields</label>
          <div class="space-y-2">${fields}</div>
        </div>
      `;
    },

    _renderChecklistSection(task, canEdit) {
      const dis = canEdit ? '' : 'disabled';
      const checklist = task.checklist || [];
      const summary = checklist.length ? ` <span class="ml-1 normal-case font-normal text-gray-400">(${this.checklistProgress(task)})</span>` : '';
      const epicBadge = this.selectedTaskType?.is_epic
        ? `<span class="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">⚡ Items spawn objectives</span>`
        : '';

      const checklistVis = this.checklistVisibilityValue(task);
      const clVisBtns = ['default', 'show', 'hide'].map((v, i) => {
        const border = i < 2 ? 'border-r border-gray-200' : '';
        const cls = this.visibilityButtonClass(checklistVis, v);
        return `<button type="button" data-action="modal-update-checklist-visibility" data-value="${v}" ${dis} class="px-2.5 py-1 text-xs font-medium transition-colors ${border} ${cls}">${v.charAt(0).toUpperCase() + v.slice(1)}</button>`;
      }).join('');

      const progressBar = checklist.length
        ? `<progress class="checklist-progress mb-2" max="100" value="${this.checklistPercent(task)}"></progress>`
        : '';

      const items = checklist.map(item => {
        const checked = item.done ? ' checked' : '';
        const containerCls = this.linkedChecklistItemContainerClass(item);

        let textOrEdit;
        if (item._editing === true) {
          textOrEdit = `
            <input
              data-field="modal-checklist-item-edit"
              data-item-id="${item.id}"
              value="${_escapeBoardHtml(item._draft_title || item.title || '')}"
              class="flex-1 min-w-0 border rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            >
          `;
        } else {
          const textCls = this.linkedChecklistItemTextClass(item);
          const titleAttr = item.spawned_task_id ? ' title="Open linked objective"' : '';
          const clickAttr = item.spawned_task_id ? `data-action="modal-open-spawned-task" data-task-id="${item.spawned_task_id}"` : '';
          const linkIcon = item.spawned_task_id
            ? `<span data-action="modal-open-spawned-task" data-task-id="${item.spawned_task_id}" class="checklist-linked-icon flex-shrink-0 text-xs" title="Open linked objective">↗</span>`
            : '';
          textOrEdit = `
            <span ${clickAttr} class="text-sm min-w-0 ${textCls}"${titleAttr}>${_escapeBoardHtml(item.title || '')}</span>
            ${linkIcon}
          `;
        }

        const editBtn = canEdit && item._editing !== true
          ? `<button data-action="modal-edit-checklist-item" data-item-id="${item.id}" class="text-gray-200 hover:text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 text-xs" title="Edit item">✎</button>`
          : '';
        const deleteBtn = canEdit
          ? `<button data-action="modal-delete-checklist-item" data-item-id="${item.id}" class="text-gray-200 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" title="Delete item">×</button>`
          : '';

        return `
          <div class="flex items-center gap-2 group">
            <input type="checkbox" data-action="modal-toggle-checklist-item" data-item-id="${item.id}"${checked} ${dis} class="h-4 w-4 rounded accent-blue-500 flex-shrink-0">
            <div class="flex flex-1 items-center gap-1.5 min-w-0 ${containerCls}">
              ${textOrEdit}
            </div>
            ${editBtn}
            ${deleteBtn}
          </div>
        `;
      }).join('');

      const addItemInput = `
        <div class="flex gap-2">
          <input
            data-field="modal-new-checklist-item"
            value="${_escapeBoardHtml(this.newChecklistItem)}"
            ${dis}
            placeholder="Add an item..."
            class="flex-1 border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
          ${canEdit ? `<button data-action="modal-add-checklist-item" class="bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm px-3 py-1.5 rounded-lg transition-colors">Add</button>` : ''}
        </div>
      `;

      return `
        <div class="mb-5">
          <div class="flex items-center justify-between gap-3 mb-2">
            <label class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Checklist${summary}</label>
            <div class="flex items-center gap-2 flex-wrap justify-end">
              ${epicBadge}
              <div class="inline-flex rounded-lg border border-gray-200 overflow-hidden flex-shrink-0">${clVisBtns}</div>
            </div>
          </div>
          ${progressBar}
          <div class="space-y-1.5 mb-2">${items}</div>
          ${addItemInput}
        </div>
      `;
    },

    renderLogConfigModal() {
      if (!this.logConfigModalEl) return;
      if (!this.showLogConfig || !this.logConfigStage) {
        this.logConfigModalEl.innerHTML = '';
        return;
      }
      const stage = this.logConfigStage;
      const isLogChecked = stage.is_log ? ' checked' : '';
      const filterOptions = this.savedFilters.map(f => {
        const sel = this.sameString(stage.filter_id, f.id) ? ' selected' : '';
        return `<option value="${_escapeBoardHtml(String(f.id))}"${sel}>${_escapeBoardHtml(f.name)}</option>`;
      }).join('');
      const allSelected = !stage.filter_id ? ' selected' : '';
      const filterSection = stage.is_log ? `
        <div class="space-y-3">
          <div>
            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Saved Filter</label>
            <select data-field="log-config-filter-id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400">
              <option value=""${allSelected}>All objectives</option>
              ${filterOptions}
            </select>
            <a href="${_escapeBoardHtml(this.logConfigFiltersHref)}" class="inline-block mt-2 text-xs text-sky-600 hover:text-sky-700">Manage filters</a>
            ${this.showLogConfigFiltersEmptyState ? '<p class="mt-2 text-xs text-gray-400">No saved filters yet.</p>' : ''}
          </div>
        </div>
      ` : '';

      this.logConfigModalEl.innerHTML = `
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" data-action="close-log-config">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md" data-stop-propagation="true">
            <div class="p-6">
              <div class="flex items-center justify-between mb-5">
                <h2 class="text-lg font-bold text-gray-800">Stage Settings</h2>
                <button data-action="close-log-config" class="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
              </div>
              <label class="flex items-center gap-2 text-sm text-gray-700 mb-4">
                <input type="checkbox" data-field="log-config-is-log"${isLogChecked} class="h-4 w-4 rounded accent-sky-500">
                Log stage
              </label>
              ${filterSection}
              <div class="flex justify-end gap-2 border-t pt-4 mt-5">
                <button data-action="close-log-config" class="text-gray-500 hover:text-gray-700 px-4 py-2 text-sm">Cancel</button>
                <button data-action="save-log-config" class="bg-sky-500 hover:bg-sky-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Save</button>
              </div>
            </div>
          </div>
        </div>
      `;
    },

    renderCalendarDay(day) {
      const count = day.entries.length ? `<span class="text-[11px] font-medium calendar-day-count">${_escapeBoardHtml(this.calendarDayCountLabel(day.entries))}</span>` : '';
      const entries = day.entries.map(entry => this.renderCalendarEntry(entry, day.date)).join('');
      return `
        <div class="min-h-[11rem] border-b border-r border-slate-200 p-2.5 flex flex-col gap-2 ${this.calendarDayClass(day)}" data-calendar-day="true" data-calendar-date="${day.date}">
          <div class="flex items-center justify-between gap-2">
            <span class="inline-flex items-center justify-center h-8 min-w-8 px-2 rounded-full text-sm font-semibold ${this.calendarDayNumberClass(day)}">${day.dayNumber}</span>
            ${count}
          </div>
          <div class="space-y-2 flex-1 min-h-[6rem]" data-calendar-dropzone="true">
            ${entries}
          </div>
        </div>
      `;
    },

    renderCalendarEntry(entry, dayKey) {
      return `
        <div
          data-action="open-task"
          data-open-task-id="${entry.id}"
          data-calendar-task="true"
          data-task-id="${this.calendarTaskId(entry)}"
          data-calendar-draggable="${this.calendarEntryDraggableValue(entry)}"
          role="button"
          tabindex="0"
          class="w-full rounded-lg px-2.5 py-2 bg-white shadow-sm hover:shadow-md transition-all cursor-pointer ${this.calendarTaskCardClass(entry, dayKey)} ${this.taskCardClass(entry)}"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="text-sm font-medium leading-snug ${this.calendarEntryTitleClass(entry)}">${_escapeBoardHtml(entry.title)}</span>
            ${entry.recurrence ? '<span class="text-[10px] font-semibold uppercase tracking-wide opacity-70">↻</span>' : ''}
          </div>
          <div class="mt-1.5 flex items-center gap-1.5 flex-wrap">
            ${entry.task_type ? `<span class="text-[11px] px-1.5 py-0.5 rounded font-medium ${this.taskTypeBadgeClass(entry.task_type)}">${_escapeBoardHtml(entry.task_type.name)}</span>` : ''}
            <span class="text-[11px] px-1.5 py-0.5 rounded font-medium bg-slate-100 text-slate-600">${_escapeBoardHtml(this.calendarStageLabel(entry))}</span>
            ${entry.is_calendar_preview ? '<span class="text-[11px] text-blue-600 font-medium">Next occurrence</span>' : ''}
          </div>
        </div>
      `;
    },

    checklistProgress(task) {
      if (!task.checklist || !task.checklist.length) return '';
      const done = task.checklist.filter(i => i.done).length;
      return `${done}/${task.checklist.length}`;
    },

    checklistPercent(task) {
      if (!task.checklist || !task.checklist.length) return 0;
      return Math.round(task.checklist.filter(i => i.done).length / task.checklist.length * 100);
    },

    initSortable() {
      this.showStageDropTargets = false;
      if (this.boardView === 'calendar') {
        if (!this.canEditBoard) return;
        this.initCalendarSortable();
        return;
      }
      if (this.boardView !== 'stages') {
        return;
      }

      this.stages.forEach(stage => {
        const el = document.getElementById('stage-' + stage.id);
        if (!el) return;
        if (stage.is_log) return;
        if (Sortable.get(el)) return;
        const s = Sortable.create(el, {
          group: 'tasks',
          animation: 150,
          draggable: '[data-task-id]',
          ghostClass: 'task-ghost',
          onEnd: async (evt) => {
            const newStageId = parseInt(evt.to.dataset.stageId);
            const taskEls = Array.from(evt.to.querySelectorAll('[data-task-id]'));
            const ids = taskEls.map(el => parseInt(el.dataset.taskId));
            const movedTaskId = parseInt(evt.item.dataset.taskId);
            const stageMap = new Map(this.stages.map(stage => [stage.id, {
              ...stage,
              tasks: stage.tasks.filter(task => task.id !== movedTaskId),
            }]));
            const movedTask = this.stages.flatMap(stage => stage.tasks).find(task => task.id === movedTaskId);
            const targetStage = stageMap.get(newStageId);
            if (movedTask && targetStage) {
              const taskMap = new Map(this.stages.flatMap(stage => stage.tasks).map(task => [task.id, task]));
              targetStage.tasks = ids
                .map((id, index) => {
                  const task = taskMap.get(id);
                  if (!task) return null;
                  return {...task, stage_id: newStageId, position: index};
                })
                .filter(Boolean);
              this.stages = this.stages.map(stage => {
                const updatedStage = stageMap.get(stage.id);
                if (!updatedStage) return stage;
                if (stage.id === newStageId) return updatedStage;
                return {
                  ...updatedStage,
                  tasks: updatedStage.tasks.map((task, index) => ({...task, position: index})),
                };
              });
            }
            await fetch('/api/tasks/reorder', {
              method: 'PUT',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({stage_id: newStageId, ids}),
            });
            await this.reloadStagesAfterDrag();
          },
        });
        this._sortables.push(s);
      });
    },

    initCalendarSortable() {
      const dayContainers = Array.from(document.querySelectorAll('[data-calendar-date]'));
      dayContainers.forEach(dayEl => {
        const taskList = dayEl.querySelector('[data-calendar-dropzone]');
        if (!taskList) return;
        if (Sortable.get(taskList)) return;
        const sortable = Sortable.create(taskList, {
          group: 'calendar-tasks',
          animation: 150,
          ghostClass: 'task-ghost',
          draggable: '[data-calendar-draggable="true"]',
          onEnd: async (evt) => {
            const taskId = parseInt(evt.item.dataset.taskId, 10);
            const targetDate = evt.to.closest('[data-calendar-date]')?.dataset.calendarDate;
            const sourceDate = evt.from.closest('[data-calendar-date]')?.dataset.calendarDate;
            if (!taskId || !targetDate || targetDate === sourceDate) {
              await this.reloadStagesAfterDrag();
              return;
            }
            await this.handleCalendarTaskDrop(taskId, targetDate);
          },
        });
        this._sortables.push(sortable);
      });
    },

    buildStagePlacements() {
      const placements = [];
      const stageSlots = Array.from(document.querySelectorAll('[data-stage-slot]'));
      stageSlots.forEach(slotEl => {
        const stageEl = Array.from(slotEl.children).find(child => child.dataset.stageColumnId);
        if (!stageEl) return;
        placements.push({
          id: parseInt(stageEl.dataset.stageColumnId, 10),
          row: parseInt(slotEl.dataset.stageRow || '0', 10),
          position: parseInt(slotEl.dataset.stageSlotPosition || '0', 10),
        });
      });
      return placements;
    },

    bindStageDragEvents() {
      if (this._stageDragBound) return;
      this._stageDragBound = true;
      document.addEventListener('mousedown', evt => {
        const handle = evt.target.closest('[data-stage-drag-handle]');
        const stageEl = handle?.closest('[data-stage-column-id]');
        this._armedStageDragId = stageEl ? parseInt(stageEl.dataset.stageColumnId || '0', 10) : null;
        if (stageEl) {
          stageEl.draggable = true;
        }
      });
      document.addEventListener('mouseup', () => {
        this.resetArmedStageDrag();
      });
      document.addEventListener('dragstart', evt => {
        const stageEl = evt.target instanceof HTMLElement && evt.target.matches('[data-stage-column-id]')
          ? evt.target
          : null;
        if (!stageEl) return;
        const draggedId = parseInt(stageEl.dataset.stageColumnId || '0', 10);
        if (!this.canEditBoard || this.boardView !== 'stages' || !draggedId || this._armedStageDragId !== draggedId) {
          evt.preventDefault();
          return;
        }
        this._stageDragContext = {
          draggedId,
          placements: this.clonePlacements(this.buildStagePlacements()),
        };
        this.showStageDropTargets = true;
        this.updateStageDropTargetVisibility();
        if (evt.dataTransfer) {
          evt.dataTransfer.effectAllowed = 'move';
          evt.dataTransfer.setData('text/plain', String(draggedId));
        }
      });
      document.addEventListener('dragover', evt => {
        const slot = evt.target.closest?.('[data-stage-slot]');
        if (!slot || !this._stageDragContext) return;
        const targetRow = parseInt(slot.dataset.stageRow || '-1', 10);
        const targetPosition = parseInt(slot.dataset.stageSlotPosition || '-1', 10);
        if (!this.canPlaceStageTarget(this._stageDragContext.draggedId, targetRow, targetPosition)) return;
        evt.preventDefault();
        if (evt.dataTransfer) {
          evt.dataTransfer.dropEffect = 'move';
        }
      });
      document.addEventListener('drop', evt => {
        const slot = evt.target.closest?.('[data-stage-slot]');
        if (!slot || !this._stageDragContext) return;
        evt.preventDefault();
        const targetRow = parseInt(slot.dataset.stageRow || '-1', 10);
        const targetPosition = parseInt(slot.dataset.stageSlotPosition || '-1', 10);
        this.finishStageDrop(targetRow, targetPosition);
      });
      document.addEventListener('dragend', evt => {
        const stageEl = evt.target instanceof HTMLElement && evt.target.matches('[data-stage-column-id]')
          ? evt.target
          : null;
        if (stageEl) {
          stageEl.draggable = false;
        }
        this.resetArmedStageDrag();
        this.showStageDropTargets = false;
        this.updateStageDropTargetVisibility();
        this._stageDragContext = null;
      });
    },

    resetArmedStageDrag() {
      this._armedStageDragId = null;
      document.querySelectorAll('[data-stage-column-id]').forEach(el => {
        el.draggable = false;
      });
    },

    clonePlacements(placements) {
      return placements.map(placement => ({...placement}));
    },

    placementForStage(placements, stageId) {
      return placements.find(placement => placement.id === stageId) || null;
    },

    beginStageDrag(evt) {
      const draggedId = parseInt(evt.item?.dataset?.stageColumnId || '0', 10);
      this._stageDragContext = {
        draggedId,
        placements: this.clonePlacements(this.buildStagePlacements()),
      };
    },

    stageFallbackTarget(sourcePlacement, placements) {
      if (!sourcePlacement) return null;
      if (sourcePlacement.row === 0) {
        const topOccupied = placements.some(placement => placement.row === 0 && placement.position === sourcePlacement.position);
        if (topOccupied) {
          return {row: 1, position: sourcePlacement.position};
        }
      }
      return {row: sourcePlacement.row, position: sourcePlacement.position};
    },

    applyStageDrop(placements, draggedId, targetRow, targetPosition) {
      const nextPlacements = this.clonePlacements(placements).filter(placement => placement.id !== draggedId);
      const sourcePlacement = this.placementForStage(placements, draggedId);
      if (!sourcePlacement) return nextPlacements;

      if (sourcePlacement.row === 0) {
        const promotedStage = nextPlacements.find(placement => placement.row === 1 && placement.position === sourcePlacement.position);
        if (promotedStage) {
          promotedStage.row = 0;
        }
      }

      const displacedStage = nextPlacements.find(placement => placement.row === targetRow && placement.position === targetPosition);
      if (displacedStage) {
        const fallback = this.stageFallbackTarget(sourcePlacement, nextPlacements);
        if (fallback) {
          displacedStage.row = fallback.row;
          displacedStage.position = fallback.position;
        }
      }

      nextPlacements.push({id: draggedId, row: targetRow, position: targetPosition});
      return this.normalizeStagePlacements(nextPlacements);
    },

    normalizeStagePlacements(placements) {
      const orderedPositions = [...new Set(
        placements
          .map(placement => placement.position)
          .filter(position => Number.isInteger(position))
          .sort((a, b) => a - b)
      )];
      const normalizedPosition = new Map(orderedPositions.map((position, index) => [position, index]));
      return placements
        .map(placement => ({
          ...placement,
          position: normalizedPosition.get(placement.position) ?? placement.position,
        }))
        .sort((a, b) => (a.position - b.position) || (a.row - b.row) || (a.id - b.id));
    },

    canPlaceStageDrop(evt) {
      const placements = this.previewStagePlacements(evt);
      if (!placements) return false;
      const topRowPositions = new Set(placements.filter(placement => placement.row === 0).map(placement => placement.position));
      return placements.every(placement => placement.row !== 1 || topRowPositions.has(placement.position));
    },

    canPlaceStageTarget(draggedId, targetRow, targetPosition) {
      if (!draggedId || targetRow < 0 || targetPosition < 0) return false;
      const basePlacements = this._stageDragContext?.placements || this.buildStagePlacements();
      const placements = this.applyStageDrop(basePlacements, draggedId, targetRow, targetPosition);
      const topRowPositions = new Set(placements.filter(placement => placement.row === 0).map(placement => placement.position));
      return placements.every(placement => placement.row !== 1 || topRowPositions.has(placement.position));
    },

    previewStagePlacements(evt) {
      const draggedId = parseInt(evt.dragged?.dataset?.stageColumnId || evt.item?.dataset?.stageColumnId || '0', 10);
      if (!draggedId) return null;
      const targetRow = parseInt(evt.to?.dataset?.stageRow || '0', 10);
      const slotPosition = parseInt(evt.to?.dataset?.stageSlotPosition || '0', 10);
      if (!Number.isInteger(targetRow) || !Number.isInteger(slotPosition)) return this._stageDragContext?.placements || this.buildStagePlacements();
      const basePlacements = this._stageDragContext?.placements || this.buildStagePlacements();
      return this.applyStageDrop(basePlacements, draggedId, targetRow, slotPosition);
    },

    syncStagesFromPlacements(placements) {
      const stageById = new Map(this.stages.map(stage => [stage.id, stage]));
      this.stages = placements
        .map(placement => {
          const stage = stageById.get(placement.id);
          if (!stage) return null;
          return {...stage, row: placement.row, position: placement.position};
        })
        .filter(Boolean)
        .sort((a, b) => (a.row - b.row) || (a.position - b.position));
    },

    commitStageDrop(placements = this.buildStagePlacements()) {
      this.syncStagesFromPlacements(placements);
      this.queuePersistStagePlacements(placements);
    },

    async finishStageDrop(targetRow, targetPosition) {
      const draggedId = parseInt(this._stageDragContext?.draggedId || '0', 10);
      const basePlacements = this._stageDragContext?.placements || this.buildStagePlacements();
      this._stageDragContext = null;
      if (!draggedId || targetRow < 0 || targetPosition < 0) {
        this.showStageDropTargets = false;
        this.updateStageDropTargetVisibility();
        await this.loadStages();
        return;
      }
      const placements = this.applyStageDrop(basePlacements, draggedId, targetRow, targetPosition);
      this.showStageDropTargets = false;
      this.updateStageDropTargetVisibility();
      await this.persistStagePlacements(placements);
    },

    async persistStagePlacements(placements = this._pendingStagePlacements || this.buildStagePlacements()) {
      const res = await fetch('/api/stages/reorder', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stages: placements}),
      });
      if (!res.ok) {
        await this.loadStages();
        return;
      }
      await this.loadStages();
    },

    queuePersistStagePlacements(placements) {
      this.showStageDropTargets = false;
      this.updateStageDropTargetVisibility();
      this._pendingStagePlacements = placements;
      if (this._stagePersistTimer) {
        clearTimeout(this._stagePersistTimer);
      }
      this._stagePersistTimer = setTimeout(async () => {
        this._stagePersistTimer = null;
        const nextPlacements = this._pendingStagePlacements;
        this._pendingStagePlacements = null;
        await this.persistStagePlacements(nextPlacements);
      }, 0);
    },

    // Stages
    openNewStageForm(row, position = null) {
      this.newStageRow = row;
      this.newStagePosition = position;
      this.showNewStage = true;
      this.renderBoardSurface();
      requestAnimationFrame(() => {
        this._el.querySelector('[data-field="new-stage-name"]')?.focus();
      });
    },

    cancelNewStage() {
      this.showNewStage = false;
      this.newStageName = '';
      this.newStagePosition = null;
      this.renderBoardSurface();
    },

    async createStage(row = this.newStageRow, position = this.newStagePosition) {
      if (!this.canEditBoard) return;
      if (!this.newStageName.trim()) return;
      const res = await fetch('/api/stages', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: this.newStageName.trim(), board_id: this.boardId, row, position}),
      });
      await res.json();
      this.newStageName = '';
      this.showNewStage = false;
      this.newStagePosition = null;
      await this.loadStages();
    },

    async saveStageName(stage) {
      if (!this.canEditBoard) return;
      if (!stage.name.trim()) return;
      await fetch(`/api/stages/${stage.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: stage.name.trim()}),
      });
    },

    async deleteStage(stageId) {
      if (!this.canEditBoard) return;
      if (!confirm('Delete this stage and all its objectives?')) return;
      await fetch(`/api/stages/${stageId}`, {method: 'DELETE'});
      this.stages = this.stages.filter(s => s.id !== stageId);
      this.renderBoardSurface();
    },

    // Tasks
    async createTask(stageId) {
      if (!this.canEditBoard) return;
      const title = (this.newTaskTitles[stageId] || '').trim();
      if (!title) return;
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, stage_id: stageId}),
      });
      const task = await res.json();
      const stage = this.stages.find(s => s.id === stageId);
      if (stage) stage.tasks.push(task);
      this.newTaskTitles = {...this.newTaskTitles, [stageId]: ''};
      this.showNewTask = {...this.showNewTask, [stageId]: false};
      this.renderBoardSurface();
      requestAnimationFrame(() => this.initSortable());
    },

    isNewTaskFormOpen(stageId) {
      return this.showNewTask[stageId] === true;
    },

    openNewTaskForm(stageId) {
      this.showNewTask = {...this.showNewTask, [stageId]: true};
      this.newTaskTitles = {...this.newTaskTitles, [stageId]: ''};
      this.renderBoardSurface();
      requestAnimationFrame(() => {
        this._el.querySelector(`[data-field="new-task-title"][data-stage-id="${stageId}"]`)?.focus();
      });
    },

    closeNewTaskForm(stageId) {
      this.showNewTask = {...this.showNewTask, [stageId]: false};
      this.renderBoardSurface();
    },

    updateNewTaskTitle(stageId, value) {
      this.newTaskTitles = {...this.newTaskTitles, [stageId]: value};
    },

    openTask(task) {
      this.selectedTask = this._normalizeSelectedTask(task);
      this.recurrenceExpanded = false;
      this.newChecklistItem = '';
      this.descriptionEditing = false;
      this.taskActionMenuOpen = false;
      this.taskColorPickerOpen = false;
      this.showModal = true;
      this.renderTaskModal();
    },

    closeModal() {
      this.showModal = false;
      this.recurrenceExpanded = false;
      this.descriptionEditing = false;
      this.newChecklistItem = '';
      this.taskActionMenuOpen = false;
      this.taskColorPickerOpen = false;
      this.selectedTask = null;
      this.renderTaskModal();
    },

    async openSpawnedTask(taskId) {
      await this.openTaskById(taskId);
    },

    async openTaskById(taskId) {
      const res = await fetch(`/api/tasks/${taskId}`);
      if (!res.ok) return;
      const task = await res.json();
      if (task.board_id && String(task.board_id) !== String(this.boardId)) {
        window.location.href = `/board/${task.board_id}?task_id=${task.id}`;
        return;
      }
      this.selectedTask = this._normalizeSelectedTask(task);
      this.recurrenceExpanded = false;
      this.showModal = true;
      this.newChecklistItem = '';
      this.descriptionEditing = false;
      this.taskActionMenuOpen = false;
      this.taskColorPickerOpen = false;
      this.renderTaskModal();
    },

    toggleStageMenu(stageId) {
      this.activeStageMenuId = this.activeStageMenuId === stageId ? null : stageId;
    },

    closeStageMenu() {
      this.activeStageMenuId = null;
    },

    isStageMenuOpen(stageId) {
      return this.activeStageMenuId === stageId;
    },

    toggleTaskActionMenu() {
      this.taskActionMenuOpen = !this.taskActionMenuOpen;
      this.renderTaskModal();
    },

    closeTaskActionMenu() {
      this.taskActionMenuOpen = false;
      this.renderTaskModal();
    },

    toggleTaskColorPicker() {
      this.taskColorPickerOpen = !this.taskColorPickerOpen;
      this.renderTaskModal();
    },

    closeTaskColorPicker() {
      this.taskColorPickerOpen = false;
      this.renderTaskModal();
    },

    selectedTaskColorStyle() {
      return this.colorSwatchClass(this.selectedTask?.color);
    },

    colorSwatchClass(color) {
      return color ? `swatch-${String(color).replace('#', '')}` : 'swatch-empty';
    },

    selectedColorClass(currentColor, color) {
      return currentColor === color ? 'ring-2 ring-offset-1 ring-gray-500' : '';
    },

    selectedColorSettingsClass(currentColor, color) {
      return currentColor === color ? 'ring-2 ring-offset-2 ring-gray-600 scale-110' : '';
    },

    settingsColorSwatchClass(color) {
      return `${this.colorSwatchClass(color)} ${this.selectedColorSettingsClass(this.settingsBoardColor, color)}`.trim();
    },

    taskColorSwatchClass(color) {
      return `${this.colorSwatchClass(color)} ${this.selectedColorClass(this.selectedTask?.color, color)}`.trim();
    },

    emptyColorSettingsClass(value) {
      return !value ? 'ring-2 ring-offset-2 ring-gray-400' : '';
    },

    async openParentTask() {
      if (!this.selectedTask?.parent_task?.id) return;
      const parentTask = this.selectedTask.parent_task;
      if (parentTask.board_id && String(parentTask.board_id) !== String(this.boardId)) {
        window.location.href = `/board/${parentTask.board_id}?task_id=${parentTask.id}`;
        return;
      }
      await this.openTaskById(parentTask.id);
    },

    async updateTaskField(field, value) {
      if (!this.canEditBoard) return;
      const body = {};
      body[field] = value;
      const res = await fetch(`/api/tasks/${this.selectedTask.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      const updated = await res.json();
      this.selectedTask = this._normalizeSelectedTask(updated);
      this._syncTaskInStages(updated);
      this.renderTaskModal();
      if (field === 'title' && this.selectedTask.parent_task) {
        await this.loadStages();
      }
    },

    async updateTaskType() {
      if (!this.canEditBoard) return;
      const typeId = this.selectedTask.task_type_id ? parseInt(this.selectedTask.task_type_id) : null;
      const res = await fetch(`/api/tasks/${this.selectedTask.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({task_type_id: typeId}),
      });
      const updated = await res.json();
      this.selectedTask = this._normalizeSelectedTask(updated);
      this._syncTaskInStages(updated);
      this.renderTaskModal();
    },

    async updateAssignee() {
      if (!this.canEditBoard) return;
      const assigneeUserId = this.selectedTask.assignee_user_id ? parseInt(this.selectedTask.assignee_user_id) : null;
      const res = await fetch(`/api/tasks/${this.selectedTask.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({assignee_user_id: assigneeUserId}),
      });
      const updated = await res.json();
      this.selectedTask = this._normalizeSelectedTask(updated);
      this._syncTaskInStages(updated);
      this.renderTaskModal();
    },

    async updateCustomField(fieldDefId, value) {
      if (!this.canEditBoard) return;
      const res = await fetch(`/api/tasks/${this.selectedTask.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({custom_fields: {[fieldDefId]: value}}),
      });
      const updated = await res.json();
      this.selectedTask.custom_field_values = updated.custom_field_values;
      this._syncTaskInStages(updated);
      this.renderTaskModal();
    },

    async updateDescriptionVisibility(value) {
      if (!this.canEditBoard) return;
      let nextValue = null;
      if (value === 'show') nextValue = true;
      if (value === 'hide') nextValue = false;
      await this.updateTaskField('show_description_on_card', nextValue);
    },

    async updateChecklistVisibility(value) {
      if (!this.canEditBoard) return;
      let nextValue = null;
      if (value === 'show') nextValue = true;
      if (value === 'hide') nextValue = false;
      await this.updateTaskField('show_checklist_on_card', nextValue);
    },

    async _setTaskDone(taskId, newDone) {
      const res = await fetch(`/api/tasks/${taskId}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({done: newDone}),
      });
      const updated = await res.json();
      await this.loadStages();
      return updated;
    },

    async toggleTaskDoneFromCard(task) {
      if (!this.canEditBoard) return;
      const updated = await this._setTaskDone(task.id, !task.done);
      if (this.selectedTask && this.selectedTask.id === updated.id) {
        const found = this._findTaskInStages(updated.id);
        if (found) {
          this.selectedTask = this._normalizeSelectedTask({...updated, stage_id: found.stage_id});
        } else {
          this.selectedTask = this._normalizeSelectedTask(updated);
        }
      }
    },

    async toggleDone() {
      if (!this.canEditBoard) return;
      const updated = await this._setTaskDone(this.selectedTask.id, !this.selectedTask.done);
      // Find the task in its new location and refresh modal
      const found = this._findTaskInStages(updated.id);
      if (found) {
        this.selectedTask = this._normalizeSelectedTask({...updated, stage_id: found.stage_id});
      } else {
        this.selectedTask = this._normalizeSelectedTask(updated);
      }
      this.renderTaskModal();
    },

    async moveTask() {
      if (!this.canEditBoard) return;
      const newStageId = parseInt(this.selectedTask.stage_id);
      const targetStage = this.stages.find(s => s.id === newStageId);
      const position = targetStage ? targetStage.tasks.length : 0;
      await fetch(`/api/tasks/${this.selectedTask.id}/move`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stage_id: newStageId, position}),
      });
      await this.loadStages();
    },

    async deleteTask() {
      if (!this.canEditBoard) return;
      if (!confirm('Delete this objective?')) return;
      await fetch(`/api/tasks/${this.selectedTask.id}`, {method: 'DELETE'});
      await this.loadStages();
      this.closeModal();
    },

    // Checklist
    async addChecklistItem() {
      if (!this.canEditBoard) return;
      const title = this.newChecklistItem.trim();
      if (!title) return;
      const res = await fetch(`/api/tasks/${this.selectedTask.id}/checklist`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title}),
      });
      const item = await res.json();
      this.selectedTask.checklist.push(item);
      this._syncTaskInStages(this.selectedTask);
      this.newChecklistItem = '';
      this.renderTaskModal();
      if (item.spawned_task_id) {
        // Reload to show the spawned task on the board
        await this.loadStages();
      }
    },

    async toggleChecklistItem(item) {
      if (!this.canEditBoard) return;
      const res = await fetch(`/api/tasks/${this.selectedTask.id}/checklist/${item.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({done: !item.done}),
      });
      const updated = await res.json();
      const idx = this.selectedTask.checklist.findIndex(i => i.id === item.id);
      if (idx !== -1) this.selectedTask.checklist[idx] = updated;
      this._syncTaskInStages(this.selectedTask);
      this.renderTaskModal();
      // Reload board if this item has a spawned task (automation may have moved it)
      if (item.spawned_task_id) await this.loadStages();
    },

    startChecklistItemEdit(item) {
      if (!this.canEditBoard) return;
      item._editing = true;
      item._draft_title = item.title;
    },

    cancelChecklistItemEdit(item) {
      item._editing = false;
      item._draft_title = item.title;
    },

    async saveChecklistItemTitle(item) {
      if (!this.canEditBoard || item._editing !== true) return;
      const nextTitle = String(item._draft_title || '').trim();
      item._editing = false;
      if (!nextTitle || nextTitle === item.title) {
        item._draft_title = item.title;
        return;
      }
      const res = await fetch(`/api/tasks/${this.selectedTask.id}/checklist/${item.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: nextTitle}),
      });
      const updated = await res.json();
      const idx = this.selectedTask.checklist.findIndex(i => i.id === item.id);
      if (idx !== -1) this.selectedTask.checklist[idx] = updated;
      this._syncTaskInStages(this.selectedTask);
      if (item.spawned_task_id) await this.loadStages();
    },

    async deleteChecklistItem(item) {
      if (!this.canEditBoard) return;
      await fetch(`/api/tasks/${this.selectedTask.id}/checklist/${item.id}`, {method: 'DELETE'});
      this.selectedTask.checklist = this.selectedTask.checklist.filter(i => i.id !== item.id);
      this._syncTaskInStages(this.selectedTask);
      await this.loadStages();
    },

    async sortStageByDueDate(stage) {
      if (!this.canEditBoard) return;
      if (!stage || !Array.isArray(stage.tasks)) return;

      const originalTasks = [...stage.tasks];
      const sortedTasks = [...stage.tasks].sort((a, b) => {
        const aHasDueDate = this.hasDueDate(a?.due_date);
        const bHasDueDate = this.hasDueDate(b?.due_date);
        if (aHasDueDate && bHasDueDate) {
          const byDueDate = a.due_date.localeCompare(b.due_date);
          if (byDueDate !== 0) return byDueDate;
        } else if (aHasDueDate !== bHasDueDate) {
          return aHasDueDate ? -1 : 1;
        }
        return (a.position ?? 0) - (b.position ?? 0);
      });

      const sortedIds = sortedTasks.map(task => task.id);
      const isUnchanged = sortedIds.every((id, index) => id === originalTasks[index]?.id);
      if (isUnchanged) return;

      stage.tasks = sortedTasks.map((task, index) => ({...task, position: index}));
      this.stages = [...this.stages];

      try {
        const res = await fetch('/api/tasks/reorder', {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({stage_id: stage.id, ids: sortedIds}),
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Unable to sort objectives by due date');
        }
      } catch (error) {
        stage.tasks = originalTasks;
        this.stages = [...this.stages];
        alert(error.message || 'Unable to sort objectives by due date');
      } finally {
        await this.loadStages();
      }
    },

    async clearCompletedStage(stage) {
      if (!this.canEditBoard) return;
      if (!confirm(`Clear completed objectives from "${stage.name}"? Completed quests will also clear their spawned objectives.`)) return;
      await fetch(`/api/stages/${stage.id}/clear-completed`, {method: 'POST'});
      await this.loadStages();
      if (this.selectedTask) {
        const stillExists = this._findTaskInStages(this.selectedTask.id);
        if (!stillExists) this.closeModal();
      }
    },

    openLogConfig(stage) {
      this.logConfigStage = JSON.parse(JSON.stringify(stage));
      this.logConfigStage.filter_id = this.logConfigStage.filter_id ? String(this.logConfigStage.filter_id) : '';
      this.showLogConfig = true;
      this.renderLogConfigModal();
    },

    closeLogConfig() {
      this.showLogConfig = false;
      this.logConfigStage = null;
      this.renderLogConfigModal();
    },

    async saveLogConfig() {
      if (!this.canEditBoard) return;
      if (!this.logConfigStage) return;
      const payload = {
        is_log: this.logConfigStage.is_log,
        filter_id: this.logConfigStage.is_log && this.logConfigStage.filter_id ? parseInt(this.logConfigStage.filter_id, 10) : null,
      };
      await fetch(`/api/stages/${this.logConfigStage.id}/config`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      this.showLogConfig = false;
      this.logConfigStage = null;
      this.renderLogConfigModal();
      await this.loadStages();
    },

    customFieldOptionLabel(option) {
      if (typeof option === 'string') return option;
      return option?.label || option?.value || '';
    },

    customFieldChipColor(field, value) {
      if (field?.field_type !== 'dropdown' || !value) return field?.color || null;
      const option = (field.options || []).find(opt => this.customFieldOptionLabel(opt) === value);
      return option?.color || field?.color || null;
    },

    hasCustomFieldValue(value) {
      if (value === null || value === undefined) return false;
      if (typeof value === 'string') return value.trim() !== '';
      return true;
    },

    taskCardCustomFields(task) {
      const customFields = task?.task_type?.custom_fields || [];
      const values = task?.custom_field_values || {};
      return customFields.filter(field => (
        field.show_on_card && this.hasCustomFieldValue(values[String(field.id)])
      ));
    },

    shouldShowTaskCardCustomFields(task) {
      return this.taskCardCustomFields(task).length > 0;
    },

    taskCardCustomFieldValue(task, field) {
      return task?.custom_field_values?.[String(field.id)];
    },

    taskCardCustomFieldLabel(task, field) {
      return `${field.name}: ${this.taskCardCustomFieldValue(task, field)}`;
    },

    selectedTaskCustomFieldValue(field) {
      return this.selectedTask?.custom_field_values?.[String(field.id)] || '';
    },

    taskTypeOptionLabel(taskType) {
      return `${taskType.name}${taskType.is_epic ? ' ⚡ Quest' : ''}`;
    },

    isTaskTypeSelected(taskType) {
      return this.sameString(this.selectedTask?.task_type_id || '', taskType.id);
    },

    isAssigneeSelected(member) {
      return this.sameString(this.selectedTask?.assignee_user_id || '', member.user_id);
    },

    customFieldOptions(field) {
      return field?.options || [];
    },

    isCustomFieldOptionSelected(field, option) {
      return this.selectedTaskCustomFieldValue(field) === this.customFieldOptionLabel(option);
    },

    isLogConfigFilterSelected(savedFilter) {
      return this.sameString(this.logConfigStage?.filter_id || '', savedFilter.id);
    },

    shouldShowDescriptionOnCard(task) {
      return !!(task?.effective_show_description_on_card && task?.description && String(task.description).trim());
    },

    hasDescription(task) {
      return !!(task?.description && String(task.description).trim());
    },

    shouldShowChecklistOnCard(task) {
      return !!(task?.effective_show_checklist_on_card && task?.checklist && task.checklist.length > 0);
    },

    descriptionVisibilityValue(task) {
      if (!task) return 'default';
      if (task.show_description_on_card === true) return 'show';
      if (task.show_description_on_card === false) return 'hide';
      return 'default';
    },

    visibilityButtonClass(currentValue, expectedValue, inactiveClass = 'bg-white text-gray-500 hover:bg-gray-50') {
      return currentValue === expectedValue ? 'bg-blue-50 text-blue-700' : inactiveClass;
    },

    descriptionVisibilityButtonClass(expectedValue) {
      return this.visibilityButtonClass(this.descriptionVisibilityValue(this.selectedTask), expectedValue);
    },

    checklistVisibilityValue(task) {
      if (!task) return 'default';
      if (task.show_checklist_on_card === true) return 'show';
      if (task.show_checklist_on_card === false) return 'hide';
      return 'default';
    },

    checklistVisibilityButtonClass(expectedValue) {
      return this.visibilityButtonClass(this.checklistVisibilityValue(this.selectedTask), expectedValue);
    },

    taskTypeBadgeStyle(taskType) {
      const bg = taskType?.color || '#6b7280';
      const n = parseInt(bg.replace('#', ''), 16);
      const luminance = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
      return `background:${bg}; color:${luminance > 0.55 ? '#1f2937' : '#ffffff'}`;
    },

    formatDueDate(value) {
      if (!value) return '';
      const date = new Date(value + 'T00:00:00');
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
    },

    hasDueDate(value) {
      return !!(value && String(value).trim());
    },

    dueDateLabel(value) {
      if (!this.hasDueDate(value)) return '';
      return 'Due ' + this.formatDueDate(value);
    },

    contrastTextClass(color) {
      const normalized = color || '#6b7280';
      const n = parseInt(normalized.replace('#', ''), 16);
      const luminance = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
      return luminance > 0.55 ? 'swatch-text-dark' : 'swatch-text-light';
    },

    taskCardClass(task) {
      return `task-card-border task-border-${this.taskBorderColor(task).replace('#', '')}`;
    },

    taskTypeBadgeClass(taskType) {
      const color = taskType?.color || '#6b7280';
      return `${this.colorSwatchClass(color)} ${this.contrastTextClass(color)}`.trim();
    },

    dueDateClass(value) {
      if (!this.hasDueDate(value)) return '';

      const due = new Date(value + 'T00:00:00');
      if (Number.isNaN(due.getTime())) {
        return 'due-date-invalid';
      }

      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const diffDays = Math.floor((due.getTime() - today.getTime()) / 86400000);

      if (diffDays < 0) return 'due-date-overdue';
      if (diffDays === 0) return 'due-date-today';
      if (diffDays <= 7) return 'due-date-soon';
      return 'due-date-future';
    },

    taskChipClass(field, value = null) {
      const color = this.customFieldChipColor(field, value) || field.color || '#6b7280';
      return `task-chip ${this.colorSwatchClass(color)} ${this.contrastTextClass(color)}`.trim();
    },

    taskDoneToggleClass(task) {
      return task.done
        ? 'w-4 mr-2 bg-green-500 border-green-500 text-white opacity-100'
        : 'w-0 mr-0 border-gray-300 text-transparent hover:border-green-500 hover:text-green-500 bg-white opacity-0';
    },

    taskDoneToggleTitle(task) {
      return task.done ? 'Mark objective not done' : 'Mark objective done';
    },

    taskTitleClass(task) {
      return task.done ? 'line-through text-gray-400' : '';
    },

    assigneeChipLabel(task) {
      return `@ ${task.assignee.display_name}`;
    },

    logSourceLabel(task) {
      return `In ${this.sourceStageName(task)}`;
    },

    checklistItemIconClass(item) {
      return item.done ? 'text-green-500' : 'text-gray-300';
    },

    checklistItemIcon(item) {
      return item.done ? '☑' : '☐';
    },

    checklistItemTitleClass(item) {
      return item.done ? 'line-through text-gray-400' : '';
    },

    selectedTaskInputType(field) {
      if (field.field_type === 'number') return 'number';
      if (field.field_type === 'date') return 'date';
      return 'text';
    },

    linkedChecklistItemContainerClass(item) {
      return item.spawned_task_id ? 'checklist-linked-item' : '';
    },

    linkedChecklistItemTextClass(item) {
      const tone = item.done
        ? (item.spawned_task_id ? 'line-through text-blue-600' : 'line-through text-gray-400')
        : (item.spawned_task_id ? 'text-blue-600' : 'text-gray-700');
      const affordance = item.spawned_task_id ? 'cursor-pointer hover:text-blue-700 hover:underline' : '';
      return `${tone} ${affordance}`.trim();
    },

    linkedChecklistItemTitle(item) {
      return item.spawned_task_id ? 'Open linked objective' : '';
    },

    calendarDayNumberClass(day) {
      if (day.isToday) return 'bg-slate-900 text-white';
      return day.inCurrentMonth ? 'calendar-day-number' : 'calendar-day-number-muted';
    },

    calendarEntryDraggableValue(entry) {
      return entry.is_calendar_preview ? 'false' : 'true';
    },

    calendarEntryTitleClass(entry) {
      return entry.done ? 'line-through opacity-70' : '';
    },

    taskBorderColor(task) {
      return task?.color || '#e2e8f0';
    },

    sourceStageName(task) {
      const localSource = this.stages.find(stage => String(stage.id) === String(task.stage_id));
      const stageName = task?.stage_name || localSource?.name || 'another stage';
      const boardName = task?.board_id && String(task.board_id) !== String(this.boardId)
        ? (task.board_name || this.boards.find(board => String(board.id) === String(task.board_id))?.name)
        : null;
      return boardName ? `${boardName} / ${stageName}` : stageName;
    },

    logStageSummary(stage) {
      if (!stage?.is_log) return '';
      const savedFilter = stage.saved_filter;
      if (!savedFilter) return 'Showing all objectives across this hub';
      const definition = savedFilter.definition || {};
      const parts = [savedFilter.name];
      const taskType = definition.selected_task_type_id
        ? this.taskTypes.find(tt => String(tt.id) === String(definition.selected_task_type_id))
        : null;
      if (taskType) parts.push(taskType.name);
      const sourceNames = (definition.source_board_ids || [])
        .map(boardId => this.boards.find(board => String(board.id) === String(boardId))?.name)
        .filter(Boolean);
      parts.push((sourceNames.length ? sourceNames : [this.boards.find(board => String(board.id) === String(this.boardId))?.name || 'Current hub']).join(', '));
      const ruleCount = (definition.rules || []).length;
      parts.push(`${definition.op?.toUpperCase() || 'AND'} • ${ruleCount} rule${ruleCount === 1 ? '' : 's'}`);
      return parts.join(' • ');
    },

    // Settings
    async saveSettings() {
      if (!this.canManageBoard) return;
      await fetch(`/api/boards/${this.boardId}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: this.settingsBoardName, color: this.settingsBoardColor}),
      });
      this.showSettings = false;
      document.title = 'questline';
      applyBoardColor(this.settingsBoardColor);
      this.renderBoardSurface();
    },

    async addBoardMember() {
      if (!this.canManageBoard) return;
      this.shareError = '';
      if (!this.shareEmail.trim()) return;
      const res = await fetch(`/api/boards/${this.boardId}/members`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: this.shareEmail.trim(), role: this.shareRole}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.shareError = data.detail || 'Unable to share hub';
        this.renderBoardSurface();
        return;
      }
      const member = await res.json();
      const existing = this.boardMembers.findIndex(entry => entry.user_id === member.user_id);
      if (existing === -1) {
        this.boardMembers.push(member);
      } else {
        this.boardMembers[existing] = member;
      }
      this.shareEmail = '';
      this.shareRole = 'viewer';
      await this.loadBoardMembers();
    },

    async updateBoardMemberRole(member, role) {
      if (!this.canManageBoard) return;
      const res = await fetch(`/api/boards/${this.boardId}/members/${member.user_id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.shareError = data.detail || 'Unable to update role';
        await this.loadBoardMembers();
        return;
      }
      this.shareError = '';
      await this.loadBoardMembers();
    },

    async removeBoardMember(member) {
      if (!this.canManageBoard) return;
      this.shareError = '';
      if (!confirm(`Remove ${member.display_name} from this hub?`)) return;
      const res = await fetch(`/api/boards/${this.boardId}/members/${member.user_id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const data = await res.json();
        this.shareError = data.detail || 'Unable to remove member';
        this.renderBoardSurface();
        return;
      }
      await this.loadBoardMembers();
    },

    // Helpers
    _syncTaskInStages(updated) {
      const nextTask = this._decorateTask(updated);
      let changed = false;
      this.stages = this.stages.map(stage => {
        const idx = stage.tasks.findIndex(t => t.id === updated.id);
        if (idx === -1) return stage;
        changed = true;
        const tasks = [...stage.tasks];
        tasks.splice(idx, 1, nextTask);
        return {...stage, tasks};
      });
      if (!changed) return;
      this.renderBoardSurface();
    },

    _findTaskInStages(taskId) {
      for (const stage of this.stages) {
        const t = stage.tasks.find(t => t.id === taskId);
        if (t) return {...t, stage_id: stage.id};
      }
      return null;
    },

    _normalizeSelectedTask(task) {
      const selectedTask = this._decorateTask(JSON.parse(JSON.stringify(task)));
      selectedTask.stage_id = task.stage_id;
      const taskTypeId = task.task_type_id ?? task.task_type?.id ?? '';
      selectedTask.task_type_id = taskTypeId === '' || taskTypeId === null ? '' : String(taskTypeId);
      const assigneeUserId = task.assignee_user_id ?? task.assignee?.id ?? '';
      selectedTask.assignee_user_id = assigneeUserId === '' || assigneeUserId === null ? '' : String(assigneeUserId);
      if (selectedTask.recurrence) {
        selectedTask.recurrence.spawn_stage_id = String(selectedTask.recurrence.spawn_stage_id || selectedTask.stage_id);
        selectedTask.recurrence._persisted = true;
      }
      return selectedTask;
    },

    _decorateTask(task) {
      if (!task) return task;
      return {...task};
    },

    recurrenceUnitLabel(frequency, interval) {
      const amount = Number(interval || 1);
      if (frequency === 'daily') return amount === 1 ? 'day' : 'days';
      if (frequency === 'weekly') return amount === 1 ? 'week' : 'weeks';
      return amount === 1 ? 'month' : 'months';
    },

    setBoardView(view) {
      this.boardView = view === 'calendar' ? 'calendar' : 'stages';
      this.updateBoardUrlState();
      this.renderBoardSurface();
      requestAnimationFrame(() => {
        this.initSortable();
      });
    },

    changeCalendarMonth(offset) {
      const next = new Date(this.calendarCursor);
      next.setMonth(next.getMonth() + offset, 1);
      this.calendarCursor = new Date(next.getFullYear(), next.getMonth(), 1);
      this.updateBoardUrlState();
      this.renderBoardSurface();
    },

    jumpCalendarToToday() {
      const now = new Date();
      this.calendarCursor = new Date(now.getFullYear(), now.getMonth(), 1);
      this.updateBoardUrlState();
      this.renderBoardSurface();
    },

    openCalendarCreate(day, event) {
      if (!this.canEditBoard) return;
      if (event?.target?.closest?.('[data-calendar-task]')) return;
      this.calendarCreateDate = day.date;
      this.calendarCreateStageId = String(this.realStages[0]?.id || '');
      if (!this.calendarCreateStageId) return;
      this.showCalendarCreate = true;
      this.renderBoardSurface();
    },

    closeCalendarCreate() {
      this.showCalendarCreate = false;
      this.calendarCreateDate = '';
      this.calendarCreateStageId = '';
      this.renderBoardSurface();
    },

    formatCalendarCreateDate(value) {
      if (!value) return '';
      const date = new Date(value + 'T00:00:00');
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleDateString(undefined, {weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'});
    },

    calendarDayCountLabel(entries) {
      const realCount = (entries || []).filter(entry => !entry.is_calendar_preview).length;
      const previewCount = (entries || []).filter(entry => entry.is_calendar_preview).length;
      if (realCount && previewCount) return `${realCount} objective${realCount === 1 ? '' : 's'} + ${previewCount} next`;
      if (realCount) return `${realCount} objective${realCount === 1 ? '' : 's'}`;
      return `${previewCount} next`;
    },

    async createTaskFromCalendar() {
      if (!this.canEditBoard) return;
      const stageId = parseInt(this.calendarCreateStageId, 10);
      if (!stageId || !this.calendarCreateDate) return;
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title: 'New objective',
          stage_id: stageId,
          due_date: this.calendarCreateDate,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Unable to create objective');
        return;
      }
      const task = await res.json();
      const stage = this.stages.find(s => s.id === stageId);
      if (stage) stage.tasks.push(task);
      this.closeCalendarCreate();
      this.openTask(task);
      this.renderBoardSurface();
    },

    async handleCalendarTaskDrop(taskId, targetDate) {
      const task = this.allBoardTasks.find(entry => entry.id === taskId);
      if (!task) {
        await this.loadStages();
        return;
      }

      try {
        const res = await fetch(`/api/tasks/${taskId}`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({due_date: targetDate}),
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Unable to update due date');
        }
      } catch (error) {
        alert(error.message || 'Unable to move objective');
      } finally {
        await this.loadStages();
      }
    },

    taskCalendarDate(task) {
      if (this.hasDueDate(task?.due_date)) return task.due_date;
      if (task?.recurrence?.next_run_on) return task.recurrence.next_run_on;
      return null;
    },

    shouldShowRecurrencePreview(task) {
      return !!(
        task?.recurrence?.next_run_on &&
        this.hasDueDate(task?.due_date) &&
        task.recurrence.next_run_on !== task.due_date
      );
    },

    calendarTaskCardClass(task, dayKey) {
      if (task.is_calendar_preview) return 'opacity-60 border border-dashed calendar-pill-text-done border-slate-400';
      if (task.done) return 'opacity-60 calendar-pill-text-done border border-slate-200';
      return 'calendar-pill-text border border-slate-200';
    },

    calendarStageLabel(task) {
      return task.stage_name || this.sourceStageName(task);
    },

    isTodayDate(value) {
      return value === this.formatDateKey(new Date());
    },

    isPastDate(value) {
      return value < this.formatDateKey(new Date());
    },

    formatDateKey(value) {
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) return '';
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    },

    getRequestedBoardView() {
      const params = new URLSearchParams(window.location.search);
      return params.get('view') === 'calendar' ? 'calendar' : 'stages';
    },

    getInitialCalendarCursor() {
      const params = new URLSearchParams(window.location.search);
      const month = params.get('month');
      if (month && /^\d{4}-\d{2}$/.test(month)) {
        const [year, monthNumber] = month.split('-').map(part => parseInt(part, 10));
        if (!Number.isNaN(year) && !Number.isNaN(monthNumber)) {
          return new Date(year, monthNumber - 1, 1);
        }
      }
      const requestedTaskId = this.getRequestedTaskId();
      if (requestedTaskId) {
        const taskDate = params.get('date');
        if (taskDate && /^\d{4}-\d{2}-\d{2}$/.test(taskDate)) {
          const parsed = new Date(taskDate + 'T00:00:00');
          if (!Number.isNaN(parsed.getTime())) {
            return new Date(parsed.getFullYear(), parsed.getMonth(), 1);
          }
        }
      }
      const now = new Date();
      return new Date(now.getFullYear(), now.getMonth(), 1);
    },

    updateBoardUrlState() {
      const params = new URLSearchParams(window.location.search);
      if (this.boardView === 'calendar') {
        params.set('view', 'calendar');
        params.set('month', `${this.calendarCursor.getFullYear()}-${String(this.calendarCursor.getMonth() + 1).padStart(2, '0')}`);
      } else {
        params.delete('view');
        params.delete('month');
      }
      const taskId = this.getRequestedTaskId();
      if (taskId) params.set('task_id', String(taskId));
      const query = params.toString();
      const nextUrl = `${window.location.pathname}${query ? '?' + query : ''}`;
      window.history.replaceState({}, '', nextUrl);
    },

    defaultRecurrenceForTask(task) {
      return {
        enabled: true,
        mode: 'create_new',
        frequency: 'weekly',
        interval: 1,
        next_run_on: task?.due_date || new Date().toISOString().slice(0, 10),
        spawn_stage_id: String(task?.stage_id || ''),
        _persisted: false,
      };
    },

    enableRecurrence() {
      if (!this.canEditBoard) return;
      this.selectedTask.recurrence = this.selectedTask.recurrence || this.defaultRecurrenceForTask(this.selectedTask);
      this.recurrenceExpanded = true;
      this.renderTaskModal();
    },

    async disableRecurrence() {
      if (!this.canEditBoard) return;
      await this.deleteRecurrence();
    },

    async saveRecurrence() {
      if (!this.canEditBoard || !this.selectedTask?.recurrence) return;
      const payload = {
        enabled: true,
        mode: this.selectedTask.recurrence.mode || 'create_new',
        frequency: this.selectedTask.recurrence.frequency,
        interval: parseInt(this.selectedTask.recurrence.interval, 10) || 1,
        next_run_on: this.selectedTask.recurrence.next_run_on,
        spawn_stage_id: parseInt(this.selectedTask.recurrence.spawn_stage_id, 10),
      };
      const res = await fetch(`/api/tasks/${this.selectedTask.id}/recurrence`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Unable to save recurrence');
        return;
      }
      this.selectedTask.recurrence = await res.json();
      this.selectedTask.recurrence.spawn_stage_id = String(this.selectedTask.recurrence.spawn_stage_id);
      this.selectedTask.recurrence._persisted = true;
      this._syncTaskInStages(this.selectedTask);
      this.renderTaskModal();
    },

    async deleteRecurrence() {
      if (!this.canEditBoard || !this.selectedTask) return;
      if (!this.selectedTask.recurrence) return;
      if (!this.selectedTask.recurrence._persisted) {
        this.selectedTask.recurrence = null;
        this.recurrenceExpanded = false;
        this._syncTaskInStages(this.selectedTask);
        this.renderTaskModal();
        return;
      }
      const res = await fetch(`/api/tasks/${this.selectedTask.id}/recurrence`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Unable to delete recurrence');
        return;
      }
      this.selectedTask.recurrence = null;
      this.recurrenceExpanded = false;
      this._syncTaskInStages(this.selectedTask);
      this.renderTaskModal();
    },

    getRequestedTaskId() {
      const params = new URLSearchParams(window.location.search);
      const taskId = params.get('task_id');
      return taskId ? parseInt(taskId, 10) : null;
    },
  };
}

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('board-root');
  if (!el) return;
  const instance = _createBoard();
  instance._el = el;
  instance.init();
});

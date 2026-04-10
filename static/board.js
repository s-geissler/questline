function _parseBoardPageJson(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function board() {
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
      this.boardId = parseInt(this.$el.dataset.boardId || '0', 10);
      this.boards = _parseBoardPageJson(this.$el.dataset.boards, []);
      this.settingsBoardName = _parseBoardPageJson(this.$el.dataset.boardName, '');
      this.settingsBoardColor = _parseBoardPageJson(this.$el.dataset.boardColor, '') || null;
      this.currentBoardRole = _parseBoardPageJson(this.$el.dataset.boardRole, null);
      this.boardView = this.getRequestedBoardView();
      this.calendarCursor = this.getInitialCalendarCursor();
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
    },

    async loadStages() {
      const stagesRes = await fetch('/api/stages?board_id=' + this.boardId);
      this.stages = (await stagesRes.json()).map(stage => ({
        ...stage,
        row: Number.isInteger(stage.row) ? stage.row : 0,
        tasks: (stage.tasks || []).map(task => this._decorateTask(task)),
      }));
      this.$nextTick(() => {
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
    },

    async loadBoardMembers() {
      const res = await fetch(`/api/boards/${this.boardId}/members`);
      if (!res.ok) return;
      const payload = await res.json();
      this.currentBoardRole = payload.current_role;
      this.boardMembers = payload.members || [];
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
      return nextPlacements;
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
        await this.loadStages();
        return;
      }
      const placements = this.applyStageDrop(basePlacements, draggedId, targetRow, targetPosition);
      this.showStageDropTargets = false;
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
      this.$nextTick(() => this.$refs.newStageInput?.focus());
    },

    cancelNewStage() {
      this.showNewStage = false;
      this.newStageName = '';
      this.newStagePosition = null;
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
      this.$nextTick(() => this.initSortable());
    },

    isNewTaskFormOpen(stageId) {
      return this.showNewTask[stageId] === true;
    },

    openNewTaskForm(stageId) {
      this.showNewTask = {...this.showNewTask, [stageId]: true};
      this.newTaskTitles = {...this.newTaskTitles, [stageId]: ''};
      this.$nextTick(() => document.getElementById(`new-task-input-${stageId}`)?.focus());
    },

    closeNewTaskForm(stageId) {
      this.showNewTask = {...this.showNewTask, [stageId]: false};
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
    },

    closeModal() {
      this.showModal = false;
      this.recurrenceExpanded = false;
      this.descriptionEditing = false;
      this.newChecklistItem = '';
      this.taskActionMenuOpen = false;
      this.taskColorPickerOpen = false;
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
    },

    closeTaskActionMenu() {
      this.taskActionMenuOpen = false;
    },

    toggleTaskColorPicker() {
      this.taskColorPickerOpen = !this.taskColorPickerOpen;
    },

    closeTaskColorPicker() {
      this.taskColorPickerOpen = false;
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
      this.$nextTick(() => {
        this.initSortable();
      });
    },

    changeCalendarMonth(offset) {
      const next = new Date(this.calendarCursor);
      next.setMonth(next.getMonth() + offset, 1);
      this.calendarCursor = new Date(next.getFullYear(), next.getMonth(), 1);
      this.updateBoardUrlState();
    },

    jumpCalendarToToday() {
      const now = new Date();
      this.calendarCursor = new Date(now.getFullYear(), now.getMonth(), 1);
      this.updateBoardUrlState();
    },

    openCalendarCreate(day, event) {
      if (!this.canEditBoard) return;
      if (event?.target?.closest?.('[data-calendar-task]')) return;
      this.calendarCreateDate = day.date;
      this.calendarCreateStageId = String(this.realStages[0]?.id || '');
      if (!this.calendarCreateStageId) return;
      this.showCalendarCreate = true;
    },

    closeCalendarCreate() {
      this.showCalendarCreate = false;
      this.calendarCreateDate = '';
      this.calendarCreateStageId = '';
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
    },

    async deleteRecurrence() {
      if (!this.canEditBoard || !this.selectedTask) return;
      if (!this.selectedTask.recurrence) return;
      if (!this.selectedTask.recurrence._persisted) {
        this.selectedTask.recurrence = null;
        this.recurrenceExpanded = false;
        this._syncTaskInStages(this.selectedTask);
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
    },

    getRequestedTaskId() {
      const params = new URLSearchParams(window.location.search);
      const taskId = params.get('task_id');
      return taskId ? parseInt(taskId, 10) : null;
    },
  };
}

document.addEventListener('alpine:init', () => {
  Alpine.data('board', board);
});

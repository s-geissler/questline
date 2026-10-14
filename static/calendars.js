document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('calendar-feeds-modal');
  if (!modal) return;
  const list = document.getElementById('calendar-feeds-list');
  const form = document.getElementById('calendar-feed-form');
  const fields = document.getElementById('calendar-feed-fields');
  const nameInput = document.getElementById('calendar-feed-name');
  const boardInput = document.getElementById('calendar-feed-board');
  const assignedInput = document.getElementById('calendar-feed-assigned');
  const stagesInput = document.getElementById('calendar-feed-stages');
  const editForm = document.getElementById('calendar-feed-edit-form');
  const editFields = document.getElementById('calendar-feed-edit-fields');
  const editStagesInput = document.getElementById('calendar-feed-edit-stages');
  const error = document.getElementById('calendar-feeds-error');
  const feedback = document.getElementById('calendar-feeds-feedback');
  const createdPanel = document.getElementById('calendar-feed-created');
  const urlInput = document.getElementById('calendar-feed-url');
  let generation = 0;
  let isOpen = false;
  let busy = false;
  let previousFocus = null;
  let stageChoices = [];
  let subscriptions = [];
  let editingFeedId = null;

  function setBusy(value) {
    busy = value;
    fields.disabled = value;
    editFields.disabled = value;
    list.querySelectorAll('button').forEach(button => { button.disabled = value; });
  }

  function showError(message) {
    error.textContent = message;
    error.classList.toggle('hidden', !message);
  }

  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => item.msg).join('. ')
        : data.detail;
      throw new Error(detail || 'Unable to manage calendar subscriptions.');
    }
    return data;
  }

  function renderList(feeds) {
    subscriptions = feeds;
    list.innerHTML = feeds.length ? feeds.map(feed => {
      const scope = feed.board_id === null ? 'All accessible hubs' : feed.board_name || 'Hub unavailable';
      const stageNames = (feed.stages || []).map(stage => feed.board_id === null
        ? `${stage.board_name}: ${stage.name}` : stage.name);
      const stageSummary = feed.stage_ids == null ? 'All stages'
        : stageNames.length ? `Stages: ${stageNames.join(', ')}` : 'No available stages';
      return `
        <div class="flex flex-wrap items-center justify-between gap-2 p-3 border border-gray-200 rounded-lg">
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-gray-800 break-words">${_escapeNavHtml(feed.name)}</div>
            <div class="text-xs text-gray-500 mt-1">${_escapeNavHtml(scope)}${feed.assigned_only ? ' · Assigned to you' : ''}</div>
            <div class="text-xs text-gray-500 mt-1 break-words">${_escapeNavHtml(stageSummary)}</div>
            <div class="text-xs text-gray-500 font-mono mt-1">URL ending …${_escapeNavHtml(feed.last_four)}</div>
          </div>
          <div class="flex flex-wrap gap-2">
            ${feed.available ? `<button type="button" data-calendar-action="stages" data-feed-id="${_escapeNavHtml(feed.id)}" class="px-2 py-1.5 rounded-lg border border-gray-300 text-xs disabled:opacity-60">Edit stages</button>` : ''}
            ${feed.available ? `<button type="button" data-calendar-action="rotate" data-feed-id="${_escapeNavHtml(feed.id)}" class="px-2 py-1.5 rounded-lg border border-gray-300 text-xs disabled:opacity-60">Regenerate URL</button>` : ''}
            <button type="button" data-calendar-action="revoke" data-feed-id="${_escapeNavHtml(feed.id)}" class="px-2 py-1.5 rounded-lg border border-red-200 text-red-700 text-xs disabled:opacity-60">Revoke</button>
          </div>
        </div>`;
    }).join('') : '<p class="text-sm text-gray-500 py-3">No calendar subscriptions yet.</p>';
  }

  function renderStagePicker(container, boardId, stageIds = null) {
    const choices = stageChoices.filter(stage => boardId == null || boardId === ''
      || String(stage.board_id) === String(boardId));
    const selected = new Set(stageIds || []);
    const all = stageIds === null;
    const groups = new Map();
    choices.forEach(stage => {
      if (!groups.has(stage.board_id)) groups.set(stage.board_id, {name: stage.board_name, stages: []});
      groups.get(stage.board_id).stages.push(stage);
    });
    const missing = (stageIds || []).filter(id => !choices.some(stage => stage.id === id)).length;
    container.innerHTML = `
      <label class="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" data-calendar-all-stages ${all ? 'checked' : ''}> All stages
      </label>
      <p data-calendar-stage-hint class="text-xs text-gray-500 mt-1"></p>
      ${missing ? '<p class="text-xs text-amber-700 mt-2">Some saved stages are unavailable. Saving keeps only your current selection.</p>' : ''}
      <div class="space-y-3 mt-3 max-h-56 overflow-y-auto">
        ${[...groups.values()].map(group => `
          <fieldset>
            ${boardId == null || boardId === '' ? `<legend class="text-xs font-semibold text-gray-700 mb-2">${_escapeNavHtml(group.name)}</legend>` : ''}
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              ${group.stages.map(stage => `
                <label class="flex items-start gap-2 text-sm text-gray-700 min-w-0">
                  <input type="checkbox" data-calendar-stage-id="${stage.id}" class="mt-1" ${all || selected.has(stage.id) ? 'checked' : ''}>
                  <span class="break-words min-w-0">${_escapeNavHtml(stage.name)}</span>
                </label>`).join('')}
            </div>
          </fieldset>`).join('') || '<p class="text-xs text-gray-500">No stages available in this scope.</p>'}
      </div>`;
    updateStageHint(container);
  }

  function updateStageHint(container) {
    const all = container.querySelector('[data-calendar-all-stages]').checked;
    container.querySelector('[data-calendar-stage-hint]').textContent = all
      ? 'Includes stages created later. Uncheck an individual stage to customize.'
      : 'Only checked stages are included. Select at least one stage.';
  }

  function stageSelection(container) {
    if (container.querySelector('[data-calendar-all-stages]')?.checked) return null;
    return [...container.querySelectorAll('[data-calendar-stage-id]:checked')]
      .map(input => Number(input.dataset.calendarStageId));
  }

  function requireStageSelection(container) {
    const selection = stageSelection(container);
    if (selection !== null && !selection.length) {
      showError('Select at least one stage, or choose All stages.');
      container.querySelector('[data-calendar-stage-id], [data-calendar-all-stages]')?.focus();
      return false;
    }
    return true;
  }

  function closeStageEditor(restoreFocus = true) {
    const id = editingFeedId;
    editingFeedId = null;
    editForm.classList.add('hidden');
    form.classList.remove('hidden');
    if (restoreFocus) {
      const trigger = [...list.querySelectorAll('[data-calendar-action="stages"]')]
        .find(button => button.dataset.feedId === id);
      (trigger || document.getElementById('calendar-feeds-close')).focus();
    }
  }

  function openStageEditor(feedId) {
    const feed = subscriptions.find(item => item.id === feedId);
    if (!feed) return;
    clearUrl();
    showError('');
    feedback.textContent = '';
    editingFeedId = feed.id;
    document.getElementById('calendar-feed-edit-title').textContent = `Stages for ${feed.name}`;
    renderStagePicker(editStagesInput, feed.board_id, feed.stage_ids);
    form.classList.add('hidden');
    editForm.classList.remove('hidden');
    editStagesInput.querySelector('[data-calendar-all-stages]').focus();
  }

  [stagesInput, editStagesInput].forEach(container => {
    container.addEventListener('change', event => {
      const all = container.querySelector('[data-calendar-all-stages]');
      if (event.target === all) {
        container.querySelectorAll('[data-calendar-stage-id]').forEach(input => { input.checked = all.checked; });
      } else if (event.target.matches('[data-calendar-stage-id]')) {
        all.checked = false;
      }
      updateStageHint(container);
      showError('');
    });
  });

  function clearUrl() {
    const hadFocus = createdPanel.contains(document.activeElement);
    urlInput.value = '';
    createdPanel.classList.add('hidden');
    if (isOpen && hadFocus) document.getElementById('calendar-feeds-close').focus();
  }

  function showUrl(url) {
    urlInput.value = url;
    createdPanel.classList.remove('hidden');
    urlInput.focus();
    urlInput.select();
  }

  function closeModal() {
    generation++;
    isOpen = false;
    clearUrl();
    closeStageEditor(false);
    modal.classList.add('hidden');
    previousFocus?.focus();
  }

  async function openModal(boardId) {
    const current = ++generation;
    previousFocus = document.activeElement;
    isOpen = true;
    const menuPanel = document.getElementById('nav-user-menu-panel');
    if (menuPanel && !menuPanel.classList.contains('hidden')) {
      previousFocus = document.getElementById('nav-user-menu-toggle');
      previousFocus?.click();
    }
    modal.classList.remove('hidden');
    document.getElementById('calendar-feeds-close').focus();
    clearUrl();
    showError('');
    feedback.textContent = 'Loading subscriptions…';
    list.innerHTML = '';
    form.reset();
    closeStageEditor(false);
    stageChoices = [];
    renderStagePicker(stagesInput, boardId);
    setBusy(true);
    try {
      const [feeds, boards, stages] = await Promise.all([
        api('/api/calendar-feeds'), api('/api/boards'), api('/api/calendar-feeds/stages'),
      ]);
      if (generation !== current) return;
      boardInput.innerHTML = '<option value="">All accessible hubs</option>' + boards.map(board =>
        `<option value="${board.id}">${_escapeNavHtml(board.name)}</option>`
      ).join('');
      boardInput.value = boards.some(board => String(board.id) === boardId) ? boardId : '';
      stageChoices = stages;
      renderStagePicker(stagesInput, boardInput.value);
      renderList(feeds);
      feedback.textContent = '';
    } catch (err) {
      if (generation === current) {
        showError(err.message);
        feedback.textContent = '';
      }
    } finally {
      if (generation === current) setBusy(false);
    }
  }

  async function mutate(action, message = 'Subscription revoked.', onSuccess = null) {
    if (busy) return;
    const current = generation;
    setBusy(true);
    showError('');
    feedback.textContent = '';
    try {
      const result = await action();
      if (generation !== current) return;
      clearUrl();
      if (result.subscription_url) showUrl(result.subscription_url);
      else {
        feedback.textContent = message;
        document.getElementById('calendar-feeds-close').focus();
      }
      const feeds = await api('/api/calendar-feeds');
      if (generation === current) {
        renderList(feeds);
        onSuccess?.();
      }
    } catch (err) {
      if (generation === current) showError(err.message);
    } finally {
      if (generation === current) setBusy(false);
    }
  }

  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-open-calendar-feeds]');
    if (trigger) openModal(trigger.dataset.boardId || '');
  });
  document.getElementById('calendar-feeds-close').addEventListener('click', closeModal);
  modal.addEventListener('click', event => { if (event.target === modal) closeModal(); });
  document.addEventListener('keydown', event => {
    if (!isOpen) return;
    if (event.key === 'Escape') closeModal();
    if (event.key === 'Tab') {
      const focusable = [...modal.querySelectorAll('button, input, select, textarea')]
        .filter(element => !element.matches(':disabled') && element.getClientRects().length);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!modal.contains(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!requireStageSelection(stagesInput)) return;
    mutate(() => api('/api/calendar-feeds', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: nameInput.value.trim(),
        board_id: boardInput.value ? Number(boardInput.value) : null,
        assigned_only: assignedInput.checked,
        stage_ids: stageSelection(stagesInput),
      }),
    }));
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-calendar-action]');
    if (!button || busy) return;
    if (button.dataset.calendarAction === 'stages') {
      openStageEditor(button.dataset.feedId);
      return;
    }
    const rotate = button.dataset.calendarAction === 'rotate';
    const message = rotate
      ? 'Regenerate this subscription URL? The previous URL will stop working. Update it in your calendar app.'
      : 'Revoke this subscription? Its URL will stop working. Calendar apps may keep previously downloaded entries.';
    if (!window.confirm(message)) return;
    mutate(() => api(`/api/calendar-feeds/${button.dataset.feedId}${rotate ? '/rotate' : ''}`, {
      method: rotate ? 'POST' : 'DELETE',
    }));
  });
  boardInput.addEventListener('change', () => renderStagePicker(stagesInput, boardInput.value));
  document.getElementById('calendar-feed-edit-cancel').addEventListener('click', () => closeStageEditor());
  editForm.addEventListener('submit', event => {
    event.preventDefault();
    if (!editingFeedId || !requireStageSelection(editStagesInput)) return;
    mutate(() => api(`/api/calendar-feeds/${editingFeedId}`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({stage_ids: stageSelection(editStagesInput)}),
    }), 'Stages updated. Your calendar will reflect the selection on its next refresh.', () => closeStageEditor());
  });
  document.getElementById('calendar-feed-saved').addEventListener('click', clearUrl);
  document.getElementById('calendar-feed-copy').addEventListener('click', async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(urlInput.value);
      else {
        urlInput.focus();
        urlInput.select();
        if (!document.execCommand('copy')) throw new Error('Clipboard unavailable');
      }
      feedback.textContent = 'Subscription URL copied.';
    } catch {
      urlInput.focus();
      urlInput.select();
      feedback.textContent = 'Select and copy the subscription URL above.';
    }
  });
});

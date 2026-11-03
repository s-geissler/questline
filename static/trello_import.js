/* Shared Trello import dialog for the Hub overview and Hub Settings. */
let activeTrelloImportDialog = null;

class TrelloImportDialog {
  constructor({boardId = null, boardName = ''} = {}) {
    this.boardId = boardId;
    this.boardName = boardName;
    this.file = null;
    this.preview = null;
    this.busy = false;
    this.error = '';
    this.confirmed = false;
    this.returnFocus = document.activeElement;
    this.root = document.createElement('div');
    document.body.append(this.root);
    this.keyHandler = event => this.handleKeydown(event);
    document.addEventListener('keydown', this.keyHandler, true);
    this.root.addEventListener('click', event => {
      const action = event.target.closest('[data-trello-action]')?.dataset.trelloAction;
      if (action === 'cancel') this.close();
      if (action === 'import') this.importFile();
    });
    this.root.addEventListener('change', event => {
      if (event.target.matches('[data-trello-file]')) {
        this.file = event.target.files[0] || null;
        this.confirmed = false;
        this.preview = null;
        this.loadPreview();
      }
      if (event.target.matches('[data-trello-confirm]')) {
        this.confirmed = event.target.checked;
        this.root.querySelector('[data-trello-action="import"]').disabled = !this.confirmed;
      }
    });
    this.render();
    this.root.querySelector('[data-trello-file]').focus();
  }

  close() {
    if (this.busy) return;
    document.removeEventListener('keydown', this.keyHandler, true);
    this.root.remove();
    activeTrelloImportDialog = null;
    this.returnFocus?.focus();
  }

  handleKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      this.close();
    }
    if (event.key === 'Tab') {
      const focusable = [...this.root.querySelectorAll('button:not([disabled]), input:not([disabled])')];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  }

  async upload(path) {
    const body = new FormData();
    body.append('file', this.file);
    if (this.boardId !== null) body.append('board_id', String(this.boardId));
    if (path === '/api/boards/import-trello' && this.boardId !== null) {
      body.append('confirm_replace', 'true');
    }
    const response = await fetch(path, {method: 'POST', body});
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Unable to import this export.');
    }
    return payload;
  }

  async loadPreview() {
    this.error = '';
    if (!this.file) {
      this.render();
      return;
    }
    if (this.file.size > 10 * 1024 * 1024) {
      this.error = 'Trello export exceeds the 10 MiB size limit.';
      this.render();
      return;
    }
    this.busy = true;
    this.render();
    try {
      this.preview = await this.upload('/api/boards/import-trello/preview');
    } catch (error) {
      this.error = error.message || 'Unable to read this export.';
    } finally {
      this.busy = false;
      this.render();
      this.root.querySelector('[data-trello-confirm], [data-trello-action="import"]')?.focus();
    }
  }

  async importFile() {
    if (this.busy || !this.preview || (this.boardId !== null && !this.confirmed)) return;
    this.busy = true;
    this.error = '';
    this.render();
    try {
      const result = await this.upload('/api/boards/import-trello');
      window.location.assign(`/board/${result.board_id}`);
    } catch (error) {
      this.error = error.message || 'Unable to import this export.';
      this.busy = false;
      this.render();
    }
  }

  render() {
    const escape = _escapeNavHtml;
    const count = (value, singular) => `${value} ${singular}${value === 1 ? '' : 's'}`;
    const replacing = this.boardId !== null;
    const preview = this.preview;
    const target = preview?.target_board;
    this.root.innerHTML = `
      <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
        <section role="dialog" aria-modal="true" aria-labelledby="trello-import-title" aria-busy="${this.busy}"
          class="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6">
          <h2 id="trello-import-title" class="text-lg font-bold text-gray-800 mb-3">Import from Trello</h2>
          <p class="text-sm text-gray-600 mb-4">${replacing
            ? `Replace the content of “${escape(target?.name || this.boardName)}” with a Trello board export.`
            : 'Create a new Hub from a Trello board JSON export.'}</p>
          <label class="block text-sm font-medium text-gray-800 mb-2" for="trello-import-file">Trello JSON file (up to 10 MiB)</label>
          <input id="trello-import-file" type="file" accept=".json,application/json" data-trello-file
            ${this.busy ? 'disabled' : ''} class="block w-full text-sm mb-3">
          ${this.file ? `<p class="text-xs text-gray-500 mb-3">Selected: ${escape(this.file.name)}</p>` : ''}
          <p class="text-xs text-gray-500 mb-4">Archived cards, custom fields, labels, and Trello configuration are skipped. Assignees and attachment links are added as Markdown notes in each Objective’s description for manual transfer.</p>
          ${preview ? `
            <div class="border rounded-xl p-3 mb-4 text-sm text-gray-700" aria-live="polite">
              <p class="font-semibold mb-2">${escape(preview.name)}</p>
              <p>${count(preview.stage_count, 'Stage')} · ${count(preview.task_count, 'Objective')} · ${count(preview.checklist_item_count, 'checklist item')}</p>
              <p class="text-xs text-gray-500 mt-1">${count(preview.skipped_archived_card_count, 'archived card')} skipped.</p>
            </div>
            ${replacing ? `
              <div class="border border-red-200 rounded-xl p-3 mb-4 text-sm text-red-700">
                <p>This will delete ${count(target.stage_count, 'existing Stage')}, ${count(target.task_count, 'Objective')} and their associated data, and remove all automations (${target.automation_count}).</p>
                <p class="mt-2">The Hub name and members are kept. Calendar Stage selections and Quest spawn-stage settings will need reconfiguration.</p>
                <label class="flex items-start gap-2 mt-3">
                  <input type="checkbox" data-trello-confirm ${this.confirmed ? 'checked' : ''} ${this.busy ? 'disabled' : ''}>
                  <span>I understand and want to replace this Hub’s content.</span>
                </label>
              </div>` : ''}
          ` : ''}
          ${this.error ? `<p role="alert" class="text-sm text-red-600 mb-4">${escape(this.error)}</p>` : ''}
          ${this.busy ? '<p role="status" class="text-sm text-gray-500 mb-4">Processing Trello export…</p>' : ''}
          <div class="flex justify-end gap-2 border-t pt-4">
            <button type="button" data-trello-action="cancel" ${this.busy ? 'disabled' : ''}
              class="text-gray-500 hover:text-gray-700 px-4 py-2 text-sm">Cancel</button>
            <button type="button" data-trello-action="import" ${this.busy || !preview || (replacing && !this.confirmed) ? 'disabled' : ''}
              class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50">${replacing ? 'Replace content' : 'Create Hub'}</button>
          </div>
        </section>
      </div>`;
    // Rendering progress/preview must not clear the browser's selected filename.
    if (this.file && typeof File !== 'undefined' && this.file instanceof File && typeof DataTransfer !== 'undefined') {
      const transfer = new DataTransfer();
      transfer.items.add(this.file);
      this.root.querySelector('[data-trello-file]').files = transfer.files;
    }
  }
}

function openTrelloImport(options) {
  if (activeTrelloImportDialog) return;
  activeTrelloImportDialog = new TrelloImportDialog(options);
}

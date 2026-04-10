function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function boardHeaderClass(board) {
  const color = board?.color || '#2563eb';
  return `swatch-${String(color).replace('#', '')}`;
}

function boardRoleClasses(board) {
  if (board.role === 'admin') return 'bg-fuchsia-400/25 border-fuchsia-200/30';
  if (board.role === 'owner') return 'bg-white/20 border-white/25';
  if (board.role === 'editor') return 'bg-amber-400/25 border-amber-200/30';
  return 'bg-emerald-400/25 border-emerald-200/30';
}

function boardRoleLabel(board) {
  if (!board.role) return '';
  return board.role.charAt(0).toUpperCase() + board.role.slice(1);
}

function canManageBoard(board) {
  return board.role === 'owner' || board.role === 'admin';
}

class HomePageController {
  constructor(root) {
    this.root = root;
    this.grid = root.querySelector('#home-boards-grid');
    this.emptyState = root.querySelector('#home-empty-state');
    this.createForm = root.querySelector('#home-create-form');
    this.newBoardNameInput = root.querySelector('#home-new-board-name');
    this.boards = [];
    this.showCreate = false;
    this.actionMenuBoardId = null;
    this.bindEvents();
  }

  bindEvents() {
    this.root.addEventListener('click', event => this.handleClick(event));
    this.root.addEventListener('input', event => this.handleInput(event));
    this.root.addEventListener('keydown', event => this.handleKeydown(event));
    this.root.addEventListener('blur', event => this.handleBlur(event), true);
    document.addEventListener('click', event => this.handleDocumentClick(event));
  }

  async init() {
    const res = await fetch('/api/boards');
    this.boards = (await res.json()).map(board => this.normalizeBoard(board));
    this.render();
  }

  normalizeBoard(board) {
    return {
      ...board,
      editing: false,
      editName: board.name,
    };
  }

  render() {
    this.createForm.classList.toggle('hidden', !this.showCreate);
    this.emptyState.classList.toggle('hidden', this.boards.length > 0);
    this.grid.innerHTML = this.boards.map(board => this.renderBoard(board)).join('');
  }

  renderBoard(board) {
    const roleBadge = board.role
      ? `<span class="text-[11px] px-1.5 py-0.5 rounded-full text-white font-medium border flex-shrink-0 ${boardRoleClasses(board)}">${escapeHtml(boardRoleLabel(board))}</span>`
      : '';
    const footer = canManageBoard(board) ? this.renderBoardFooter(board) : '';
    return `
      <div class="bg-white rounded-xl shadow hover:shadow-md transition-shadow overflow-visible flex flex-col">
        <a href="/board/${board.id}" class="block p-5 h-24 flex items-end hover:opacity-90 transition-opacity ${boardHeaderClass(board)}">
          <div class="flex items-end justify-between gap-3 w-full">
            <span class="text-white font-bold text-base leading-tight drop-shadow">${escapeHtml(board.name)}</span>
            ${roleBadge}
          </div>
        </a>
        ${footer}
      </div>
    `;
  }

  renderBoardFooter(board) {
    if (board.editing) {
      return `
        <div class="px-3 py-2 border-t">
          <input
            type="text"
            data-role="rename-input"
            data-board-id="${board.id}"
            value="${escapeHtml(board.editName)}"
            class="w-full text-sm border-b border-blue-400 focus:outline-none py-0.5 bg-transparent"
          >
        </div>
      `;
    }

    const menuOpen = this.actionMenuBoardId === board.id;
    return `
      <div class="px-3 py-2 border-t">
        <div class="relative flex justify-end">
          <button
            type="button"
            data-action="toggle-menu"
            data-board-id="${board.id}"
            class="text-gray-400 hover:text-gray-600 px-2 py-1 rounded hover:bg-gray-100 transition-colors text-lg leading-none"
            title="Hub actions"
          >☰</button>
          <div class="${menuOpen ? '' : 'hidden '}absolute top-full right-0 mt-1 bg-white text-gray-800 shadow-xl rounded-xl py-1 min-w-[140px] z-20" data-role="board-menu" data-board-id="${board.id}">
            <button
              type="button"
              data-action="start-edit"
              data-board-id="${board.id}"
              class="block w-full text-left text-xs text-gray-600 hover:text-blue-600 px-3 py-2 hover:bg-gray-100 transition-colors"
            >Rename</button>
            <button
              type="button"
              data-action="delete-board"
              data-board-id="${board.id}"
              class="block w-full text-left text-xs text-gray-600 hover:text-red-600 px-3 py-2 hover:bg-gray-100 transition-colors"
            >Delete</button>
          </div>
        </div>
      </div>
    `;
  }

  boardById(boardId) {
    return this.boards.find(board => board.id === boardId) || null;
  }

  openCreateForm() {
    this.showCreate = true;
    this.render();
    this.newBoardNameInput?.focus();
  }

  closeCreateForm() {
    this.showCreate = false;
    if (this.newBoardNameInput) {
      this.newBoardNameInput.value = '';
    }
    this.render();
  }

  async createBoard() {
    const name = this.newBoardNameInput?.value?.trim() || '';
    if (!name) return;
    const res = await fetch('/api/boards', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name}),
    });
    if (!res.ok) return;
    const board = await res.json();
    this.boards.push(this.normalizeBoard(board));
    this.closeCreateForm();
  }

  async saveBoardName(boardId) {
    const board = this.boardById(boardId);
    if (!board) return;
    const nextName = board.editName.trim();
    if (!nextName || nextName === board.name) {
      board.editing = false;
      board.editName = board.name;
      this.render();
      return;
    }
    const res = await fetch(`/api/boards/${board.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: nextName}),
    });
    if (!res.ok) {
      board.editing = false;
      board.editName = board.name;
      this.render();
      return;
    }
    board.name = nextName;
    board.editName = nextName;
    board.editing = false;
    this.render();
  }

  startEdit(boardId) {
    const board = this.boardById(boardId);
    if (!board) return;
    this.actionMenuBoardId = null;
    board.editing = true;
    board.editName = board.name;
    this.render();
    const input = this.root.querySelector(`[data-role="rename-input"][data-board-id="${board.id}"]`);
    input?.focus();
    input?.select();
  }

  async deleteBoard(boardId) {
    const board = this.boardById(boardId);
    if (!board) return;
    if (!confirm(`Delete hub "${board.name}" and all its content?`)) return;
    const res = await fetch(`/api/boards/${board.id}`, {method: 'DELETE'});
    if (!res.ok) return;
    this.boards = this.boards.filter(entry => entry.id !== board.id);
    this.actionMenuBoardId = null;
    this.render();
  }

  toggleBoardMenu(boardId) {
    this.actionMenuBoardId = this.actionMenuBoardId === boardId ? null : boardId;
    this.render();
  }

  closeBoardMenu() {
    if (this.actionMenuBoardId === null) return;
    this.actionMenuBoardId = null;
    this.render();
  }

  handleClick(event) {
    const actionTarget = event.target.closest('[data-action]');
    if (!actionTarget) return;
    const action = actionTarget.dataset.action;
    const boardId = Number.parseInt(actionTarget.dataset.boardId || '', 10);

    if (action === 'open-create') {
      this.openCreateForm();
      return;
    }
    if (action === 'cancel-create') {
      this.closeCreateForm();
      return;
    }
    if (action === 'create-board') {
      this.createBoard();
      return;
    }
    if (action === 'toggle-menu' && !Number.isNaN(boardId)) {
      event.preventDefault();
      event.stopPropagation();
      this.toggleBoardMenu(boardId);
      return;
    }
    if (action === 'start-edit' && !Number.isNaN(boardId)) {
      event.preventDefault();
      event.stopPropagation();
      this.startEdit(boardId);
      return;
    }
    if (action === 'delete-board' && !Number.isNaN(boardId)) {
      event.preventDefault();
      event.stopPropagation();
      this.deleteBoard(boardId);
    }
  }

  handleInput(event) {
    const renameInput = event.target.closest('[data-role="rename-input"]');
    if (!renameInput) return;
    const boardId = Number.parseInt(renameInput.dataset.boardId || '', 10);
    const board = this.boardById(boardId);
    if (!board) return;
    board.editName = renameInput.value;
  }

  handleKeydown(event) {
    const renameInput = event.target.closest('[data-role="rename-input"]');
    if (renameInput) {
      const boardId = Number.parseInt(renameInput.dataset.boardId || '', 10);
      const board = this.boardById(boardId);
      if (!board) return;
      if (event.key === 'Enter') {
        renameInput.blur();
      } else if (event.key === 'Escape') {
        board.editing = false;
        board.editName = board.name;
        this.render();
      }
      return;
    }

    if (event.target === this.newBoardNameInput) {
      if (event.key === 'Enter') {
        this.createBoard();
      } else if (event.key === 'Escape') {
        this.closeCreateForm();
      }
    }
  }

  handleBlur(event) {
    const renameInput = event.target.closest('[data-role="rename-input"]');
    if (!renameInput) return;
    const boardId = Number.parseInt(renameInput.dataset.boardId || '', 10);
    this.saveBoardName(boardId);
  }

  handleDocumentClick(event) {
    if (this.actionMenuBoardId === null) return;
    if (!this.root.contains(event.target)) {
      this.closeBoardMenu();
      return;
    }
    if (!event.target.closest('[data-action="toggle-menu"]') && !event.target.closest('[data-role="board-menu"]')) {
      this.closeBoardMenu();
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('home-page');
  if (!root) return;
  const controller = new HomePageController(root);
  controller.init();
});

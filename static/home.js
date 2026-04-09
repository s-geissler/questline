function homePage() {
  return {
    boards: [],
    showCreate: false,
    newName: '',
    actionMenuBoardId: null,

    get hasBoards() {
      return this.boards.length > 0;
    },

    async init() {
      const res = await fetch('/api/boards');
      this.boards = (await res.json()).map(b => ({...b, editing: false, editName: b.name}));
    },

    openCreateForm() {
      this.showCreate = true;
      this.$nextTick(() => this.$refs.newBoardName?.focus());
    },

    closeCreateForm() {
      this.showCreate = false;
      this.newName = '';
    },

    async createBoard() {
      if (!this.newName.trim()) return;
      const res = await fetch('/api/boards', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: this.newName.trim()}),
      });
      if (!res.ok) return;
      const board = await res.json();
      this.boards.push({...board, editing: false, editName: board.name});
      this.closeCreateForm();
    },

    startEdit(board) {
      this.closeBoardMenu();
      board.editing = true;
      board.editName = board.name;
      this.$nextTick(() => document.getElementById(this.renameInputId(board))?.focus());
    },

    async saveBoardName(board) {
      if (!board.editName.trim() || board.editName.trim() === board.name) {
        board.editing = false;
        return;
      }
      const res = await fetch(`/api/boards/${board.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: board.editName.trim()}),
      });
      if (!res.ok) {
        board.editName = board.name;
        board.editing = false;
        return;
      }
      board.name = board.editName.trim();
      board.editing = false;
    },

    async deleteBoard(board) {
      if (!confirm(`Delete hub "${board.name}" and all its content?`)) return;
      const res = await fetch(`/api/boards/${board.id}`, {method: 'DELETE'});
      if (!res.ok) return;
      this.boards = this.boards.filter(b => b.id !== board.id);
    },

    boardHref(board) {
      return `/board/${board.id}`;
    },

    boardHeaderStyle(board) {
      return `background:${board.color || '#2563eb'}`;
    },

    boardRoleClasses(board) {
      if (board.role === 'admin') return 'bg-fuchsia-400/25 border-fuchsia-200/30';
      if (board.role === 'owner') return 'bg-white/20 border-white/25';
      if (board.role === 'editor') return 'bg-amber-400/25 border-amber-200/30';
      return 'bg-emerald-400/25 border-emerald-200/30';
    },

    boardRoleLabel(board) {
      if (!board.role) return '';
      return board.role.charAt(0).toUpperCase() + board.role.slice(1);
    },

    canManageBoard(board) {
      return board.role === 'owner' || board.role === 'admin';
    },

    renameInputId(board) {
      return `rename-${board.id}`;
    },

    isBoardMenuOpen(board) {
      return this.actionMenuBoardId === board.id;
    },

    toggleBoardMenu(board) {
      this.actionMenuBoardId = this.isBoardMenuOpen(board) ? null : board.id;
    },

    closeBoardMenu() {
      this.actionMenuBoardId = null;
    },
  };
}

document.addEventListener('alpine:init', () => {
  Alpine.data('homePage', homePage);
});

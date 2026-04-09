function homePage() {
  return {
    boards: [],
    showCreate: false,
    newName: '',

    async init() {
      const res = await fetch('/api/boards');
      this.boards = (await res.json()).map(b => ({...b, editing: false, editName: b.name}));
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
      this.newName = '';
      this.showCreate = false;
    },

    startEdit(board) {
      board.editing = true;
      board.editName = board.name;
      this.$nextTick(() => document.getElementById('rename-' + board.id)?.focus());
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
  };
}

document.addEventListener('alpine:init', () => {
  Alpine.data('homePage', homePage);
});

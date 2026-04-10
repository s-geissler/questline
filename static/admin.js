function _escapeAdminHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function _createAdmin() {
  return {
    currentUserId: null,
    users: [],
    boards: [],
    settings: {},
    savingSettings: false,
    userSearch: '',
    passwordDialogUserId: null,
    savingPasswordForUserId: null,
    openActionsUserId: null,
    deletingUserId: null,
    deletingBoardId: null,
    deletingOrphanedBoards: false,
    _selectedBoardColor: '#3b82f6',
    _selectedThemeColor: '#1d4ed8',

    async init() {
      const root = document.getElementById('admin-root');
      this.currentUserId = parseInt(root?.dataset.currentUserId || '0', 10);

      const settingsRes = await fetch('/api/admin/settings');
      if (!settingsRes.ok) {
        this.showError('Unable to load admin data');
        return;
      }
      this.settings = await settingsRes.json();
      const loaded = await this.reloadAdminEntities();
      if (!loaded) return;
      this.populateSettings();
      this.bindEvents();
    },

    async reloadAdminEntities() {
      const [usersRes, boardsRes] = await Promise.all([
        fetch('/api/admin/users'),
        fetch('/api/admin/boards'),
      ]);
      if (!usersRes.ok || !boardsRes.ok) {
        this.showError('Unable to load admin data');
        return false;
      }
      this.users = await usersRes.json();
      this.boards = await boardsRes.json();
      this.renderUsers();
      this.renderBoards();
      this.renderGlobalActions();
      return true;
    },

    renderGlobalActions() {
      const btn = document.getElementById('admin-delete-orphaned-boards-btn');
      const note = document.getElementById('admin-global-actions-note');
      const orphanedCount = this.boards.filter(board => board.is_orphan).length;
      if (btn) {
        btn.disabled = this.deletingOrphanedBoards || orphanedCount === 0;
        btn.textContent = this.deletingOrphanedBoards
          ? 'Deleting orphaned hubs...'
          : 'Delete all orphaned hubs';
      }
      if (note) {
        note.textContent = orphanedCount === 0
          ? 'No orphaned hubs found.'
          : `${orphanedCount} orphaned ${orphanedCount === 1 ? 'hub is' : 'hubs are'} currently available for cleanup.`;
      }
    },

    _renderColorSwatches(containerId, selectedColor, dataAction, colors = PRESET_COLORS) {
      const el = document.getElementById(containerId);
      if (!el) return;
      el.innerHTML = colors.map(color => {
        const token = color.replace('#', '');
        const isSelected = color === selectedColor;
        const ring = isSelected ? 'ring-2 ring-offset-1 ring-gray-700' : '';
        return `<button
          type="button"
          data-action="${dataAction}"
          data-color="${color}"
          class="w-8 h-8 rounded-full hover:scale-110 transition-transform border-2 border-black/10 swatch-${token} ${ring}"
          title="${color}"
        ></button>`;
      }).join('');
    },

    populateSettings() {
      const s = this.settings;
      const get = id => document.getElementById(id);
      const cb = get('settings-registration-enabled');
      if (cb) cb.checked = !!s.registration_enabled;
      const cb2 = get('settings-new-accounts-active');
      if (cb2) cb2.checked = !!s.new_accounts_active_by_default;

      this._selectedBoardColor = s.default_board_color || '#3b82f6';
      this._selectedThemeColor = s.instance_theme_color || '#1d4ed8';
      this._renderColorSwatches('settings-default-board-color-swatches', this._selectedBoardColor, 'select-board-color', PRESET_COLORS);
      this._renderColorSwatches('settings-instance-theme-color-swatches', this._selectedThemeColor, 'select-theme-color', PAGE_THEME_COLORS);

      const interval = get('settings-recurrence-interval');
      if (interval) interval.value = s.recurrence_worker_interval_seconds ?? 60;
    },

    readSettings() {
      const get = id => document.getElementById(id);
      return {
        registration_enabled: get('settings-registration-enabled')?.checked ?? false,
        new_accounts_active_by_default: get('settings-new-accounts-active')?.checked ?? false,
        default_board_color: this._selectedBoardColor || '#3b82f6',
        instance_theme_color: this._selectedThemeColor || '#1d4ed8',
        recurrence_worker_interval_seconds: parseInt(get('settings-recurrence-interval')?.value || '60', 10),
      };
    },

    bindEvents() {
      document.getElementById('admin-root')?.addEventListener('click', event => {
        const target = event.target.closest('[data-action]');
        const action = target?.dataset.action;
        if (!target) return;
        event.stopPropagation();
        if (action === 'save-settings') { this.saveSettings(); return; }
        if (action === 'select-board-color') {
          this._selectedBoardColor = target.dataset.color;
          this._renderColorSwatches('settings-default-board-color-swatches', this._selectedBoardColor, 'select-board-color', PRESET_COLORS);
          return;
        }
        if (action === 'delete-orphaned-boards') {
          this.deleteOrphanedBoards();
          return;
        }
        if (action === 'select-theme-color') {
          this._selectedThemeColor = target.dataset.color;
          this._renderColorSwatches('settings-instance-theme-color-swatches', this._selectedThemeColor, 'select-theme-color', PAGE_THEME_COLORS);
          return;
        }
        if (action === 'update-user-status') {
          const userId = parseInt(target.dataset.userId, 10);
          const user = this.users.find(u => u.id === userId);
          if (user) this.updateUserStatus(user, target.dataset.value === 'active');
          return;
        }
        if (action === 'clear-password-reset-request') {
          const userId = parseInt(target.dataset.userId, 10);
          const user = this.users.find(u => u.id === userId);
          if (user) this.updatePasswordResetRequested(user, false);
          this.openActionsUserId = null;
          this.renderUsers();
          return;
        }
        if (action === 'open-set-password-dialog') {
          const userId = parseInt(target.dataset.userId, 10);
          const user = this.users.find(u => u.id === userId);
          if (user) this.openPasswordDialog(user);
          this.openActionsUserId = null;
          this.renderUsers();
          return;
        }
        if (action === 'toggle-user-actions') {
          const userId = parseInt(target.dataset.userId, 10);
          this.openActionsUserId = this.openActionsUserId === userId ? null : userId;
          this.renderUsers();
          return;
        }
        if (action === 'delete-user') {
          const userId = parseInt(target.dataset.userId, 10);
          const user = this.users.find(u => u.id === userId);
          if (user) this.deleteUser(user);
          this.openActionsUserId = null;
          this.renderUsers();
          return;
        }
        if (action === 'delete-board') {
          const boardId = parseInt(target.dataset.boardId, 10);
          const board = this.boards.find(b => b.id === boardId);
          if (board) this.deleteBoard(board);
          return;
        }
        this.openActionsUserId = null;
        this.renderUsers();
      });

      document.addEventListener('click', event => {
        if (this.openActionsUserId === null) return;
        if (event.target.closest('#admin-root')) return;
        this.openActionsUserId = null;
        this.renderUsers();
      });

      document.getElementById('admin-users-list')?.addEventListener('change', event => {
        const field = event.target.dataset.field;
        const userId = parseInt(event.target.dataset.userId, 10);
        const user = this.users.find(u => u.id === userId);
        if (!user) return;
        if (field === 'user-status') this.updateUserStatus(user, event.target.value === 'active');
        if (field === 'user-role') this.updateUserRole(user, event.target.value);
      });

      document.getElementById('admin-user-search')?.addEventListener('input', event => {
        this.userSearch = event.target.value || '';
        this.renderUsers();
      });

      document.getElementById('admin-password-form')?.addEventListener('submit', event => {
        event.preventDefault();
        this.submitPasswordDialog();
      });

      document.getElementById('admin-password-cancel-btn')?.addEventListener('click', () => {
        this.closePasswordDialog();
      });

      document.getElementById('admin-password-dialog')?.addEventListener('close', () => {
        this.resetPasswordDialog();
      });

      document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && this.openActionsUserId !== null) {
          this.openActionsUserId = null;
          this.renderUsers();
        }
      });
    },

    getFilteredUsers() {
      const query = this.userSearch.trim().toLowerCase();
      if (!query) return this.users;
      return this.users.filter(user => {
        const displayName = String(user.display_name || '').toLowerCase();
        const email = String(user.email || '').toLowerCase();
        return displayName.includes(query) || email.includes(query);
      });
    },

    renderUsers() {
      const el = document.getElementById('admin-users-list');
      if (!el) return;
      if (!this.users.length) {
        el.innerHTML = '<div class="px-5 py-4 text-sm text-gray-500">No users found.</div>';
        return;
      }
      const filteredUsers = this.getFilteredUsers();
      if (!filteredUsers.length) {
        el.innerHTML = '<div class="px-5 py-4 text-sm text-gray-500">No users match that search.</div>';
        return;
      }
      el.innerHTML = filteredUsers.map(user => {
        const youBadge = user.id === this.currentUserId
          ? '<div class="text-xs text-blue-500 mt-0.5">You</div>'
          : '';
        const statusSelect = `
          <select data-field="user-status" data-user-id="${user.id}" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <option value="active"${user.is_active ? ' selected' : ''}>Active</option>
            <option value="inactive"${!user.is_active ? ' selected' : ''}>Inactive</option>
          </select>
        `;
        const roleSelect = `
          <select data-field="user-role" data-user-id="${user.id}" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <option value="user"${user.role === 'user' ? ' selected' : ''}>User</option>
            <option value="admin"${user.role === 'admin' ? ' selected' : ''}>Admin</option>
          </select>
        `;
        const recoveryStatus = user.password_reset_requested
          ? '<span class="inline-flex items-center rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-xs font-medium">Requested</span>'
          : '<span class="text-sm text-gray-400">None</span>';
        const savingPassword = this.savingPasswordForUserId === user.id;
        const deletingUser = this.deletingUserId === user.id;
        const actionsOpen = this.openActionsUserId === user.id;
        const rowLayerClass = actionsOpen ? 'relative z-20' : 'relative z-0';
        const clearRecoveryAction = user.password_reset_requested
          ? `<button type="button" data-action="clear-password-reset-request" data-user-id="${user.id}" class="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50">Clear recovery request</button>`
          : '';
        const actionsMenu = `
          <div class="relative">
            <button
              type="button"
              data-action="toggle-user-actions"
              data-user-id="${user.id}"
              class="inline-flex items-center justify-center whitespace-nowrap rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              aria-expanded="${actionsOpen ? 'true' : 'false'}"
            >Actions</button>
            ${actionsOpen ? `
              <div class="absolute right-0 z-10 mt-2 min-w-52 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg">
                <button
                  type="button"
                  data-action="open-set-password-dialog"
                  data-user-id="${user.id}"
                  class="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                  ${savingPassword ? 'disabled' : ''}
                >${savingPassword ? 'Saving...' : 'Set password'}</button>
                ${clearRecoveryAction}
                <button
                  type="button"
                  data-action="delete-user"
                  data-user-id="${user.id}"
                  class="admin-danger-action block w-full px-3 py-2 text-left text-sm text-red-600 disabled:cursor-not-allowed disabled:opacity-60"
                  ${deletingUser ? 'disabled' : ''}
                >${deletingUser ? 'Deleting...' : 'Delete user'}</button>
              </div>
            ` : ''}
          </div>
        `;
        return `
          <div class="admin-users-grid ${rowLayerClass} gap-4 px-5 py-3 border-b items-center">
            <div class="min-w-0">
              <div class="text-sm font-medium text-gray-800">${_escapeAdminHtml(user.display_name)}</div>
              ${youBadge}
            </div>
            <div class="text-sm text-gray-600 truncate">${_escapeAdminHtml(user.email)}</div>
            <div class="text-sm text-gray-500">${_escapeAdminHtml(user.board_count)}</div>
            <div>${statusSelect}</div>
            <div>${roleSelect}</div>
            <div>${recoveryStatus}</div>
            <div>${actionsMenu}</div>
          </div>
        `;
      }).join('');
    },

    renderBoards() {
      const el = document.getElementById('admin-boards-list');
      if (!el) return;
      if (!this.boards.length) {
        el.innerHTML = '<div class="px-5 py-4 text-sm text-gray-500">No boards found.</div>';
        return;
      }
      el.innerHTML = this.boards.map(board => {
        const token = (board.color || '#3b82f6').replace('#', '');
        const owner = board.owner_display_name
          ? `
            <div class="min-w-0">
              <div class="text-sm font-medium text-gray-800">${_escapeAdminHtml(board.owner_display_name)}</div>
              <div class="text-xs text-gray-500 truncate">${_escapeAdminHtml(board.owner_email || '')}</div>
            </div>
          `
          : '<span class="text-sm text-gray-400">No owner</span>';
        const status = board.is_orphan
          ? '<span class="inline-flex items-center rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-xs font-medium">Orphaned</span>'
          : '<span class="inline-flex items-center rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5 text-xs font-medium">Owned</span>';
        const deletingBoard = this.deletingBoardId === board.id;
        return `
          <div class="admin-boards-grid gap-4 px-5 py-3 border-b items-center">
            <div class="min-w-0 flex items-center gap-3">
              <span class="w-3 h-3 rounded-full flex-shrink-0 border border-black/10 swatch-${_escapeAdminHtml(token)}"></span>
              <div class="min-w-0">
                <div class="text-sm font-medium text-gray-800 truncate">${_escapeAdminHtml(board.name)}</div>
                <div class="text-xs text-gray-500">Board #${_escapeAdminHtml(board.id)}</div>
              </div>
            </div>
            <div>${owner}</div>
            <div class="text-sm text-gray-500">${_escapeAdminHtml(board.member_count)}</div>
            <div>${status}</div>
            <div>
              <button
                type="button"
                data-action="delete-board"
                data-board-id="${board.id}"
                class="admin-danger-action inline-flex items-center justify-center whitespace-nowrap rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-red-600 disabled:cursor-not-allowed disabled:opacity-60"
                ${deletingBoard ? 'disabled' : ''}
              >${deletingBoard ? 'Deleting...' : 'Delete board'}</button>
            </div>
          </div>
        `;
      }).join('');
    },

    openPasswordDialog(user) {
      const dialog = document.getElementById('admin-password-dialog');
      const description = document.getElementById('admin-password-dialog-description');
      if (!dialog || typeof dialog.showModal !== 'function') return;
      this.passwordDialogUserId = user.id;
      if (description) {
        description.textContent = `Store a new password for ${user.display_name || user.email}. This will sign them out of existing sessions.`;
      }
      this.setPasswordFormError('');
      this.setPasswordSubmitting(false);
      dialog.showModal();
      document.getElementById('admin-password-input')?.focus();
    },

    closePasswordDialog() {
      document.getElementById('admin-password-dialog')?.close();
    },

    resetPasswordDialog() {
      this.passwordDialogUserId = null;
      const form = document.getElementById('admin-password-form');
      if (form) form.reset();
      this.setPasswordFormError('');
      this.setPasswordSubmitting(false);
    },

    setPasswordFormError(message) {
      const el = document.getElementById('admin-password-form-error');
      if (!el) return;
      el.textContent = message;
      el.classList.toggle('hidden', !message);
    },

    setPasswordSubmitting(value) {
      const submitBtn = document.getElementById('admin-password-submit-btn');
      const cancelBtn = document.getElementById('admin-password-cancel-btn');
      const passwordInput = document.getElementById('admin-password-input');
      const confirmInput = document.getElementById('admin-password-confirm-input');
      if (submitBtn) {
        submitBtn.disabled = value;
        submitBtn.textContent = value ? 'Saving...' : 'Set password';
      }
      if (cancelBtn) cancelBtn.disabled = value;
      if (passwordInput) passwordInput.disabled = value;
      if (confirmInput) confirmInput.disabled = value;
    },

    showError(msg) {
      const el = document.getElementById('admin-error');
      if (!el) return;
      el.textContent = msg;
      el.classList.toggle('hidden', !msg);
    },

    setSaving(value) {
      this.savingSettings = value;
      const btn = document.getElementById('admin-save-btn');
      if (!btn) return;
      btn.disabled = value;
      btn.textContent = value ? 'Saving...' : 'Save settings';
    },

    async updateUserRole(user, role) {
      this.showError('');
      const previousRole = user.role;
      user.role = role;
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.showError(data.detail || 'Unable to update user role');
        user.role = previousRole;
        this.renderUsers();
        return;
      }
      const updated = await res.json();
      user.role = updated.role;
      user.is_active = updated.is_active;
      user.password_reset_requested = !!updated.password_reset_requested;
      this.renderUsers();
    },

    async updateUserStatus(user, isActive) {
      this.showError('');
      const previousValue = user.is_active;
      user.is_active = isActive;
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({is_active: isActive}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.showError(data.detail || 'Unable to update user status');
        user.is_active = previousValue;
        this.renderUsers();
        return;
      }
      const updated = await res.json();
      user.role = updated.role;
      user.is_active = updated.is_active;
      user.password_reset_requested = !!updated.password_reset_requested;
      this.renderUsers();
    },

    async updatePasswordResetRequested(user, passwordResetRequested) {
      this.showError('');
      const previousValue = user.password_reset_requested;
      user.password_reset_requested = passwordResetRequested;
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password_reset_requested: passwordResetRequested}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.showError(data.detail || 'Unable to update password recovery status');
        user.password_reset_requested = previousValue;
        this.renderUsers();
        return;
      }
      const updated = await res.json();
      user.role = updated.role;
      user.is_active = updated.is_active;
      user.password_reset_requested = !!updated.password_reset_requested;
      this.renderUsers();
    },

    async submitPasswordDialog() {
      const userId = this.passwordDialogUserId;
      const user = this.users.find(candidate => candidate.id === userId);
      if (!user) {
        this.closePasswordDialog();
        return;
      }
      const password = document.getElementById('admin-password-input')?.value || '';
      const confirmPassword = document.getElementById('admin-password-confirm-input')?.value || '';
      if (password.length < 8) {
        this.setPasswordFormError('Password must be at least 8 characters');
        return;
      }
      if (password !== confirmPassword) {
        this.setPasswordFormError('Passwords do not match');
        return;
      }

      this.showError('');
      this.setPasswordFormError('');
      this.setPasswordSubmitting(true);
      this.savingPasswordForUserId = user.id;
      this.renderUsers();
      const previousPasswordResetRequested = user.password_reset_requested;

      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password}),
      });

      this.savingPasswordForUserId = null;
      this.renderUsers();
      this.setPasswordSubmitting(false);

      if (!res.ok) {
        const data = await res.json();
        user.password_reset_requested = previousPasswordResetRequested;
        this.setPasswordFormError(data.detail || 'Unable to set password');
        return;
      }

      const updated = await res.json();
      user.role = updated.role;
      user.is_active = updated.is_active;
      user.password_reset_requested = !!updated.password_reset_requested;
      this.renderUsers();
      this.closePasswordDialog();
    },

    async deleteUser(user) {
      this.showError('');
      const confirmed = window.confirm(`Delete ${user.display_name || user.email}? This cannot be undone.`);
      if (!confirmed) return;

      this.deletingUserId = user.id;
      this.renderUsers();
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'DELETE',
      });
      this.deletingUserId = null;

      if (!res.ok) {
        this.renderUsers();
        const data = await res.json();
        this.showError(data.detail || 'Unable to delete user');
        return;
      }

      this.openActionsUserId = null;
      await this.reloadAdminEntities();
    },

    async deleteBoard(board) {
      this.showError('');
      const confirmed = window.confirm(`Delete board "${board.name}"? This cannot be undone.`);
      if (!confirmed) return;

      this.deletingBoardId = board.id;
      this.renderBoards();
      const res = await fetch(`/api/boards/${board.id}`, {
        method: 'DELETE',
      });
      this.deletingBoardId = null;

      if (!res.ok) {
        this.renderBoards();
        const data = await res.json();
        this.showError(data.detail || 'Unable to delete board');
        return;
      }

      await this.reloadAdminEntities();
    },

    async deleteOrphanedBoards() {
      this.showError('');
      const orphanedCount = this.boards.filter(board => board.is_orphan).length;
      if (!orphanedCount) return;
      const confirmed = window.confirm(`Delete all ${orphanedCount} orphaned hubs? This cannot be undone.`);
      if (!confirmed) return;

      this.deletingOrphanedBoards = true;
      this.renderGlobalActions();
      const res = await fetch('/api/admin/actions/delete-orphaned-boards', {
        method: 'POST',
      });
      this.deletingOrphanedBoards = false;

      if (!res.ok) {
        this.renderGlobalActions();
        const data = await res.json();
        this.showError(data.detail || 'Unable to delete orphaned hubs');
        return;
      }

      await this.reloadAdminEntities();
    },

    async saveSettings() {
      this.showError('');
      this.setSaving(true);
      const payload = this.readSettings();
      const res = await fetch('/api/admin/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      this.setSaving(false);
      if (!res.ok) {
        const data = await res.json();
        this.showError(data.detail || 'Unable to save settings');
        return;
      }
      this.settings = await res.json();
      this.populateSettings();
    },
  };
}

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('admin-root')) return;
  const instance = _createAdmin();
  instance.init();
});

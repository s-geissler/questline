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
    settings: {},
    savingSettings: false,
    _selectedBoardColor: '#3b82f6',
    _selectedThemeColor: '#1d4ed8',

    async init() {
      const root = document.getElementById('admin-root');
      this.currentUserId = parseInt(root?.dataset.currentUserId || '0', 10);

      const [usersRes, settingsRes] = await Promise.all([
        fetch('/api/admin/users'),
        fetch('/api/admin/settings'),
      ]);
      if (!usersRes.ok || !settingsRes.ok) {
        this.showError('Unable to load admin data');
        return;
      }
      this.users = await usersRes.json();
      this.settings = await settingsRes.json();
      this.populateSettings();
      this.renderUsers();
      this.bindEvents();
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
        const action = event.target.closest('[data-action]')?.dataset.action;
        if (action === 'save-settings') { this.saveSettings(); return; }
        if (action === 'select-board-color') {
          const el = event.target.closest('[data-action]');
          this._selectedBoardColor = el.dataset.color;
          this._renderColorSwatches('settings-default-board-color-swatches', this._selectedBoardColor, 'select-board-color', PRESET_COLORS);
          return;
        }
        if (action === 'select-theme-color') {
          const el = event.target.closest('[data-action]');
          this._selectedThemeColor = el.dataset.color;
          this._renderColorSwatches('settings-instance-theme-color-swatches', this._selectedThemeColor, 'select-theme-color', PAGE_THEME_COLORS);
          return;
        }
        if (action === 'update-user-status') {
          const el = event.target.closest('[data-action]');
          const userId = parseInt(el.dataset.userId, 10);
          const user = this.users.find(u => u.id === userId);
          if (user) this.updateUserStatus(user, el.dataset.value === 'active');
          return;
        }
      });

      document.getElementById('admin-users-list')?.addEventListener('change', event => {
        const field = event.target.dataset.field;
        const userId = parseInt(event.target.dataset.userId, 10);
        const user = this.users.find(u => u.id === userId);
        if (!user) return;
        if (field === 'user-status') this.updateUserStatus(user, event.target.value === 'active');
        if (field === 'user-role') this.updateUserRole(user, event.target.value);
      });
    },

    renderUsers() {
      const el = document.getElementById('admin-users-list');
      if (!el) return;
      if (!this.users.length) {
        el.innerHTML = '<div class="px-5 py-4 text-sm text-gray-500">No users found.</div>';
        return;
      }
      el.innerHTML = this.users.map(user => {
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
        return `
          <div class="grid grid-cols-[1.4fr_1.4fr_0.8fr_0.8fr_0.8fr] gap-4 px-5 py-3 border-b items-center">
            <div class="min-w-0">
              <div class="text-sm font-medium text-gray-800">${_escapeAdminHtml(user.display_name)}</div>
              ${youBadge}
            </div>
            <div class="text-sm text-gray-600 truncate">${_escapeAdminHtml(user.email)}</div>
            <div class="text-sm text-gray-500">${_escapeAdminHtml(user.board_count)}</div>
            <div>${statusSelect}</div>
            <div>${roleSelect}</div>
          </div>
        `;
      }).join('');
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
      this.renderUsers();
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

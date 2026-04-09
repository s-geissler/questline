function adminPage(currentUserId) {
  return {
    currentUserId,
    users: [],
    settings: {
      registration_enabled: true,
      default_board_color: '#2563eb',
      new_accounts_active_by_default: true,
      instance_theme_color: '#1d4ed8',
      recurrence_worker_interval_seconds: 60,
    },
    error: '',
    savingSettings: false,

    async init() {
      const [usersRes, settingsRes] = await Promise.all([
        fetch('/api/admin/users'),
        fetch('/api/admin/settings'),
      ]);
      if (!usersRes.ok || !settingsRes.ok) {
        this.error = 'Unable to load admin data';
        return;
      }
      this.users = await usersRes.json();
      this.settings = await settingsRes.json();
    },

    async updateUserRole(user, role) {
      this.error = '';
      const previousRole = user.role;
      user.role = role;
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.error = data.detail || 'Unable to update user role';
        user.role = previousRole;
        return;
      }
      const updated = await res.json();
      user.role = updated.role;
      user.is_active = updated.is_active;
    },

    async updateUserStatus(user, isActive) {
      this.error = '';
      const previousValue = user.is_active;
      user.is_active = isActive;
      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({is_active: isActive}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.error = data.detail || 'Unable to update user status';
        user.is_active = previousValue;
        return;
      }
      const updated = await res.json();
      user.role = updated.role;
      user.is_active = updated.is_active;
    },

    async saveSettings() {
      this.error = '';
      this.savingSettings = true;
      const res = await fetch('/api/admin/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(this.settings),
      });
      this.savingSettings = false;
      if (!res.ok) {
        const data = await res.json();
        this.error = data.detail || 'Unable to save settings';
        return;
      }
      this.settings = await res.json();
    },
  };
}

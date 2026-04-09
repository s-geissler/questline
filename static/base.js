function getCookie(name) {
  const prefix = `${name}=`;
  return document.cookie
    .split(';')
    .map(part => part.trim())
    .find(part => part.startsWith(prefix))
    ?.slice(prefix.length) || '';
}

function sanitizeMarkdownHtml(html) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html || '', 'text/html');
  const allowedTags = new Set(['A', 'P', 'BR', 'STRONG', 'EM', 'UL', 'OL', 'LI', 'CODE', 'PRE', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'HR']);
  const allowedProtocols = ['http:', 'https:', 'mailto:', 'tel:'];

  function isSafeHref(value) {
    if (!value) return false;
    if (value.startsWith('/') || value.startsWith('#')) return true;
    try {
      const url = new URL(value, window.location.origin);
      return allowedProtocols.includes(url.protocol);
    } catch {
      return false;
    }
  }

  function visit(node) {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        if (!allowedTags.has(child.tagName)) {
          child.replaceWith(document.createTextNode(child.textContent || ''));
          continue;
        }
        for (const attr of [...child.attributes]) {
          const attrName = attr.name.toLowerCase();
          if (child.tagName === 'A' && attrName === 'href') {
            if (!isSafeHref(attr.value)) {
              child.removeAttribute(attr.name);
            }
            continue;
          }
          if (child.tagName === 'A' && attrName === 'title') {
            continue;
          }
          child.removeAttribute(attr.name);
        }
        if (child.tagName === 'A') {
          child.setAttribute('rel', 'nofollow noopener noreferrer');
        }
        visit(child);
        continue;
      }
      if (child.nodeType !== Node.TEXT_NODE) {
        child.remove();
      }
    }
  }

  visit(doc.body);
  return doc.body.innerHTML;
}

function renderMarkdown(value) {
  return sanitizeMarkdownHtml(marked.parse(value || ''));
}

const nativeFetch = window.fetch.bind(window);
window.fetch = function(input, init = {}) {
  const request = input instanceof Request ? input : new Request(input, init);
  const url = new URL(request.url, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) {
    return nativeFetch(input, init);
  }

  const method = (request.method || 'GET').toUpperCase();
  if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    return nativeFetch(input, init);
  }

  const headers = new Headers(request.headers);
  headers.set('X-Requested-With', 'XMLHttpRequest');

  if (!['/api/auth/login', '/api/auth/register'].includes(url.pathname)) {
    const csrfToken = getCookie('questline_csrf');
    if (csrfToken) {
      headers.set('X-CSRF-Token', csrfToken);
    }
  }

  if (input instanceof Request) {
    return nativeFetch(new Request(input, {headers}));
  }
  return nativeFetch(input, {...init, headers});
};

const PRESET_COLORS = [
  '#ef4444','#f97316','#f59e0b','#eab308',
  '#22c55e','#14b8a6','#06b6d4','#3b82f6',
  '#6366f1','#a855f7','#ec4899','#64748b',
  '#374151','#78716c',
];

function _darkenHex(hex, amount) {
  const n = parseInt((hex || '#1d4ed8').replace('#', ''), 16);
  const r = Math.max(0, ((n >> 16) & 255) * (1 - amount) | 0);
  const g = Math.max(0, ((n >> 8) & 255) * (1 - amount) | 0);
  const b = Math.max(0, (n & 255) * (1 - amount) | 0);
  return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
}

function applyBoardColor(color) {
  const bg = color || '#1d4ed8';
  document.body.style.backgroundColor = bg;
  const nav = document.getElementById('main-nav');
  if (nav) nav.style.backgroundColor = _darkenHex(bg, 0.25);
}

function getInitialTheme() {
  const saved = localStorage.getItem('questline-theme');
  if (saved === 'dark' || saved === 'light') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  localStorage.setItem('questline-theme', theme);
}

function userMenu(currentUser) {
  return {
    menuOpen: false,
    notificationsOpen: false,
    notifications: [],
    unreadCount: 0,
    profileOpen: false,
    savingProfile: false,
    profileError: '',
    profile: {
      display_name: currentUser?.display_name || '',
      password: '',
    },

    async init() {
      if (currentUser) {
        await this.fetchNotifications();
      }
    },

    async fetchNotifications() {
      const res = await fetch('/api/notifications');
      if (!res.ok) return;
      const data = await res.json();
      this.notifications = data.items || [];
      this.unreadCount = data.unread_count || 0;
    },

    async toggleNotifications() {
      this.notificationsOpen = !this.notificationsOpen;
      if (this.notificationsOpen) {
        await this.fetchNotifications();
      }
    },

    async openNotification(notification) {
      if (!notification.read_at) {
        await fetch(`/api/notifications/${notification.id}/read`, {method: 'POST'});
        notification.read_at = new Date().toISOString();
        this.unreadCount = Math.max(0, this.unreadCount - 1);
      }
      this.notificationsOpen = false;
      if (notification.link_url) {
        window.location.href = notification.link_url;
      }
    },

    async markAllNotificationsRead() {
      const res = await fetch('/api/notifications/read-all', {method: 'POST'});
      if (!res.ok) return;
      this.notifications = this.notifications.map(notification => ({
        ...notification,
        read_at: notification.read_at || new Date().toISOString(),
      }));
      this.unreadCount = 0;
    },

    formatNotificationTime(value) {
      if (!value) return '';
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return '';
      return dt.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
    },

    openProfile() {
      this.profile.display_name = currentUser?.display_name || this.profile.display_name;
      this.profile.password = '';
      this.profileError = '';
      this.profileOpen = true;
    },

    closeProfile() {
      this.profileOpen = false;
      this.profile.password = '';
      this.profileError = '';
    },

    async saveProfile() {
      this.profileError = '';
      this.savingProfile = true;
      const res = await fetch('/api/auth/profile', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(this.profile),
      });
      this.savingProfile = false;
      if (!res.ok) {
        const data = await res.json();
        this.profileError = data.detail || 'Unable to save profile';
        return;
      }
      const updated = await res.json();
      currentUser.display_name = updated.display_name;
      this.profile.display_name = updated.display_name;
      this.profile.password = '';
      this.profileOpen = false;
    },

    async logout() {
      await fetch('/api/auth/logout', {method: 'POST'});
      window.location.href = '/login';
    },
  };
}

applyTheme(getInitialTheme());

document.addEventListener('DOMContentLoaded', () => {
  const color = document.body.dataset.pageThemeColor || '';
  applyBoardColor(color || null);
});

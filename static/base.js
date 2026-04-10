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

const PAGE_THEME_COLORS = ['#1d4ed8', ...PRESET_COLORS];

function _colorToken(hex, fallback = '1d4ed8') {
  return String(hex || '').replace('#', '').toLowerCase() || fallback;
}

function applyBoardColor(color) {
  const token = _colorToken(color, '1d4ed8');
  const nav = document.getElementById('main-nav');
  document.body.classList.remove(...PAGE_THEME_COLORS.map(value => `theme-bg-${_colorToken(value)}`));
  document.body.classList.add(`theme-bg-${token}`);
  if (nav) {
    nav.classList.remove(...PAGE_THEME_COLORS.map(value => `theme-nav-${_colorToken(value)}`));
    nav.classList.add(`theme-nav-${token}`);
  }
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

function userMenu() {
  return {
    currentUser: null,
    menuOpen: false,
    notificationsOpen: false,
    notifications: [],
    unreadCount: 0,
    profileOpen: false,
    savingProfile: false,
    profileError: '',
    profile: {
      display_name: '',
      password: '',
    },

    get hasUnreadNotifications() {
      return this.unreadCount > 0;
    },

    get unreadBadgeText() {
      return this.unreadCount > 9 ? '9+' : String(this.unreadCount || '');
    },

    get showEmptyNotifications() {
      return this.notifications.length === 0;
    },

    get saveProfileLabel() {
      return this.savingProfile ? 'Saving...' : 'Save';
    },

    async init() {
      this.currentUser = JSON.parse(this.$el.dataset.currentUser || 'null');
      this.profile.display_name = this.currentUser?.display_name || '';
      if (this.currentUser) {
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

    closeNotifications() {
      this.notificationsOpen = false;
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
      this.profile.display_name = this.currentUser?.display_name || this.profile.display_name;
      this.profile.password = '';
      this.profileError = '';
      this.profileOpen = true;
    },

    openProfileFromMenu() {
      this.menuOpen = false;
      this.openProfile();
    },

    closeProfile() {
      this.profileOpen = false;
      this.profile.password = '';
      this.profileError = '';
    },

    toggleMenu() {
      this.menuOpen = !this.menuOpen;
    },

    closeMenu() {
      this.menuOpen = false;
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
      this.currentUser.display_name = updated.display_name;
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

function dropdownMenu() {
  return {
    open: false,

    toggle() {
      this.open = !this.open;
    },

    close() {
      this.open = false;
    },
  };
}

function themeToggle() {
  return {
    dark: false,

    init() {
      this.dark = document.documentElement.classList.contains('dark');
    },

    toggle() {
      this.dark = !this.dark;
      applyTheme(this.dark ? 'dark' : 'light');
    },

    get ariaLabel() {
      return this.dark ? 'Switch to light mode' : 'Switch to dark mode';
    },

    get showLightIcon() {
      return !this.dark;
    },

    get showDarkIcon() {
      return this.dark;
    },
  };
}

applyTheme(getInitialTheme());

document.addEventListener('DOMContentLoaded', () => {
  const color = document.body.dataset.pageThemeColor || '';
  applyBoardColor(color || null);
});

document.addEventListener('alpine:init', () => {
  Alpine.directive('markdown', (el, {expression}, {evaluateLater, effect}) => {
    const evaluate = evaluateLater(expression);
    effect(() => {
      evaluate(value => {
        el.innerHTML = renderMarkdown(value || '');
      });
    });
  });
  Alpine.data('dropdownMenu', dropdownMenu);
  Alpine.data('userMenu', userMenu);
  Alpine.data('themeToggle', themeToggle);
});

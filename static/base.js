function _escapeNavHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

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
  '#ef4444', '#f97316', '#f59e0b', '#eab308',
  '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  '#6366f1', '#a855f7', '#ec4899', '#64748b',
  '#374151', '#78716c',
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

function _setHidden(el, hidden, displayClass = null) {
  if (!el) return;
  el.classList.toggle('hidden', hidden);
  if (displayClass) {
    el.classList.toggle(displayClass, !hidden);
  }
}

function _setText(el, value) {
  if (el) el.textContent = value;
}

function _setError(el, value) {
  if (!el) return;
  _setText(el, value || '');
  el.classList.toggle('hidden', !value);
}

function initBoardSwitcher() {
  const root = document.getElementById('board-switcher');
  const toggle = document.getElementById('board-switcher-toggle');
  const menu = document.getElementById('board-switcher-menu');
  if (!root || !toggle || !menu) return;

  let open = false;
  const render = () => _setHidden(menu, !open);

  toggle.addEventListener('click', event => {
    event.stopPropagation();
    open = !open;
    render();
  });

  menu.addEventListener('click', () => {
    open = false;
    render();
  });

  document.addEventListener('click', event => {
    if (!root.contains(event.target)) {
      open = false;
      render();
    }
  });
}

function initThemeToggle() {
  const button = document.getElementById('theme-toggle');
  const lightIcon = document.getElementById('theme-toggle-light');
  const darkIcon = document.getElementById('theme-toggle-dark');
  if (!button || !lightIcon || !darkIcon) return;

  let dark = document.documentElement.classList.contains('dark');

  function render() {
    button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
    _setHidden(lightIcon, dark);
    _setHidden(darkIcon, !dark);
  }

  button.addEventListener('click', () => {
    dark = !dark;
    applyTheme(dark ? 'dark' : 'light');
    render();
  });

  render();
}

function initUserShell() {
  const root = document.getElementById('nav-user-root');
  if (!root) return;

  const currentUser = JSON.parse(root.dataset.currentUser || 'null');
  const notificationsRoot = document.getElementById('nav-notifications');
  const notificationsToggle = document.getElementById('nav-notifications-toggle');
  const notificationsPanel = document.getElementById('nav-notifications-panel');
  const notificationsList = document.getElementById('nav-notifications-list');
  const notificationsBadge = document.getElementById('nav-notifications-badge');
  const markAllReadButton = document.getElementById('nav-mark-all-read');
  const menuRoot = document.getElementById('nav-user-menu-root');
  const menuToggle = document.getElementById('nav-user-menu-toggle');
  const menuPanel = document.getElementById('nav-user-menu-panel');
  const currentUserName = document.getElementById('nav-current-user-name');
  const openProfileButton = document.getElementById('nav-open-profile');
  const logoutButton = document.getElementById('nav-logout');
  const profileModal = document.getElementById('profile-modal');
  const profileBackdrop = document.getElementById('profile-modal-backdrop');
  const profileCloseTop = document.getElementById('profile-close-top');
  const profileCancel = document.getElementById('profile-cancel');
  const profileSave = document.getElementById('profile-save');
  const profileSaveLabel = document.getElementById('profile-save-label');
  const profileDisplayNameInput = document.getElementById('profile-display-name-input');
  const profilePasswordInput = document.getElementById('profile-password-input');
  const profileError = document.getElementById('profile-error');

  const openTokensButton = document.getElementById('nav-open-tokens');
  const tokensModal = document.getElementById('tokens-modal');
  const tokensModalBackdrop = document.getElementById('tokens-modal-backdrop');
  const tokensModalCloseTop = document.getElementById('tokens-modal-close-top');
  const tokensListSection = document.getElementById('tokens-list-section');
  const tokensList = document.getElementById('tokens-list');
  const tokensListEmpty = document.getElementById('tokens-list-empty');
  const tokensError = document.getElementById('tokens-error');
  const tokensCreateToggle = document.getElementById('tokens-create-toggle');
  const tokensCreateForm = document.getElementById('tokens-create-form');
  const tokensCreateName = document.getElementById('tokens-create-name');
  const tokensCreateError = document.getElementById('tokens-create-error');
  const tokensCreateSubmit = document.getElementById('tokens-create-submit');
  const tokensCreateSubmitLabel = document.getElementById('tokens-create-submit-label');
  const tokensCreateCancel = document.getElementById('tokens-create-cancel');
  const tokensJustCreatedPanel = document.getElementById('tokens-just-created-panel');
  const tokensRawValue = document.getElementById('tokens-raw-value');
  const tokensJustCreatedName = document.getElementById('tokens-just-created-name');
  const tokensCopyRaw = document.getElementById('tokens-copy-raw');
  const tokensCopyFeedback = document.getElementById('tokens-copy-feedback');
  const tokensJustCreatedClose = document.getElementById('tokens-just-created-close');
  const tokensConfirmRevoke = document.getElementById('tokens-confirm-revoke');
  const tokensRevokeTargetName = document.getElementById('tokens-revoke-target-name');
  const tokensRevokeTargetSuffix = document.getElementById('tokens-revoke-target-suffix');
  const tokensRevokeCancel = document.getElementById('tokens-revoke-cancel');
  const tokensRevokeConfirm = document.getElementById('tokens-revoke-confirm');
  const tokensRevokeConfirmLabel = document.getElementById('tokens-revoke-confirm-label');

  if (!currentUser) return;

  const state = {
    currentUser,
    notifications: [],
    unreadCount: 0,
    notificationsOpen: false,
    menuOpen: false,
    profileOpen: false,
    savingProfile: false,
    tokensOpen: false,
    tokens: [],
    tokensLoading: false,
    tokensError: '',
    tokensCreateFormOpen: false,
    creatingToken: false,
    tokensCreateError: '',
    newlyCreatedToken: null,
    tokensCopyFeedback: false,
    revokeTarget: null,
    revokingTokenId: null,
  };

  function renderNotifications() {
    if (!notificationsList) return;
    if (!state.notifications.length) {
      notificationsList.innerHTML = '<div class="px-3 py-4 text-sm text-gray-500">No notifications</div>';
      return;
    }
    notificationsList.innerHTML = state.notifications.map((notification, idx) => {
      const dotClass = notification.read_at ? 'bg-gray-200' : 'bg-blue-500';
      const bodyHtml = notification.body
        ? `<div class="text-xs text-gray-500 mt-0.5">${_escapeNavHtml(notification.body)}</div>`
        : '';
      const timeHtml = `<div class="text-[11px] text-gray-400 mt-1">${_escapeNavHtml(formatNotificationTime(notification.created_at))}</div>`;
      return `
        <button
          type="button"
          data-action="open-notification"
          data-notification-index="${idx}"
          class="w-full text-left px-3 py-2 hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-b-0"
        >
          <div class="flex items-start gap-2">
            <span class="mt-1 w-2 h-2 rounded-full flex-shrink-0 ${dotClass}"></span>
            <div class="min-w-0 flex-1">
              <div class="text-sm font-medium text-gray-800">${_escapeNavHtml(notification.title || '')}</div>
              ${bodyHtml}
              ${timeHtml}
            </div>
          </div>
        </button>
      `;
    }).join('');
  }

  function renderState() {
    _setText(currentUserName, state.currentUser.display_name || '');

    if (notificationsBadge) {
      _setText(notificationsBadge, state.unreadCount > 9 ? '9+' : String(state.unreadCount || ''));
      _setHidden(notificationsBadge, state.unreadCount === 0, 'flex');
    }

    _setHidden(markAllReadButton, state.unreadCount === 0);
    _setHidden(notificationsPanel, !state.notificationsOpen);
    _setHidden(menuPanel, !state.menuOpen);
    _setHidden(profileModal, !state.profileOpen, 'flex');
    renderTokensModal();

    if (profileSave) {
      profileSave.disabled = state.savingProfile;
    }
    _setText(profileSaveLabel, state.savingProfile ? 'Saving...' : 'Save');
  }

  function closeNotifications() {
    state.notificationsOpen = false;
    renderState();
  }

  function closeMenu() {
    state.menuOpen = false;
    renderState();
  }

  function closeProfile() {
    state.profileOpen = false;
    _setError(profileError, '');
    if (profilePasswordInput) {
      profilePasswordInput.value = '';
    }
    renderState();
  }

  function openProfile() {
    state.profileOpen = true;
    _setError(profileError, '');
    if (profileDisplayNameInput) {
      profileDisplayNameInput.value = state.currentUser.display_name || '';
      profileDisplayNameInput.focus();
    }
    if (profilePasswordInput) {
      profilePasswordInput.value = '';
    }
    renderState();
  }

  async function fetchNotifications() {
    const res = await fetch('/api/notifications');
    if (!res.ok) return;
    const data = await res.json();
    state.notifications = data.items || [];
    state.unreadCount = data.unread_count || 0;
    renderNotifications();
    renderState();
  }

  async function openNotification(notification) {
    if (!notification.read_at) {
      await fetch(`/api/notifications/${notification.id}/read`, {method: 'POST'});
      notification.read_at = new Date().toISOString();
      state.unreadCount = Math.max(0, state.unreadCount - 1);
    }
    closeNotifications();
    renderNotifications();
    if (notification.link_url) {
      window.location.href = notification.link_url;
    }
  }

  async function markAllNotificationsRead() {
    const res = await fetch('/api/notifications/read-all', {method: 'POST'});
    if (!res.ok) return;
    state.notifications = state.notifications.map(notification => ({
      ...notification,
      read_at: notification.read_at || new Date().toISOString(),
    }));
    state.unreadCount = 0;
    renderNotifications();
    renderState();
  }

  async function saveProfile() {
    _setError(profileError, '');
    state.savingProfile = true;
    renderState();

    const displayName = profileDisplayNameInput?.value || '';
    const password = profilePasswordInput?.value || '';
    const res = await fetch('/api/auth/profile', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        display_name: displayName,
        password,
      }),
    });

    state.savingProfile = false;
    renderState();

    if (!res.ok) {
      const data = await res.json();
      _setError(profileError, data.detail || 'Unable to save profile');
      return;
    }

    const updated = await res.json();
    state.currentUser.display_name = updated.display_name;
    closeProfile();
    renderState();
  }

  async function logout() {
    await fetch('/api/auth/logout', {method: 'POST'});
    window.location.href = '/login';
  }

  function formatNotificationTime(value) {
    if (!value) return '';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return '';
    return dt.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
  }

  notificationsToggle?.addEventListener('click', async event => {
    event.stopPropagation();
    state.notificationsOpen = !state.notificationsOpen;
    if (state.notificationsOpen) {
      state.menuOpen = false;
      renderState();
      await fetchNotifications();
      return;
    }
    renderState();
  });

  markAllReadButton?.addEventListener('click', async event => {
    event.stopPropagation();
    await markAllNotificationsRead();
  });

  notificationsList?.addEventListener('click', event => {
    const button = event.target.closest('[data-action="open-notification"]');
    if (!button) return;
    const idx = parseInt(button.dataset.notificationIndex || '-1', 10);
    const notification = state.notifications[idx];
    if (notification) {
      openNotification(notification);
    }
  });

  menuToggle?.addEventListener('click', event => {
    event.stopPropagation();
    state.menuOpen = !state.menuOpen;
    if (state.menuOpen) {
      state.notificationsOpen = false;
    }
    renderState();
  });

  openProfileButton?.addEventListener('click', () => {
    closeMenu();
    openProfile();
  });

  logoutButton?.addEventListener('click', () => {
    logout();
  });

  profileBackdrop?.addEventListener('click', closeProfile);
  profileCloseTop?.addEventListener('click', closeProfile);
  profileCancel?.addEventListener('click', closeProfile);
  profileSave?.addEventListener('click', () => {
    saveProfile();
  });

  profilePasswordInput?.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      saveProfile();
    }
  });

  document.addEventListener('click', event => {
    if (notificationsRoot && !notificationsRoot.contains(event.target)) {
      closeNotifications();
    }
    if (menuRoot && !menuRoot.contains(event.target)) {
      closeMenu();
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    closeNotifications();
    closeMenu();
    if (state.profileOpen) {
      closeProfile();
    }
    if (state.tokensOpen) {
      closeTokensModal();
    }
  });

  // -------------------------------------------------------------------------
  // API tokens
  // -------------------------------------------------------------------------

  function _formatRelativeTime(value) {
    if (!value) return '';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return '';
    const now = Date.now();
    const diffSec = Math.floor((now - dt.getTime()) / 1000);
    if (diffSec < 5) return 'just now';
    if (diffSec < 60) return `${diffSec} seconds ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`;
    const diffHour = Math.floor(diffMin / 60);
    if (diffHour < 24) return `${diffHour} hour${diffHour === 1 ? '' : 's'} ago`;
    const diffDay = Math.floor(diffHour / 24);
    if (diffDay < 7) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
    return dt.toLocaleDateString(undefined, {year: 'numeric', month: 'short', day: 'numeric'});
  }

  async function _copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (e) {
        // fall through
      }
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.width = '1px';
    textarea.style.height = '1px';
    textarea.style.padding = '0';
    textarea.style.border = 'none';
    textarea.style.outline = 'none';
    textarea.style.boxShadow = 'none';
    textarea.style.background = 'transparent';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(textarea);
    return ok;
  }

  function renderTokenList() {
    if (!tokensList || !tokensListEmpty) return;
    if (state.tokensLoading) {
      tokensList.innerHTML = '<div class="text-sm text-gray-500 py-3 text-center">Loading…</div>';
      _setHidden(tokensListEmpty, true);
      return;
    }
    if (!state.tokens.length) {
      tokensList.innerHTML = '';
      _setHidden(tokensListEmpty, false);
      return;
    }
    _setHidden(tokensListEmpty, true);
    tokensList.innerHTML = state.tokens.map(token => {
      const lastUsed = token.last_used_at
        ? ` · Last used ${_escapeNavHtml(_formatRelativeTime(token.last_used_at))}`
        : ' · Never used';
      return `
        <div class="flex items-start justify-between gap-3 p-3 border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-gray-800 truncate">${_escapeNavHtml(token.name)}</div>
            <div class="text-xs text-gray-500 mt-0.5 font-mono">qgl_…${_escapeNavHtml(token.last_four || '')}</div>
            <div class="text-xs text-gray-500 mt-0.5">
              Created ${_escapeNavHtml(_formatRelativeTime(token.created_at))}${lastUsed}
            </div>
          </div>
          <button
            type="button"
            data-action="revoke-token"
            data-token-id="${token.id}"
            data-token-name="${_escapeNavHtml(token.name)}"
            data-token-last-four="${_escapeNavHtml(token.last_four || '')}"
            class="px-2.5 py-1.5 rounded-lg border border-red-200 text-red-700 text-xs font-medium hover:bg-red-50 flex-shrink-0"
          >Revoke</button>
        </div>
      `;
    }).join('');
  }

  function renderTokensModal() {
    if (!tokensModal) return;
    _setHidden(tokensModal, !state.tokensOpen, 'flex');
    if (tokensModalCloseTop) {
      // The close button is hidden while a token is being shown for the
      // first time — the user must explicitly acknowledge saving it.
      _setHidden(tokensModalCloseTop, !!state.newlyCreatedToken);
    }
    _setHidden(tokensJustCreatedPanel, !state.newlyCreatedToken);
    _setHidden(tokensListSection, !!state.newlyCreatedToken);
    _setHidden(tokensCreateForm, !state.tokensCreateFormOpen || !!state.newlyCreatedToken);
    _setHidden(tokensConfirmRevoke, !state.revokeTarget || !!state.newlyCreatedToken);

    renderTokenList();

    if (state.newlyCreatedToken) {
      _setText(tokensRawValue, state.newlyCreatedToken.raw_token || '');
      _setText(tokensJustCreatedName, state.newlyCreatedToken.name || '');
    }
    if (state.revokeTarget) {
      _setText(tokensRevokeTargetName, state.revokeTarget.name || '');
      _setText(tokensRevokeTargetSuffix, `qgl_…${state.revokeTarget.last_four || ''}`);
    }

    _setError(tokensError, state.tokensError);
    _setError(tokensCreateError, state.tokensCreateError);
    if (tokensCopyFeedback) {
      _setHidden(tokensCopyFeedback, !state.tokensCopyFeedback);
    }

    if (tokensCreateSubmit) {
      tokensCreateSubmit.disabled = state.creatingToken;
    }
    _setText(tokensCreateSubmitLabel, state.creatingToken ? 'Creating…' : 'Create');

    if (tokensRevokeConfirm) {
      tokensRevokeConfirm.disabled = state.revokingTokenId !== null;
    }
    _setText(tokensRevokeConfirmLabel, state.revokingTokenId !== null ? 'Revoking…' : 'Revoke');
  }

  function openTokensModal() {
    state.tokensOpen = true;
    state.newlyCreatedToken = null;
    state.revokeTarget = null;
    state.tokensError = '';
    state.tokensCreateError = '';
    state.tokensCreateFormOpen = false;
    if (tokensCreateName) tokensCreateName.value = '';
    renderTokensModal();
    fetchTokens();
  }

  function closeTokensModal() {
    if (state.newlyCreatedToken) {
      // Force the user to acknowledge the freshly-issued token before
      // dismissing the modal.
      return;
    }
    state.tokensOpen = false;
    state.newlyCreatedToken = null;
    state.revokeTarget = null;
    state.tokensCreateFormOpen = false;
    state.tokensError = '';
    state.tokensCreateError = '';
    if (tokensCreateName) tokensCreateName.value = '';
    renderTokensModal();
  }

  async function fetchTokens() {
    state.tokensLoading = true;
    renderTokensModal();
    const res = await fetch('/api/tokens');
    state.tokensLoading = false;
    if (!res.ok) {
      state.tokensError = 'Unable to load tokens';
      renderTokensModal();
      return;
    }
    state.tokens = await res.json();
    state.tokensError = '';
    renderTokensModal();
  }

  async function submitCreateToken() {
    if (!tokensCreateName) return;
    const name = tokensCreateName.value.trim();
    if (!name) {
      state.tokensCreateError = 'Name is required';
      renderTokensModal();
      return;
    }
    state.creatingToken = true;
    state.tokensCreateError = '';
    renderTokensModal();
    const res = await fetch('/api/tokens', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name}),
    });
    state.creatingToken = false;
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      state.tokensCreateError = data.detail || 'Unable to create token';
      renderTokensModal();
      return;
    }
    const token = await res.json();
    state.newlyCreatedToken = token;
    state.tokensCreateFormOpen = false;
    state.tokensCopyFeedback = false;
    if (tokensCreateName) tokensCreateName.value = '';
    await fetchTokens();
  }

  async function submitRevokeToken() {
    if (!state.revokeTarget) return;
    const id = state.revokeTarget.id;
    state.revokingTokenId = id;
    renderTokensModal();
    const res = await fetch(`/api/tokens/${id}`, {method: 'DELETE'});
    state.revokingTokenId = null;
    if (!res.ok) {
      state.tokensError = 'Unable to revoke token';
      renderTokensModal();
      return;
    }
    state.revokeTarget = null;
    state.tokensError = '';
    await fetchTokens();
  }

  openTokensButton?.addEventListener('click', () => {
    closeMenu();
    openTokensModal();
  });

  tokensModalBackdrop?.addEventListener('click', closeTokensModal);
  tokensModalCloseTop?.addEventListener('click', closeTokensModal);

  tokensCreateToggle?.addEventListener('click', () => {
    state.tokensCreateFormOpen = !state.tokensCreateFormOpen;
    state.tokensCreateError = '';
    if (state.tokensCreateFormOpen) {
      renderTokensModal();
      tokensCreateName?.focus();
    } else {
      if (tokensCreateName) tokensCreateName.value = '';
      renderTokensModal();
    }
  });

  tokensCreateCancel?.addEventListener('click', () => {
    state.tokensCreateFormOpen = false;
    state.tokensCreateError = '';
    if (tokensCreateName) tokensCreateName.value = '';
    renderTokensModal();
  });

  tokensCreateSubmit?.addEventListener('click', () => {
    submitCreateToken();
  });

  tokensCreateName?.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      submitCreateToken();
    }
  });

  tokensJustCreatedClose?.addEventListener('click', () => {
    state.newlyCreatedToken = null;
    state.tokensCopyFeedback = false;
    renderTokensModal();
  });

  tokensCopyRaw?.addEventListener('click', async () => {
    if (!state.newlyCreatedToken || !state.newlyCreatedToken.raw_token) return;
    const ok = await _copyToClipboard(state.newlyCreatedToken.raw_token);
    state.tokensCopyFeedback = ok;
    renderTokensModal();
    if (ok) {
      setTimeout(() => {
        state.tokensCopyFeedback = false;
        renderTokensModal();
      }, 2000);
    }
  });

  tokensList?.addEventListener('click', event => {
    const button = event.target.closest('[data-action="revoke-token"]');
    if (!button) return;
    state.revokeTarget = {
      id: parseInt(button.dataset.tokenId || '0', 10),
      name: button.dataset.tokenName || '',
      last_four: button.dataset.tokenLastFour || '',
    };
    renderTokensModal();
  });

  tokensRevokeCancel?.addEventListener('click', () => {
    state.revokeTarget = null;
    renderTokensModal();
  });

  tokensRevokeConfirm?.addEventListener('click', () => {
    submitRevokeToken();
  });

  renderNotifications();
  renderState();
  fetchNotifications();
}

applyTheme(getInitialTheme());

document.addEventListener('DOMContentLoaded', () => {
  const color = document.body.dataset.pageThemeColor || '';
  applyBoardColor(color || null);
  initBoardSwitcher();
  initThemeToggle();
  initUserShell();
});

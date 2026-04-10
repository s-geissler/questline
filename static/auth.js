function _setAuthMessage(el, message) {
  if (!el) return;
  el.textContent = message || '';
  el.classList.toggle('hidden', !message);
}

function initLoginPage() {
  const root = document.getElementById('login-root');
  if (!root) return;

  const emailInput = document.getElementById('login-email-input');
  const passwordInput = document.getElementById('login-password-input');
  const errorEl = document.getElementById('login-error');
  const successEl = document.getElementById('login-success');
  const submitButton = document.getElementById('login-submit');
  const recoveryButton = document.getElementById('login-request-recovery');

  async function login() {
    _setAuthMessage(errorEl, '');
    _setAuthMessage(successEl, '');
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        email: emailInput?.value || '',
        password: passwordInput?.value || '',
      }),
    });
    if (!res.ok) {
      const data = await res.json();
      _setAuthMessage(errorEl, data.detail || 'Login failed');
      return;
    }
    window.location.href = '/';
  }

  async function requestRecovery() {
    const email = emailInput?.value || '';
    _setAuthMessage(errorEl, '');
    _setAuthMessage(successEl, '');
    if (!email.trim()) {
      _setAuthMessage(errorEl, 'Enter your email to request password help.');
      return;
    }
    const res = await fetch('/api/auth/password-recovery-request', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email}),
    });
    if (!res.ok) {
      _setAuthMessage(errorEl, 'Unable to submit password help request.');
      return;
    }
    _setAuthMessage(successEl, 'If an account exists for that email, Questline admins have been notified.');
  }

  submitButton?.addEventListener('click', login);
  recoveryButton?.addEventListener('click', requestRecovery);
  emailInput?.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      login();
    }
  });
  passwordInput?.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      login();
    }
  });
}

function initRegisterPage() {
  const root = document.getElementById('register-root');
  if (!root) return;

  const displayNameInput = document.getElementById('register-display-name-input');
  const emailInput = document.getElementById('register-email-input');
  const passwordInput = document.getElementById('register-password-input');
  const errorEl = document.getElementById('register-error');
  const successEl = document.getElementById('register-success');
  const submitButton = document.getElementById('register-submit');

  async function register() {
    _setAuthMessage(errorEl, '');
    _setAuthMessage(successEl, '');

    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        display_name: displayNameInput?.value || '',
        email: emailInput?.value || '',
        password: passwordInput?.value || '',
      }),
    });

    if (!res.ok) {
      const data = await res.json();
      _setAuthMessage(errorEl, data.detail || 'Registration failed');
      return;
    }

    const data = await res.json();
    if (data.is_active === false) {
      _setAuthMessage(successEl, 'Account created. An admin needs to activate it before you can log in.');
      if (passwordInput) passwordInput.value = '';
      return;
    }

    window.location.href = '/';
  }

  submitButton?.addEventListener('click', register);
  [displayNameInput, emailInput, passwordInput].forEach(input => {
    input?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        register();
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initLoginPage();
  initRegisterPage();
});

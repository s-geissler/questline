function loginPage() {
  return {
    error: '',

    async login() {
      this.error = '';
      const email = this.$refs.emailInput?.value || '';
      const password = this.$refs.passwordInput?.value || '';
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password}),
      });
      if (!res.ok) {
        const data = await res.json();
        this.error = data.detail || 'Login failed';
        return;
      }
      window.location.href = '/';
    },
  };
}

function registerPage() {
  return {
    error: '',
    success: '',

    async register() {
      this.error = '';
      this.success = '';
      const displayName = this.$refs.displayNameInput?.value || '';
      const email = this.$refs.emailInput?.value || '';
      const password = this.$refs.passwordInput?.value || '';
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          display_name: displayName,
          email,
          password,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        this.error = data.detail || 'Registration failed';
        return;
      }
      const data = await res.json();
      if (data.is_active === false) {
        this.success = 'Account created. An admin needs to activate it before you can log in.';
        if (this.$refs.passwordInput) this.$refs.passwordInput.value = '';
        return;
      }
      window.location.href = '/';
    },
  };
}

document.addEventListener('alpine:init', () => {
  Alpine.data('loginPage', loginPage);
  Alpine.data('registerPage', registerPage);
});

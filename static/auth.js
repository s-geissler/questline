function loginPage() {
  return {
    email: '',
    password: '',
    error: '',

    async login() {
      this.error = '';
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: this.email, password: this.password}),
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
    displayName: '',
    email: '',
    password: '',
    error: '',
    success: '',

    async register() {
      this.error = '';
      this.success = '';
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          display_name: this.displayName,
          email: this.email,
          password: this.password,
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
        this.password = '';
        return;
      }
      window.location.href = '/';
    },
  };
}

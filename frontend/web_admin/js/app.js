/**
 * App: auth flow (login = username + password + TOTP always),
 * profile panel with change-credentials.
 */

// ─── Show screens ─────────────────────────────────────────────────────────────

function showLogin() {
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function showApp(user) {
  api.saveUser(user);
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  document.getElementById('username-display').textContent = user.username;

  const labels = { creator: 'Creator', head_admin: 'Гл. Админ', admin: 'Админ' };
  const roleEl = document.getElementById('role-badge');
  if (roleEl) roleEl.textContent = labels[user.role] || user.role;

  // Users tab: visible only to creator / head_admin
  const usersTabBtn = document.getElementById('tab-btn-users');
  if (usersTabBtn) {
    const canSee = user.role === 'creator' || user.role === 'head_admin';
    usersTabBtn.classList.toggle('hidden', !canSee);
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────

async function initApp() {
  const token = api.getToken();
  if (token) {
    const res = await api.me();
    if (res.ok) {
      showApp(res.data);
      showTab('servers');
      startPolling();
      return;
    }
    api.clearToken();
  }
  showLogin();
}

// ─── Login form ───────────────────────────────────────────────────────────────

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const username  = document.getElementById('login-username').value.trim();
  const password  = document.getElementById('login-password').value;
  const totpCode  = document.getElementById('login-totp').value.trim();
  const errorEl   = document.getElementById('login-error');
  const errorText = document.getElementById('login-error-text');
  const btn       = document.getElementById('login-btn');

  errorEl.classList.add('hidden');
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
  btn.disabled = true;

  const res = await api.login(username, password, totpCode);

  btn.innerHTML = '<i class="fas fa-right-to-bracket"></i> Войти';
  btn.disabled = false;

  if (res.ok && res.data.phase === 'ok') {
    api.setToken(res.data.access_token);
    const me = await api.me();
    if (me.ok) {
      showApp(me.data);
      showTab('servers');
      startPolling();
    }
  } else {
    errorText.textContent = res.error || 'Неверный логин, пароль или код';
    errorEl.classList.remove('hidden');
    document.getElementById('login-password').value = '';
    document.getElementById('login-totp').value = '';
    document.getElementById('login-totp').focus();
  }
});

// ─── Logout ───────────────────────────────────────────────────────────────────

function logout() {
  stopPolling();
  api.clearToken();
  showLogin();
}

// ─── Profile panel ────────────────────────────────────────────────────────────

function showProfilePanel() {
  const user = api.getUser();
  if (!user) return;

  const panel = document.getElementById('profile-panel');
  document.getElementById('pp-username').textContent = user.username;

  const labels = { creator: 'Creator', head_admin: 'Главный Админ', admin: 'Админ' };
  document.getElementById('pp-role').textContent = labels[user.role] || user.role;
  document.getElementById('pp-2fa-status').textContent = user.totp_enabled ? 'Включён ✓' : 'Не настроен';

  // Hide change-creds form when opening
  document.getElementById('pp-change-creds-form').classList.add('hidden');
  document.getElementById('pp-change-btn').classList.remove('hidden');

  panel.classList.toggle('hidden');
}

document.getElementById('profile-btn')?.addEventListener('click', showProfilePanel);

// Show/hide change-creds form
document.getElementById('pp-change-btn')?.addEventListener('click', () => {
  document.getElementById('pp-change-creds-form').classList.remove('hidden');
  document.getElementById('pp-change-btn').classList.add('hidden');
  document.getElementById('pp-new-username').value = api.getUser()?.username || '';
  document.getElementById('pp-new-password').value = '';
  document.getElementById('pp-confirm-password').value = '';
  document.getElementById('pp-totp-code').value = '';
  document.getElementById('pp-creds-error').classList.add('hidden');
});

document.getElementById('pp-cancel-change')?.addEventListener('click', () => {
  document.getElementById('pp-change-creds-form').classList.add('hidden');
  document.getElementById('pp-change-btn').classList.remove('hidden');
});

// Submit change-creds
document.getElementById('pp-change-creds-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const errEl = document.getElementById('pp-creds-error');
  const btn = e.target.querySelector('[type=submit]');
  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

  const newUsername = document.getElementById('pp-new-username').value.trim();
  const newPassword = document.getElementById('pp-new-password').value;
  const confirmPassword = document.getElementById('pp-confirm-password').value;
  const totpCode = document.getElementById('pp-totp-code').value.trim();

  if (newPassword !== confirmPassword) {
    errEl.textContent = 'Пароли не совпадают';
    errEl.classList.remove('hidden');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-check"></i> Сохранить';
    return;
  }

  const res = await api.changeCreds(newUsername, newPassword, confirmPassword, totpCode);

  btn.disabled = false;
  btn.innerHTML = '<i class="fas fa-check"></i> Сохранить';

  if (res.ok) {
    api.saveUser(res.data);
    document.getElementById('username-display').textContent = res.data.username;
    document.getElementById('pp-username').textContent = res.data.username;
    document.getElementById('pp-change-creds-form').classList.add('hidden');
    document.getElementById('pp-change-btn').classList.remove('hidden');
    document.getElementById('profile-panel').classList.add('hidden');
    showToast('Данные успешно изменены', 'success');
  } else {
    errEl.textContent = res.error || 'Ошибка';
    errEl.classList.remove('hidden');
  }
});

// Close profile panel on outside click
document.addEventListener('click', (e) => {
  const panel = document.getElementById('profile-panel');
  const btn = document.getElementById('profile-btn');
  if (panel && !panel.classList.contains('hidden')) {
    if (!panel.contains(e.target) && !btn.contains(e.target)) {
      panel.classList.add('hidden');
    }
  }
});

// ─── Polling ──────────────────────────────────────────────────────────────────

let pollingInterval = null;

function startPolling() {
  pollingInterval = setInterval(async () => {
    const activeTab = document.querySelector('.tab-btn.active')?.dataset?.tab;
    if (activeTab === 'servers') {
      const res = await api.getServers();
      if (res.ok && res.data) {
        res.data.forEach(server => {
          const dot = document.querySelector(`#server-card-${server.id} .status-dot`);
          if (dot) dot.className = `status-dot ${server.status}`;
        });
      }
    }
  }, 30000);
}

function stopPolling() {
  if (pollingInterval) { clearInterval(pollingInterval); pollingInterval = null; }
}

// ─── Keyboard shortcuts ───────────────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => m.classList.add('hidden'));
    document.getElementById('profile-panel')?.classList.add('hidden');
  }
  if (e.ctrlKey && e.key === '1') { e.preventDefault(); showTab('servers'); }
  if (e.ctrlKey && e.key === '2') { e.preventDefault(); showTab('connections'); }
  if (e.ctrlKey && e.key === '3') { e.preventDefault(); showTab('users'); }
});

// ─── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', initApp);

window.showLogin = showLogin;
window.showApp   = showApp;
window.logout    = logout;

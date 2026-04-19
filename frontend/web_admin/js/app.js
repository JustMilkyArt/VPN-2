/**
 * App initialization, auth flow (password → TOTP → main),
 * profile panel, change-credentials flow.
 */

// ─── State ────────────────────────────────────────────────────────────────────
let _tempToken = null;      // stored between login phases

// ─── Show/hide screens ────────────────────────────────────────────────────────
function showLogin() {
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('totp-screen').classList.add('hidden');
  document.getElementById('force-change-screen').classList.add('hidden');
  document.getElementById('app').classList.add('hidden');
  _tempToken = null;
}

function showTotpStep(tempToken) {
  _tempToken = tempToken;
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('totp-screen').classList.remove('hidden');
  document.getElementById('totp-code-input').value = '';
  document.getElementById('totp-code-input').focus();
}

function showForceChangeStep(tempToken, qrDataUri, secret) {
  _tempToken = tempToken;
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('force-change-screen').classList.remove('hidden');
  // Show QR
  if (qrDataUri) {
    document.getElementById('fc-qr-img').src = qrDataUri;
    document.getElementById('fc-secret-text').textContent = secret || '';
    document.getElementById('fc-totp-section').classList.remove('hidden');
  }
}

function showApp(user) {
  api.saveUser(user);
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('totp-screen').classList.add('hidden');
  document.getElementById('force-change-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('username-display').textContent = user.username;

  // Role badge in header
  const roleBadgeEl = document.getElementById('role-badge');
  if (roleBadgeEl) {
    const labels = { creator: 'Creator', head_admin: 'Гл. Админ', admin: 'Админ' };
    roleBadgeEl.textContent = labels[user.role] || user.role;
  }

  // Show/hide Users tab based on role
  const usersTabBtn = document.getElementById('tab-btn-users');
  if (usersTabBtn) {
    const canSeeUsers = user.role === 'creator' || user.role === 'head_admin';
    usersTabBtn.classList.toggle('hidden', !canSeeUsers);
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

// ─── Login form (step 1: password) ───────────────────────────────────────────
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('login-error');
  const errorText = document.getElementById('login-error-text');
  const btn = document.getElementById('login-btn');

  errorEl.classList.add('hidden');
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
  btn.disabled = true;

  const res = await api.login(username, password);

  btn.innerHTML = '<i class="fas fa-right-to-bracket"></i> Войти';
  btn.disabled = false;

  if (!res.ok) {
    errorText.textContent = res.error || 'Неверный логин или пароль';
    errorEl.classList.remove('hidden');
    document.getElementById('login-password').value = '';
    return;
  }

  const { phase, access_token, totp_qr, totp_secret } = res.data;

  if (phase === 'ok') {
    api.setToken(access_token);
    const me = await api.me();
    if (me.ok) { showApp(me.data); showTab('servers'); startPolling(); }
  } else if (phase === 'totp') {
    api.setToken(access_token);    // temp token stored for totp-verify
    showTotpStep(access_token);
  } else if (phase === 'force_change') {
    api.setToken(access_token);    // temp token for change-creds endpoint
    showForceChangeStep(access_token, totp_qr, totp_secret);
  }
});

// ─── TOTP step (step 2) ───────────────────────────────────────────────────────
document.getElementById('totp-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = document.getElementById('totp-code-input').value.trim();
  const errEl = document.getElementById('totp-error');
  const btn = e.target.querySelector('[type=submit]');

  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

  const res = await api.totpVerify(_tempToken, code);

  btn.disabled = false;
  btn.innerHTML = '<i class="fas fa-shield-halved"></i> Подтвердить';

  if (res.ok) {
    api.setToken(res.data.access_token);
    _tempToken = null;
    const me = await api.me();
    if (me.ok) { showApp(me.data); showTab('servers'); startPolling(); }
  } else {
    errEl.textContent = res.error || 'Неверный код';
    errEl.classList.remove('hidden');
    document.getElementById('totp-code-input').value = '';
    document.getElementById('totp-code-input').focus();
  }
});

document.getElementById('totp-back-btn')?.addEventListener('click', () => {
  api.clearToken();
  showLogin();
});

// ─── Force-change credentials (first login) ──────────────────────────────────
document.getElementById('force-change-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const errEl = document.getElementById('fc-error');
  const btn = e.target.querySelector('[type=submit]');

  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

  const res = await api.changeCreds(
    fd.get('new_username').trim(),
    fd.get('new_password'),
    fd.get('confirm_password'),
    fd.get('totp_code').trim(),
  );

  btn.disabled = false;
  btn.innerHTML = '<i class="fas fa-check"></i> Сохранить и войти';

  if (res.ok) {
    // Re-login to get a proper full token with updated username
    const loginRes = await api.login(
      fd.get('new_username').trim(),
      fd.get('new_password'),
      fd.get('totp_code').trim()
    );
    if (loginRes.ok && loginRes.data.phase === 'ok') {
      api.setToken(loginRes.data.access_token);
    }
    const me = await api.me();
    if (me.ok) { showApp(me.data); showTab('servers'); startPolling(); }
  } else {
    errEl.textContent = res.error || 'Ошибка';
    errEl.classList.remove('hidden');
  }
});

document.getElementById('fc-copy-secret')?.addEventListener('click', () => {
  const secret = document.getElementById('fc-secret-text').textContent;
  navigator.clipboard.writeText(secret).then(() => showToast('Ключ скопирован', 'success'));
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
  document.getElementById('pp-role').textContent =
    ({ creator: 'Creator', head_admin: 'Главный Админ', admin: 'Админ' })[user.role] || user.role;
  document.getElementById('pp-2fa-status').textContent = user.totp_enabled ? 'Включён ✓' : 'Не привязан';
  panel.classList.toggle('hidden');
}

document.getElementById('profile-btn')?.addEventListener('click', showProfilePanel);

// Profile: bind TOTP
document.getElementById('pp-bind-totp-btn')?.addEventListener('click', async () => {
  const res = await api.bindTotp();
  if (res.ok) {
    showTotpBindConfirmModal(res.data.totp_qr, res.data.totp_secret);
  } else {
    showToast(res.error, 'error');
  }
});

function showTotpBindConfirmModal(qr, secret) {
  document.getElementById('bind-qr-img').src = qr;
  document.getElementById('bind-secret-text').textContent = secret;
  document.getElementById('modal-bind-totp').classList.remove('hidden');
  closePanel('profile-panel');
}

document.getElementById('bind-totp-copy')?.addEventListener('click', () => {
  const s = document.getElementById('bind-secret-text').textContent;
  navigator.clipboard.writeText(s).then(() => showToast('Ключ скопирован', 'success'));
});

document.getElementById('bind-totp-confirm-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = document.getElementById('bind-confirm-code').value.trim();
  const errEl = document.getElementById('bind-totp-error');
  errEl.classList.add('hidden');
  const btn = e.target.querySelector('[type=submit]');
  btn.disabled = true;

  const res = await api.confirmTotp(code);
  btn.disabled = false;

  if (res.ok) {
    api.saveUser(res.data);
    closeModal('modal-bind-totp');
    showToast('Аутентификатор успешно привязан', 'success');
    document.getElementById('pp-2fa-status').textContent = 'Включён ✓';
  } else {
    errEl.textContent = res.error;
    errEl.classList.remove('hidden');
  }
});

function closePanel(id) {
  document.getElementById(id)?.classList.add('hidden');
}

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
    closePanel('profile-panel');
  }
  if (e.ctrlKey && e.key === '1') { e.preventDefault(); showTab('servers'); }
  if (e.ctrlKey && e.key === '2') { e.preventDefault(); showTab('connections'); }
  if (e.ctrlKey && e.key === '3') { e.preventDefault(); showTab('users'); }
});

// ─── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

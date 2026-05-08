/**
 * App: two-step auth flow
 *   Step 1: login-form  → POST /auth/login     → phase=totp, temp_token
 *   Step 2: totp modal  → POST /auth/totp-verify → access_token
 */

// ─── Show screens ─────────────────────────────────────────────────────────────

function showLogin() {
  // Stop idle timer when going back to login
  stopIdleTimer();

  // Clear all login fields on every show
  document.getElementById('login-username').value = '';
  document.getElementById('login-password').value = '';
  document.getElementById('login-error').classList.add('hidden');
  document.getElementById('totp-login-code').value = '';
  document.getElementById('totp-login-error').classList.add('hidden');
  document.getElementById('modal-totp-login').classList.add('hidden');

  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function showApp(user) {
  api.saveUser(user);
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('modal-totp-login').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  document.getElementById('username-display').textContent = user.username;

  const labels = { creator: 'Creator', head_admin: 'Гл. Админ', admin: 'Админ' };
  const roleEl = document.getElementById('role-badge');
  if (roleEl) roleEl.textContent = labels[user.role] || user.role;

  const canSeeAdminTabs = user.role === 'creator' || user.role === 'head_admin';

  const usersTabBtn = document.getElementById('tab-btn-users');
  if (usersTabBtn) usersTabBtn.classList.toggle('hidden', !canSeeAdminTabs);

  const domainsTabBtn = document.getElementById('tab-btn-domains');
  if (domainsTabBtn) domainsTabBtn.classList.toggle('hidden', !canSeeAdminTabs);

  // Start idle-timeout tracking
  startIdleTimer();
}

// ─── Init ─────────────────────────────────────────────────────────────────────

async function initApp() {
  const token = api.getToken();
  if (token) {
    const res = await api.me();
    if (res.ok) {
      showApp(res.data);   // startIdleTimer() is called inside showApp()
      showTab('servers');
      startPolling();
      return;
    }
    api.clearToken();
  }
  showLogin();
}

// ─── Step 1: Login form (username + password) ─────────────────────────────────

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errorEl  = document.getElementById('login-error');
  const errorTxt = document.getElementById('login-error-text');
  const btn      = document.getElementById('login-btn');

  errorEl.classList.add('hidden');
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
  btn.disabled = true;

  const res = await api.loginStep1(username, password);

  btn.innerHTML = '<i class="fas fa-right-to-bracket"></i> Войти';
  btn.disabled = false;

  if (res.ok && res.data.phase === 'totp') {
    // Store temp_token and show TOTP modal
    api._tempToken = res.data.temp_token;
    showTotpLoginModal();
  } else {
    errorTxt.textContent = res.error || 'Неверный логин или пароль';
    errorEl.classList.remove('hidden');
    document.getElementById('login-password').value = '';
  }
});

// ─── Step 2: TOTP modal ───────────────────────────────────────────────────────

function showTotpLoginModal() {
  document.getElementById('totp-login-code').value = '';
  document.getElementById('totp-login-error').classList.add('hidden');
  document.getElementById('modal-totp-login').classList.remove('hidden');
  setTimeout(() => document.getElementById('totp-login-code').focus(), 100);
}

function cancelTotpLogin() {
  api._tempToken = null;
  document.getElementById('modal-totp-login').classList.add('hidden');
  document.getElementById('login-password').value = '';
  document.getElementById('login-username').focus();
}

document.getElementById('totp-login-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const code    = document.getElementById('totp-login-code').value.trim();
  const errEl   = document.getElementById('totp-login-error');
  const errTxt  = document.getElementById('totp-login-error-text');
  const btn     = document.getElementById('totp-login-btn');

  errEl.classList.add('hidden');
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
  btn.disabled = true;

  const res = await api.loginStep2(api._tempToken, code);

  btn.innerHTML = '<i class="fas fa-check"></i> Подтвердить';
  btn.disabled = false;

  if (res.ok && res.data.access_token) {
    api._tempToken = null;
    api.setToken(res.data.access_token);
    const me = await api.me();
    if (me.ok) {
      showApp(me.data);
      showTab('servers');
      startPolling();
    }
  } else {
    errTxt.textContent = res.error || 'Неверный код';
    errEl.classList.remove('hidden');
    document.getElementById('totp-login-code').value = '';
    document.getElementById('totp-login-code').focus();
  }
});

// Auto-submit TOTP when 6 digits entered
document.getElementById('totp-login-code').addEventListener('input', (e) => {
  const val = e.target.value.replace(/\D/g, '');
  e.target.value = val;
  if (val.length === 6) {
    document.getElementById('totp-login-form').requestSubmit();
  }
});

// ─── Logout ───────────────────────────────────────────────────────────────────

async function logout() {
  stopPolling();
  stopIdleTimer();
  await api.logoutServer();   // invalidate server-side session (best-effort)
  api.clearToken();
  api._tempToken = null;
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

  document.getElementById('pp-change-creds-form').classList.add('hidden');
  document.getElementById('pp-change-btn').classList.remove('hidden');

  panel.classList.toggle('hidden');
}

document.getElementById('profile-btn')?.addEventListener('click', showProfilePanel);

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

document.getElementById('pp-change-creds-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const errEl = document.getElementById('pp-creds-error');
  const btn = e.target.querySelector('[type=submit]');
  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

  const newUsername     = document.getElementById('pp-new-username').value.trim();
  const newPassword     = document.getElementById('pp-new-password').value;
  const confirmPassword = document.getElementById('pp-confirm-password').value;
  const totpCode        = document.getElementById('pp-totp-code').value.trim();

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
  const btn   = document.getElementById('profile-btn');
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
    // Idle warning modal: Escape = "stay active" (same as clicking Continue)
    const idleModal = document.getElementById('modal-idle-warning');
    if (idleModal && !idleModal.classList.contains('hidden')) {
      idleStayActive();
      return;
    }
    document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => m.classList.add('hidden'));
    document.getElementById('modal-totp-login')?.classList.add('hidden');
    document.getElementById('profile-panel')?.classList.add('hidden');
  }
  if (e.ctrlKey && e.key === '1') { e.preventDefault(); showTab('servers'); }
  if (e.ctrlKey && e.key === '2') { e.preventDefault(); showTab('connections'); }
  if (e.ctrlKey && e.key === '3') { e.preventDefault(); showTab('users'); }
});

// ─── Idle Timeout ─────────────────────────────────────────────────────────────
// Logic:
//   - Total idle timeout: 10 minutes (matches server-side IDLE_TIMEOUT_SECONDS)
//   - Warning shown at 9 minutes (1 minute before forced logout)
//   - Any user activity (click, keydown, scroll, mousemove) resets the timer
//   - "Continue" button in warning modal also resets timer
//   - On timeout: server-side session invalidated, then local logout

const IDLE_TOTAL_MS   = 10 * 60 * 1000;  // 10 min — must match server
const IDLE_WARN_MS    =  9 * 60 * 1000;  // show warning at 9 min
const IDLE_EVENTS     = ['click', 'keydown', 'mousemove', 'touchstart', 'scroll'];

let _idleTimer        = null;
let _warnTimer        = null;
let _countdownInterval= null;
let _idleActive       = false;

function startIdleTimer() {
  if (_idleActive) return;
  _idleActive = true;
  _scheduleIdleTimers();

  // Register activity listeners
  IDLE_EVENTS.forEach(ev =>
    document.addEventListener(ev, _onUserActivity, { passive: true })
  );
}

function stopIdleTimer() {
  _idleActive = false;
  _clearIdleTimers();
  IDLE_EVENTS.forEach(ev =>
    document.removeEventListener(ev, _onUserActivity)
  );
  _hideIdleWarning();
}

function _scheduleIdleTimers() {
  _clearIdleTimers();
  _warnTimer  = setTimeout(_showIdleWarning,  IDLE_WARN_MS);
  _idleTimer  = setTimeout(_forceIdleLogout,  IDLE_TOTAL_MS);
}

function _clearIdleTimers() {
  if (_warnTimer)  { clearTimeout(_warnTimer);  _warnTimer  = null; }
  if (_idleTimer)  { clearTimeout(_idleTimer);  _idleTimer  = null; }
  if (_countdownInterval) { clearInterval(_countdownInterval); _countdownInterval = null; }
}

function _onUserActivity() {
  if (!_idleActive) return;
  // Reset timers; hide warning if open
  _scheduleIdleTimers();
  _hideIdleWarning();
}

function _showIdleWarning() {
  const modal = document.getElementById('modal-idle-warning');
  if (!modal) return;
  modal.classList.remove('hidden');

  // Countdown: 60 → 0
  let remaining = Math.round((IDLE_TOTAL_MS - IDLE_WARN_MS) / 1000);
  const el = document.getElementById('idle-countdown');
  if (el) el.textContent = remaining;

  _countdownInterval = setInterval(() => {
    remaining -= 1;
    if (el) el.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(_countdownInterval);
      _countdownInterval = null;
    }
  }, 1000);
}

function _hideIdleWarning() {
  const modal = document.getElementById('modal-idle-warning');
  if (modal) modal.classList.add('hidden');
  if (_countdownInterval) { clearInterval(_countdownInterval); _countdownInterval = null; }
}

async function _forceIdleLogout() {
  _hideIdleWarning();
  stopIdleTimer();
  stopPolling();
  await api.logoutServer();
  api.clearToken();
  api._tempToken = null;
  showLogin();
  // Show info toast after login screen appears
  setTimeout(() => showToast('Сессия завершена по истечении времени бездействия', 'info'), 300);
}

// Called from "Continue" button in warning modal
function idleStayActive() {
  _hideIdleWarning();
  _scheduleIdleTimers();
}

// ─── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', initApp);

window.showLogin       = showLogin;
window.showApp         = showApp;
window.logout          = logout;
window.cancelTotpLogin = cancelTotpLogin;
window.idleStayActive  = idleStayActive;

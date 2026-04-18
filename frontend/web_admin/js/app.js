/**
 * App initialization and auth flow
 */

// ───────────────── AUTH INIT ─────────────────
async function initApp() {
  const token = api.getToken();

  if (token) {
    const res = await api.me();
    if (res.ok) {
      showApp(res.data.username);
      showTab('servers');
      startPolling();
      return;
    }
  }

  showLogin();
}

// ───────────────── LOGIN FORM ─────────────────
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('login-error');
  const errorText = document.getElementById('login-error-text');
  const btn = document.getElementById('login-btn');

  errorEl.classList.add('hidden');
  btn.innerHTML = '<span class="spinner"></span>';
  btn.disabled = true;

  const res = await api.login(username, password);

  btn.innerHTML = '<i class="fas fa-right-to-bracket"></i> Войти';
  btn.disabled = false;

  if (res.ok) {
    api.setToken(res.data.access_token);
    showApp(username);
    showTab('servers');
    startPolling();
  } else {
    errorText.textContent = res.error || 'Неверный логин или пароль';
    errorEl.classList.remove('hidden');
    document.getElementById('login-password').value = '';
  }
});

// ───────────────── POLLING (status sync) ─────────────────
let pollingInterval = null;

function startPolling() {
  // Poll every 30 seconds to refresh server statuses
  pollingInterval = setInterval(async () => {
    const activeTab = document.querySelector('.tab-btn.active')?.dataset?.tab;
    if (activeTab === 'servers') {
      // Silent refresh (no spinner)
      const res = await api.getServers();
      if (res.ok && res.data) {
        // Update status dots without full re-render
        res.data.forEach(server => {
          const dot = document.querySelector(`#server-card-${server.id} .status-dot`);
          if (dot) {
            dot.className = `status-dot ${server.status}`;
          }
        });
      }
    }
  }, 30000);
}

function stopPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
  }
}

// ───────────────── KEYBOARD SHORTCUTS ─────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => m.classList.add('hidden'));
  }
  // Ctrl+1 → Servers, Ctrl+2 → Connections
  if (e.ctrlKey && e.key === '1') { e.preventDefault(); showTab('servers'); }
  if (e.ctrlKey && e.key === '2') { e.preventDefault(); showTab('connections'); }
});

// ───────────────── START ─────────────────
document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

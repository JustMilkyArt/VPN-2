/**
 * UI Utilities: toasts, modals, tabs, helpers
 */

// ─── TOAST ────────────────────────────────────────────────────────────────────

function toast(message, type = 'info', duration = 4000) {
  const icons = {
    success: 'fa-circle-check',
    error:   'fa-circle-exclamation',
    info:    'fa-circle-info',
  };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i><span>${message}</span>`;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity 0.3s, transform 0.3s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(100%)';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// Alias
function showToast(msg, type = 'info') { toast(msg, type); }

// ─── MODALS ───────────────────────────────────────────────────────────────────

function openModal(id) { document.getElementById(id)?.classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id)?.classList.add('hidden'); }

// Close on overlay click
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.add('hidden');
  }
});

// ─── TABS ─────────────────────────────────────────────────────────────────────

function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

  document.getElementById(`tab-${name}`)?.classList.remove('hidden');
  document.querySelector(`[data-tab="${name}"]`)?.classList.add('active');

  if (name === 'servers')     loadServers();
  if (name === 'connections') loadConnectionsGrouped();
  if (name === 'users')       loadUsers();
  if (name === 'domains')     loadDomains();
}

// ─── COPY ─────────────────────────────────────────────────────────────────────

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      btn.textContent = '✓ Скопировано';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = 'Копировать';
        btn.classList.remove('copied');
      }, 2000);
    }
    toast('Скопировано в буфер', 'success', 2000);
  } catch {
    toast('Не удалось скопировать', 'error', 2000);
  }
}

// ─── ESCAPE HTML ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── COUNTRY FLAGS ────────────────────────────────────────────────────────────

function getFlag(country) {
  const code = country?.toUpperCase();
  if (!code || code === '??') {
    return '<span class="flag-globe" title="Unknown">🌍</span>';
  }
  const lower = code.toLowerCase();
  return `<img src="https://flagcdn.com/32x24/${lower}.png" alt="${code}" title="${code}" class="country-flag" onerror="this.style.display='none';this.insertAdjacentHTML('afterend','<span title=&quot;${code}&quot;>🌍</span>')">`;
}

// ─── STATUS HELPERS ───────────────────────────────────────────────────────────

function statusDot(status) {
  const cls = { online: 'online', offline: 'offline', unknown: 'unknown', deploying: 'deploying' };
  return `<span class="status-dot ${cls[status] || 'unknown'}"></span>`;
}

function statusText(status) {
  const labels = {
    online:    '<span class="text-green-400">Online</span>',
    offline:   '<span class="text-red-400">Offline</span>',
    unknown:   '<span class="text-gray-500">Unknown</span>',
    deploying: '<span class="text-amber-400">Deploying...</span>',
    active:    '<span class="text-green-400">Active</span>',
    inactive:  '<span class="text-gray-500">Inactive</span>',
    error:     '<span class="text-red-400">Error</span>',
  };
  return labels[status] || status;
}

function protocolLabel(proto) {
  const map = {
    vless_reality: { text: 'VLESS Reality', icon: 'fa-lock' },
    amnezia_wg:    { text: 'AmneziaWG',     icon: 'fa-shield-halved' },
    trojan:        { text: 'Trojan',         icon: 'fa-bolt' },
    naive_proxy:   { text: 'NaiveProxy',     icon: 'fa-globe' },
  };
  return map[proto] || { text: proto, icon: 'fa-network-wired' };
}

function roleLabel(role) {
  const map = {
    RU:    '<span class="role-badge-ru">RU ENTRY</span>',
    EU:    '<span class="role-badge-eu">EU EXIT</span>',
  };
  return map[role] || role;
}

// ─── LOADING STATE ────────────────────────────────────────────────────────────

function setLoading(elementId, loading) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (loading) {
    el.dataset.originalHtml = el.innerHTML;
    el.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    el.disabled = true;
  } else {
    el.innerHTML = el.dataset.originalHtml || el.innerHTML;
    el.disabled = false;
  }
}

// ─── GLOBAL EXPORTS ───────────────────────────────────────────────────────────

window.showTab      = showTab;
window.toast        = toast;
window.showToast    = showToast;
window.openModal    = openModal;
window.closeModal   = closeModal;
window.copyText     = copyText;
window.escapeHtml   = escapeHtml;
window.getFlag      = getFlag;
window.statusDot    = statusDot;
window.statusText   = statusText;
window.protocolLabel = protocolLabel;
window.roleLabel    = roleLabel;
window.setLoading   = setLoading;

// ─── ESCAPE ATTR ──────────────────────────────────────────────────────────────

function escapeAttr(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

window.escapeAttr = escapeAttr;

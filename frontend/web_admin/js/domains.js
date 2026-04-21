/**
 * Domains tab — full management of domains and subdomains.
 * Porkbun API integration, DNS + SSL + Nginx automation.
 */

// ── State ─────────────────────────────────────────────────────────────────────
let _domains = [];
let _pollTimer = null;
let _pollingSubdomains = new Map(); // subdomainId → { domainId, intervalId }

// ── Type labels ───────────────────────────────────────────────────────────────
const TYPE_LABELS = {
  admin_panel:  { text: 'Админ-панель', cls: 'bg-brand-100 text-brand-700' },
  client_site:  { text: 'Клиентский сайт', cls: 'bg-purple-100 text-purple-700' },
  vpn:          { text: 'VPN', cls: 'bg-green-100 text-green-700' },
  none:         { text: 'Без назначения', cls: 'bg-gray-100 text-gray-600' },
};

const STATUS_LABELS = {
  pending:     { icon: '⏳', cls: 'text-yellow-600', text: 'Ожидание' },
  in_progress: { icon: '🔄', cls: 'text-blue-600',   text: 'Настройка...' },
  active:      { icon: '🟢', cls: 'text-green-600',  text: 'Активен' },
  error:       { icon: '🔴', cls: 'text-red-600',    text: 'Ошибка' },
  reserved:    { icon: '📌', cls: 'text-gray-500',   text: 'Зарезервирован' },
};

const DOMAIN_STATUS_LABELS = {
  pending: { icon: '⏳', cls: 'text-yellow-600', text: 'Проверка...' },
  active:  { icon: '🟢', cls: 'text-green-600',  text: 'Активен' },
  error:   { icon: '🔴', cls: 'text-red-600',    text: 'Ошибка API' },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtDate(dt) {
  if (!dt) return '—';
  const d = new Date(dt);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function showToast(msg, type = 'info') {
  const colors = { success: 'bg-green-500', error: 'bg-red-500', info: 'bg-brand-500' };
  const t = document.createElement('div');
  t.className = `fixed top-4 right-4 z-[9999] px-4 py-3 rounded-lg text-white text-sm shadow-xl ${colors[type] || colors.info}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

// ── Load & Render ─────────────────────────────────────────────────────────────
async function loadDomains() {
  const container = document.getElementById('domains-list');
  if (!container) return;

  container.innerHTML = `
    <div class="flex items-center gap-2 text-gray-400 py-6">
      <div class="spinner"></div><span>Загрузка доменов…</span>
    </div>`;

  const res = await api.getDomains();
  if (!res.ok) {
    container.innerHTML = `<div class="text-red-500 text-sm">Ошибка загрузки: ${res.error}</div>`;
    return;
  }

  _domains = res.data;

  if (_domains.length === 0) {
    container.innerHTML = `
      <div class="empty-state text-center py-12">
        <div class="text-4xl mb-3">🌐</div>
        <p class="text-gray-500 mb-1">Домены ещё не добавлены</p>
        <p class="text-gray-400 text-sm">Нажмите «Добавить домен» чтобы начать</p>
      </div>`;
    return;
  }

  container.innerHTML = _domains.map(renderDomainCard).join('');

  // Restart polling for in-progress subdomains
  _domains.forEach(domain => {
    (domain.subdomains || []).forEach(sub => {
      if (sub.status === 'in_progress' || sub.status === 'pending') {
        startPollingSubdomain(domain.id, sub.id);
      }
    });
  });
}

function renderDomainCard(domain) {
  const ds = DOMAIN_STATUS_LABELS[domain.status] || DOMAIN_STATUS_LABELS.pending;
  const subHtml = (domain.subdomains || []).map(s => renderSubdomainRow(domain, s)).join('');
  const emptyMsg = domain.subdomains?.length === 0
    ? `<div class="text-gray-400 text-sm italic px-2 py-2">Нет поддоменов. Создайте первый.</div>`
    : '';

  return `
  <div class="server-card" id="domain-card-${domain.id}">
    <div class="flex items-start justify-between mb-3">
      <div class="flex items-center gap-3">
        <span class="text-2xl">🌐</span>
        <div>
          <div class="font-semibold text-gray-800 text-lg">${domain.name}</div>
          <div class="text-xs ${ds.cls} flex items-center gap-1 mt-0.5">
            <span>${ds.icon}</span><span>${ds.text}</span>
            ${domain.status_message ? `<span class="text-gray-400">· ${domain.status_message}</span>` : ''}
          </div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button onclick="showCreateSubdomainModal(${domain.id})"
          class="action-btn text-xs px-3 py-1.5 flex items-center gap-1">
          <i class="fas fa-plus"></i> Поддомен
        </button>
        <button onclick="confirmDeleteDomain(${domain.id}, '${domain.name}')"
          class="action-btn danger text-xs px-3 py-1.5 flex items-center gap-1">
          <i class="fas fa-trash"></i>
        </button>
      </div>
    </div>

    <div class="border-t border-gray-100 pt-3 space-y-2" id="subdomains-${domain.id}">
      ${emptyMsg}
      ${subHtml}
    </div>
  </div>`;
}

function renderSubdomainRow(domain, sub) {
  const ss = STATUS_LABELS[sub.status] || STATUS_LABELS.pending;
  const tl = TYPE_LABELS[sub.subdomain_type] || TYPE_LABELS.none;
  const sslBadge = sub.ssl_enabled
    ? `<span class="text-green-500 text-xs flex items-center gap-1"><i class="fas fa-lock"></i>SSL до ${fmtDate(sub.ssl_expires_at)}</span>`
    : `<span class="text-gray-400 text-xs"><i class="fas fa-lock-open"></i> Без SSL</span>`;

  const link = (sub.status === 'active' && sub.ssl_enabled)
    ? `<a href="https://${sub.full_name}" target="_blank" class="text-brand-600 hover:underline text-xs ml-2">
        <i class="fas fa-external-link-alt"></i></a>`
    : '';

  const progressEl = (sub.status === 'in_progress' || sub.status === 'pending')
    ? `<div id="progress-${sub.id}" class="mt-1 text-xs text-blue-500 flex items-center gap-1">
        <div class="spinner" style="width:12px;height:12px;border-width:2px;"></div>
        <span>${sub.status_message || 'Настройка...'}</span></div>`
    : '';

  const errorEl = sub.status === 'error'
    ? `<div class="text-xs text-red-500 mt-1">${sub.status_message || ''}</div>`
    : '';

  return `
  <div class="flex items-start justify-between py-2 px-2 rounded hover:bg-gray-50 transition" id="subdomain-row-${sub.id}">
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="${ss.cls} font-medium text-sm">${ss.icon} ${sub.full_name}</span>
        ${link}
        <span class="text-xs px-1.5 py-0.5 rounded font-medium ${tl.cls}">${tl.text}</span>
        ${sslBadge}
      </div>
      <div class="text-xs text-gray-400 mt-0.5">${ss.text} · IP: ${sub.target_ip || '—'}</div>
      ${progressEl}
      ${errorEl}
    </div>
    <div class="flex items-center gap-1 ml-2 flex-shrink-0">
      ${sub.ssl_enabled ? `
        <button onclick="renewSSL(${domain.id}, ${sub.id})"
          title="Обновить SSL"
          class="action-btn text-xs px-2 py-1"><i class="fas fa-sync-alt"></i></button>` : ''}
      <button onclick="confirmDeleteSubdomain(${domain.id}, ${sub.id}, '${sub.full_name}')"
        class="action-btn danger text-xs px-2 py-1"><i class="fas fa-trash"></i></button>
    </div>
  </div>`;
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPollingSubdomain(domainId, subdomainId) {
  if (_pollingSubdomains.has(subdomainId)) return;

  const intervalId = setInterval(async () => {
    const res = await api.getSubdomainStatus(domainId, subdomainId);
    if (!res.ok) return;

    const sub = res.data;
    updateSubdomainProgress(sub);

    if (sub.status !== 'in_progress' && sub.status !== 'pending') {
      clearInterval(intervalId);
      _pollingSubdomains.delete(subdomainId);
      // Full reload to refresh the card
      await loadDomains();
    }
  }, 2000);

  _pollingSubdomains.set(subdomainId, intervalId);
}

function updateSubdomainProgress(sub) {
  const progressEl = document.getElementById(`progress-${sub.id}`);
  if (!progressEl) return;
  if (sub.status_message) {
    const span = progressEl.querySelector('span');
    if (span) span.textContent = sub.status_message;
  }
}

// ── Add Domain Modal ──────────────────────────────────────────────────────────
function showAddDomainModal() {
  const modal = document.getElementById('modal-add-domain');
  if (!modal) return;
  document.getElementById('add-domain-name').value = '';
  document.getElementById('add-domain-apikey').value = '';
  document.getElementById('add-domain-secret').value = '';
  document.getElementById('add-domain-error').textContent = '';
  document.getElementById('add-domain-btn').disabled = false;
  document.getElementById('add-domain-btn').textContent = 'Добавить';
  modal.classList.remove('hidden');
}

function closeAddDomainModal() {
  document.getElementById('modal-add-domain')?.classList.add('hidden');
}

async function submitAddDomain() {
  const name = document.getElementById('add-domain-name').value.trim();
  const apiKey = document.getElementById('add-domain-apikey').value.trim();
  const secret = document.getElementById('add-domain-secret').value.trim();
  const errEl = document.getElementById('add-domain-error');
  const btn = document.getElementById('add-domain-btn');

  errEl.textContent = '';
  if (!name || !apiKey || !secret) {
    errEl.textContent = 'Заполните все поля';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;"></div> Проверка...';

  const res = await api.addDomain({ name, porkbun_api_key: apiKey, porkbun_secret_key: secret });

  btn.disabled = false;
  btn.textContent = 'Добавить';

  if (!res.ok) {
    errEl.textContent = res.error || 'Ошибка добавления домена';
    return;
  }

  if (res.data.status === 'error') {
    errEl.textContent = res.data.status_message || 'Ошибка проверки API-ключей';
    return;
  }

  showToast(`Домен ${res.data.name} добавлен`, 'success');
  closeAddDomainModal();
  await loadDomains();
}

// ── Create Subdomain Modal ────────────────────────────────────────────────────
let _currentDomainId = null;

function showCreateSubdomainModal(domainId) {
  _currentDomainId = domainId;
  const domain = _domains.find(d => d.id === domainId);
  const modal = document.getElementById('modal-create-subdomain');
  if (!modal || !domain) return;

  document.getElementById('subdomain-domain-name').textContent = domain.name;
  document.getElementById('subdomain-name-input').value = '';
  document.getElementById('subdomain-fullname-preview').textContent = `.${domain.name}`;
  document.getElementById('subdomain-type-select').value = 'admin_panel';
  document.getElementById('create-subdomain-error').textContent = '';
  document.getElementById('create-subdomain-btn').disabled = false;
  document.getElementById('create-subdomain-btn').textContent = 'Создать';

  modal.classList.remove('hidden');
}

function closeCreateSubdomainModal() {
  document.getElementById('modal-create-subdomain')?.classList.add('hidden');
}

async function submitCreateSubdomain() {
  const name = document.getElementById('subdomain-name-input').value.trim().toLowerCase();
  const type = document.getElementById('subdomain-type-select').value;
  const errEl = document.getElementById('create-subdomain-error');
  const btn = document.getElementById('create-subdomain-btn');

  errEl.textContent = '';
  if (!name) {
    errEl.textContent = 'Введите имя поддомена';
    return;
  }
  if (!/^[a-z0-9-]+$/.test(name)) {
    errEl.textContent = 'Только латинские буквы, цифры и дефис';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;"></div> Создание...';

  const res = await api.createSubdomain(_currentDomainId, {
    name,
    subdomain_type: type,
  });

  btn.disabled = false;
  btn.textContent = 'Создать';

  if (!res.ok) {
    errEl.textContent = res.error || 'Ошибка создания поддомена';
    return;
  }

  showToast(`Поддомен ${res.data.full_name} создан, запущена настройка`, 'success');
  closeCreateSubdomainModal();
  await loadDomains();

  // Start polling if needed
  if (res.data.status === 'in_progress' || res.data.status === 'pending') {
    startPollingSubdomain(_currentDomainId, res.data.id);
  }
}

// Live preview of full subdomain name
function onSubdomainNameInput() {
  const name = document.getElementById('subdomain-name-input').value.trim().toLowerCase();
  const domain = _domains.find(d => d.id === _currentDomainId);
  const preview = document.getElementById('subdomain-fullname-preview');
  if (preview && domain) {
    preview.textContent = name ? `${name}.${domain.name}` : `.${domain.name}`;
  }
}

// ── Delete Confirmations ──────────────────────────────────────────────────────
async function confirmDeleteDomain(domainId, name) {
  if (!confirm(`Удалить домен ${name} и все его поддомены?\n\nДействие необратимо!`)) return;
  const res = await api.deleteDomain(domainId);
  if (!res.ok) {
    showToast(`Ошибка удаления: ${res.error}`, 'error');
    return;
  }
  showToast(`Домен ${name} удалён`, 'success');
  await loadDomains();
}

async function confirmDeleteSubdomain(domainId, subdomainId, fullName) {
  if (!confirm(`Удалить поддомен ${fullName}?\nDNS-запись в Porkbun также будет удалена.`)) return;
  const res = await api.deleteSubdomain(domainId, subdomainId);
  if (!res.ok) {
    showToast(`Ошибка удаления: ${res.error}`, 'error');
    return;
  }
  showToast(`Поддомен ${fullName} удалён`, 'success');
  await loadDomains();
}

async function renewSSL(domainId, subdomainId) {
  const res = await api.renewSubdomainSSL(domainId, subdomainId);
  if (!res.ok) {
    showToast(`Ошибка: ${res.error}`, 'error');
    return;
  }
  showToast('Обновление SSL запущено', 'info');
  startPollingSubdomain(domainId, subdomainId);
  await loadDomains();
}

// ── Progress Modal (step log) ─────────────────────────────────────────────────
function showSetupProgressModal(domainId, subdomain) {
  const modal = document.getElementById('modal-setup-progress');
  if (!modal) return;
  modal.classList.remove('hidden');
  document.getElementById('progress-modal-title').textContent = `Настройка: ${subdomain.full_name}`;
  renderProgressSteps(subdomain);
}

function closeProgressModal() {
  document.getElementById('modal-setup-progress')?.classList.add('hidden');
}

function renderProgressSteps(sub) {
  const container = document.getElementById('progress-steps-container');
  if (!container) return;

  let steps = [];
  try { steps = JSON.parse(sub.setup_log || '[]'); } catch { steps = []; }

  if (steps.length === 0) {
    container.innerHTML = '<div class="text-gray-400 text-sm">Ожидание начала настройки…</div>';
    return;
  }

  const icons = { ok: '✅', error: '❌', running: '🔄', skipped: '⏭️' };
  container.innerHTML = steps.map(s => `
    <div class="flex items-start gap-3 py-1.5 border-b border-gray-50 last:border-0">
      <span class="text-lg leading-none">${icons[s.status] || '⏳'}</span>
      <div>
        <div class="text-sm font-medium text-gray-700">${s.step}</div>
        ${s.detail ? `<div class="text-xs text-gray-400 mt-0.5">${s.detail}</div>` : ''}
      </div>
    </div>
  `).join('');
}

// ── Expose globals ────────────────────────────────────────────────────────────
window.loadDomains = loadDomains;
window.showAddDomainModal = showAddDomainModal;
window.closeAddDomainModal = closeAddDomainModal;
window.submitAddDomain = submitAddDomain;
window.showCreateSubdomainModal = showCreateSubdomainModal;
window.closeCreateSubdomainModal = closeCreateSubdomainModal;
window.submitCreateSubdomain = submitCreateSubdomain;
window.onSubdomainNameInput = onSubdomainNameInput;
window.confirmDeleteDomain = confirmDeleteDomain;
window.confirmDeleteSubdomain = confirmDeleteSubdomain;
window.renewSSL = renewSSL;
window.showSetupProgressModal = showSetupProgressModal;
window.closeProgressModal = closeProgressModal;

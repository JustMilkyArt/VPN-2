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
  admin_panel:     { text: 'Админ-панель',     cls: 'bg-brand-100 text-brand-700',   icon: 'fa-shield-halved' },
  client_site:     { text: 'Клиентский сайт',  cls: 'bg-purple-100 text-purple-700', icon: 'fa-globe' },
  vpn:             { text: 'VPN',              cls: 'bg-green-100 text-green-700',   icon: 'fa-lock' },
  swagger:         { text: 'Swagger API',      cls: 'bg-yellow-100 text-yellow-700', icon: 'fa-code' },
  naiveproxy_eu:   { text: 'NaiveProxy EU',    cls: 'bg-sky-100 text-sky-700',       icon: 'fa-earth-europe' },
  naiveproxy_ru:   { text: 'NaiveProxy RU',    cls: 'bg-orange-100 text-orange-700', icon: 'fa-flag' },
  none:            { text: 'Без назначения',   cls: 'bg-gray-100 text-gray-600',     icon: 'fa-minus' },
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
      <div class="text-center py-16">
        <div class="w-14 h-14 bg-gray-800 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <i class="fas fa-globe text-2xl text-gray-600"></i>
        </div>
        <p class="text-gray-400 font-medium mb-1">Домены не добавлены</p>
        <p class="text-gray-600 text-sm mb-4">Добавьте домен через Porkbun API для управления DNS и SSL</p>
        <button onclick="showAddDomainModal()"
          class="px-4 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-medium text-white transition">
          <i class="fas fa-plus mr-2"></i>Добавить домен
        </button>
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
  const subCount = domain.subdomains?.length || 0;

  const emptyMsg = subCount === 0
    ? `<div class="flex items-center gap-2 px-3 py-3 text-gray-500 text-xs">
        <i class="fas fa-info-circle opacity-50"></i>
        <span>Нет поддоменов — нажмите <span class="text-brand-400 font-medium">+ Поддомен</span></span>
       </div>`
    : '';

  const statusDot = domain.status === 'active'
    ? 'bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.6)]'
    : domain.status === 'error' ? 'bg-red-400' : 'bg-yellow-400';

  return `
  <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden" id="domain-card-${domain.id}">
    <!-- Domain header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-800">
      <div class="flex items-center gap-3 min-w-0">
        <span class="w-2 h-2 rounded-full flex-shrink-0 ${statusDot}"></span>
        <span class="font-mono font-semibold text-white text-sm truncate">${domain.name}</span>
        <span class="text-xs text-gray-500 flex-shrink-0">${subCount} поддом.</span>
      </div>
      <div class="flex items-center gap-1 flex-shrink-0">
        <button onclick="showCreateSubdomainModal(${domain.id})"
          title="Добавить поддомен"
          class="p-1.5 rounded-lg text-gray-400 hover:text-brand-400 hover:bg-gray-800 transition text-sm">
          <i class="fas fa-plus"></i>
        </button>
        <button onclick="confirmDeleteDomain(${domain.id}, '${domain.name}')"
          title="Удалить домен"
          class="p-1.5 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition text-sm">
          <i class="fas fa-trash-can"></i>
        </button>
      </div>
    </div>

    <!-- Subdomains list -->
    <div id="subdomains-${domain.id}" class="divide-y divide-gray-800/60">
      ${emptyMsg}
      ${subHtml}
    </div>
  </div>`;
}

function renderSubdomainRow(domain, sub) {
  const ss = STATUS_LABELS[sub.status] || STATUS_LABELS.pending;
  const tl = TYPE_LABELS[sub.subdomain_type] || TYPE_LABELS.none;
  const typeIcon = tl.icon ? `<i class="fas ${tl.icon} mr-1 opacity-70"></i>` : '';

  const isActive = sub.status === 'active';
  const isError = sub.status === 'error';
  const isPending = sub.status === 'in_progress' || sub.status === 'pending';

  const statusColor = isActive ? 'bg-green-500' : isError ? 'bg-red-500' : isPending ? 'bg-blue-400 animate-pulse' : 'bg-gray-500';

  const sslEl = sub.ssl_enabled
    ? `<span class="text-green-400 text-xs flex items-center gap-1"><i class="fas fa-lock text-[10px]"></i>${fmtDate(sub.ssl_expires_at)}</span>`
    : '';

  const extLink = (isActive && sub.ssl_enabled)
    ? `<a href="https://${sub.full_name}" target="_blank"
        class="text-gray-500 hover:text-brand-400 transition text-xs" title="Открыть">
        <i class="fas fa-arrow-up-right-from-square"></i></a>`
    : '';

  const progressEl = isPending
    ? `<div id="progress-${sub.id}" class="mt-1.5 flex items-center gap-1.5 text-xs text-blue-400">
        <div class="spinner" style="width:10px;height:10px;border-width:2px;"></div>
        <span class="truncate">${sub.status_message || 'Настройка...'}</span>
       </div>`
    : '';

  const errorEl = isError
    ? `<div class="mt-1 text-xs text-red-400 truncate" title="${sub.status_message || ''}">${sub.status_message || ''}</div>`
    : '';

  return `
  <div class="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800/40 transition group" id="subdomain-row-${sub.id}">
    <!-- Status dot -->
    <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-0.5 ${statusColor}"></span>

    <!-- Main info -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="font-mono text-sm text-gray-100 truncate">${sub.full_name}</span>
        ${extLink}
        <span class="text-xs px-1.5 py-0.5 rounded font-medium ${tl.cls}">${typeIcon}${tl.text}</span>
        ${sslEl}
      </div>
      <div class="flex items-center gap-2 mt-0.5">
        <span class="text-xs text-gray-500">${ss.text}</span>
        ${sub.target_ip ? `<span class="text-xs text-gray-600">· ${sub.target_ip}</span>` : ''}
      </div>
      ${progressEl}
      ${errorEl}
    </div>

    <!-- Actions (visible on hover) -->
    <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition flex-shrink-0">
      ${sub.ssl_enabled ? `
        <button onclick="renewSSL(${domain.id}, ${sub.id})" title="Обновить SSL"
          class="p-1.5 rounded-lg text-gray-500 hover:text-green-400 hover:bg-gray-700 transition text-xs">
          <i class="fas fa-rotate"></i></button>` : ''}
      <button onclick="confirmDeleteSubdomain(${domain.id}, ${sub.id}, '${sub.full_name}')"
        title="Удалить"
        class="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-gray-700 transition text-xs">
        <i class="fas fa-trash-can"></i>
      </button>
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

  // Заголовок модала — имя домена
  var dnEl = document.getElementById("subdomain-domain-name");
  if (dnEl) dnEl.textContent = domain.name;
  var sfxEl = document.getElementById("subdomain-domain-suffix");
  if (sfxEl) sfxEl.textContent = "." + domain.name;
  document.getElementById('subdomain-name-input').value = '';
  // preview обновляется через onSubdomainNameInput()
  // Smart default: если первый поддомен — ставим admin_panel, иначе vpn
  const existingTypes = (domain.subdomains || []).map(s => s.subdomain_type);
  let defaultType = 'admin_panel';
  if (existingTypes.includes('admin_panel')) {
    defaultType = existingTypes.includes('naiveproxy_eu') ? 'naiveproxy_ru' :
                  existingTypes.includes('swagger') ? 'vpn' : 'naiveproxy_eu';
  }
  document.getElementById('subdomain-type-select').value = defaultType;
  // Обновляем описание под select
  _updateSubdomainTypeHint(defaultType);
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

// Update type hint text when user changes the select
function onSubdomainTypeChange() {
  const type = document.getElementById('subdomain-type-select')?.value;
  _updateSubdomainTypeHint(type);
  // Auto-suggest subdomain name if field is empty
  const nameInput = document.getElementById('subdomain-name-input');
  if (nameInput && !nameInput.value.trim()) {
    const suggestions = {
      admin_panel: 'admin',
      client_site: 'www',
      swagger: 'api',
      naiveproxy_eu: 'eu',
      naiveproxy_ru: 'ru',
      vpn: 'vpn',
      none: '',
    };
    const s = suggestions[type] || '';
    if (s) {
      nameInput.value = s;
      onSubdomainNameInput();
    }
  }
}

function _updateSubdomainTypeHint(type) {
  const hints = {
    admin_panel:   'Создаст A-запись, выпустит SSL и настроит Nginx-прокси для панели управления',
    client_site:   'Создаст A-запись и SSL. Корень сайта настраивается отдельно',
    swagger:       'Создаст A-запись, выпустит SSL и настроит Nginx-прокси для документации API',
    naiveproxy_eu: 'Зарезервирует поддомен для NaiveProxy EU-сервера (A-запись создаётся при настройке)',
    naiveproxy_ru: 'Зарезервирует поддомен для NaiveProxy RU-сервера (A-запись создаётся при настройке)',
    vpn:           'Зарезервирует поддомен для VPN-подключения',
    none:          'Только резервирование. DNS и Nginx не настраиваются',
  };
  const el = document.getElementById('subdomain-type-hint');
  if (el) el.textContent = hints[type] || '';
}

// Live preview of full subdomain name
function onSubdomainNameInput() {
  const name = document.getElementById('subdomain-name-input').value.trim().toLowerCase();
  const domain = _domains.find(d => d.id === _currentDomainId);
  const preview = document.getElementById('subdomain-fullname-preview');
  if (preview && domain) {
    preview.textContent = name ? `${name}.${domain.name}` : `<имя>.${domain.name}`;
  // Обновляем суффикс
  const sfxEl2 = document.getElementById("subdomain-domain-suffix");
  if (sfxEl2 && domain) sfxEl2.textContent = . + domain.name;
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
window.onSubdomainTypeChange = onSubdomainTypeChange;
window.confirmDeleteDomain = confirmDeleteDomain;
window.confirmDeleteSubdomain = confirmDeleteSubdomain;
window.renewSSL = renewSSL;
window.showSetupProgressModal = showSetupProgressModal;
window.closeProgressModal = closeProgressModal;

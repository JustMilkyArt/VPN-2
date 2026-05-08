/**
 * Domains tab — full management of domains and subdomains.
 * Porkbun API integration, DNS + SSL + Nginx automation.
 */

// ── State ─────────────────────────────────────────────────────────────────────
let _domains = [];
let _pollTimer = null;
let _pollingSubdomains = new Map();

// ── Type labels ───────────────────────────────────────────────────────────────
const TYPE_LABELS = {
  admin_panel:   { text: 'Админ-панель',    cls: 'bg-indigo-900 text-indigo-300',  icon: 'fa-shield-halved' },
  client_site:   { text: 'Клиент. сайт',   cls: 'bg-purple-900 text-purple-300',  icon: 'fa-globe' },
  swagger:       { text: 'Swagger API',     cls: 'bg-yellow-900 text-yellow-300',  icon: 'fa-code' },
  naiveproxy_eu: { text: 'NaiveProxy EU',   cls: 'bg-sky-900 text-sky-300',        icon: 'fa-earth-europe' },
  naiveproxy_ru: { text: 'NaiveProxy RU',   cls: 'bg-orange-900 text-orange-300',  icon: 'fa-flag' },
  vpn:           { text: 'VPN',             cls: 'bg-green-900 text-green-300',    icon: 'fa-lock' },
  none:          { text: 'Без назначения',  cls: 'bg-gray-800 text-gray-400',      icon: 'fa-minus' },
};

const STATUS_LABELS = {
  pending:     { cls: 'text-yellow-500', text: 'Ожидание' },
  in_progress: { cls: 'text-blue-400',   text: 'Настройка...' },
  active:      { cls: 'text-green-400',  text: 'Активен' },
  error:       { cls: 'text-red-400',    text: 'Ошибка' },
  reserved:    { cls: 'text-gray-500',   text: 'Зарезервирован' },
};

const DOMAIN_STATUS_LABELS = {
  pending: { cls: 'bg-yellow-400', glow: '' },
  active:  { cls: 'bg-green-400',  glow: 'shadow-[0_0_6px_rgba(74,222,128,0.7)]' },
  error:   { cls: 'bg-red-400',    glow: '' },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtDate(dt) {
  if (!dt) return '';
  const d = new Date(dt);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
}

function showToast(msg, type) {
  type = type || 'info';
  const colors = { success: 'bg-green-600', error: 'bg-red-600', info: 'bg-brand-600' };
  const t = document.createElement('div');
  t.className = 'fixed top-4 right-4 z-[9999] px-4 py-3 rounded-lg text-white text-sm shadow-xl ' + (colors[type] || colors.info);
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function() { t.remove(); }, 3500);
}

// ── Load & Render ─────────────────────────────────────────────────────────────
async function loadDomains() {
  const container = document.getElementById('domains-list');
  if (!container) return;

  container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 py-8 justify-center"><div class="spinner"></div><span class="text-sm">Загрузка доменов…</span></div>';

  const res = await api.getDomains();
  if (!res.ok) {
    container.innerHTML = '<div class="text-red-400 text-sm px-1">Ошибка загрузки: ' + res.error + '</div>';
    return;
  }

  _domains = res.data;

  if (_domains.length === 0) {
    container.innerHTML = [
      '<div class="text-center py-16">',
      '  <div class="w-14 h-14 bg-gray-800 rounded-2xl flex items-center justify-center mx-auto mb-4">',
      '    <i class="fas fa-globe text-2xl text-gray-600"></i>',
      '  </div>',
      '  <p class="text-gray-400 font-medium mb-1">Домены не добавлены</p>',
      '  <p class="text-gray-600 text-sm mb-5">Добавьте домен с API-ключами Porkbun для управления DNS и SSL</p>',
      '  <button onclick="showAddDomainModal()" class="px-4 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-medium text-white transition">',
      '    <i class="fas fa-plus mr-2"></i>Добавить домен',
      '  </button>',
      '</div>'
    ].join('\n');
    return;
  }

  container.innerHTML = _domains.map(renderDomainCard).join('');

  _domains.forEach(function(domain) {
    (domain.subdomains || []).forEach(function(sub) {
      if (sub.status === 'in_progress' || sub.status === 'pending') {
        startPollingSubdomain(domain.id, sub.id);
      }
    });
  });
}

function renderDomainCard(domain) {
  var subs = domain.subdomains || [];
  var subCount = subs.length;
  var ds = DOMAIN_STATUS_LABELS[domain.status] || DOMAIN_STATUS_LABELS.pending;

  var subHtml = subs.map(function(s) { return renderSubdomainRow(domain, s); }).join('');

  var emptyMsg = subCount === 0
    ? '<div class="flex items-center gap-2 px-4 py-3 text-gray-600 text-xs"><i class="fas fa-info-circle opacity-40"></i><span>Нет поддоменов — нажмите <span class="text-brand-400">+</span> чтобы добавить</span></div>'
    : '';

  return [
    '<div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden mb-3" id="domain-card-' + domain.id + '">',
    '  <div class="flex items-center justify-between px-4 py-3 border-b border-gray-800">',
    '    <div class="flex items-center gap-2.5 min-w-0">',
    '      <span class="w-2 h-2 rounded-full flex-shrink-0 ' + ds.cls + ' ' + ds.glow + '"></span>',
    '      <span class="font-mono font-semibold text-white text-sm">' + domain.name + '</span>',
    '      <span class="text-xs text-gray-600">' + subCount + ' поддом.</span>',
    '    </div>',
    '    <div class="flex items-center gap-0.5">',
    '      <button onclick="showCreateSubdomainModal(' + domain.id + ')" title="Добавить поддомен"',
    '        class="p-2 rounded-lg text-gray-500 hover:text-brand-400 hover:bg-gray-800 transition text-xs">',
    '        <i class="fas fa-plus"></i>',
    '      </button>',
    '      <button onclick="confirmDeleteDomain(' + domain.id + ', \'' + domain.name + '\')" title="Удалить домен"',
    '        class="p-2 rounded-lg text-gray-500 hover:text-red-400 hover:bg-gray-800 transition text-xs">',
    '        <i class="fas fa-trash-can"></i>',
    '      </button>',
    '    </div>',
    '  </div>',
    '  <div id="subdomains-' + domain.id + '" class="divide-y divide-gray-800/50">',
    emptyMsg,
    subHtml,
    '  </div>',
    '</div>'
  ].join('\n');
}

function renderSubdomainRow(domain, sub) {
  var ss = STATUS_LABELS[sub.status] || STATUS_LABELS.pending;
  var tl = TYPE_LABELS[sub.subdomain_type] || TYPE_LABELS.none;

  var isActive   = sub.status === 'active';
  var isError    = sub.status === 'error';
  var isPending  = sub.status === 'in_progress' || sub.status === 'pending';
  var isReserved = sub.status === 'reserved';

  var dotCls = isActive ? 'bg-green-400' : isError ? 'bg-red-400' : isPending ? 'bg-blue-400' : 'bg-gray-600';

  var typeBadge = '<span class="text-xs px-1.5 py-0.5 rounded font-medium ' + tl.cls + '">'
    + (tl.icon ? '<i class="fas ' + tl.icon + ' mr-1 opacity-70 text-[10px]"></i>' : '')
    + tl.text + '</span>';

  var sslBadge = (isActive && sub.ssl_enabled)
    ? '<span class="text-green-500 text-xs flex items-center gap-1"><i class="fas fa-lock text-[9px]"></i>' + fmtDate(sub.ssl_expires_at) + '</span>'
    : '';

  var extLink = (isActive && sub.ssl_enabled)
    ? '<a href="https://' + sub.full_name + '" target="_blank" class="text-gray-600 hover:text-brand-400 transition text-xs" title="Открыть сайт"><i class="fas fa-arrow-up-right-from-square"></i></a>'
    : '';

  var statusLine = '<span class="text-xs ' + ss.cls + '">' + ss.text + '</span>'
    + (sub.target_ip ? '<span class="text-xs text-gray-700">· ' + sub.target_ip + '</span>' : '');

  var progressEl = isPending
    ? '<div id="progress-' + sub.id + '" class="mt-1 flex items-center gap-1.5 text-xs text-blue-400"><div class="spinner" style="width:10px;height:10px;border-width:2px;"></div><span class="truncate">' + (sub.status_message || 'Настройка...') + '</span></div>'
    : '';

  var errorEl = isError
    ? '<div class="mt-1 text-xs text-red-400 truncate">' + (sub.status_message || '') + '</div>'
    : '';

  var sslBtn = sub.ssl_enabled
    ? '<button onclick="renewSSL(' + domain.id + ', ' + sub.id + ')" title="Обновить SSL" class="p-1.5 rounded text-gray-600 hover:text-green-400 hover:bg-gray-700 transition text-xs"><i class="fas fa-rotate"></i></button>'
    : '';

  var delBtn = '<button onclick="confirmDeleteSubdomain(' + domain.id + ', ' + sub.id + ', \'' + sub.full_name + '\')" title="Удалить" class="p-1.5 rounded text-gray-600 hover:text-red-400 hover:bg-gray-700 transition text-xs"><i class="fas fa-trash-can"></i></button>';

  return [
    '<div class="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800/30 transition group" id="subdomain-row-' + sub.id + '">',
    '  <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 ' + dotCls + '"></span>',
    '  <div class="flex-1 min-w-0">',
    '    <div class="flex items-center gap-2 flex-wrap">',
    '      <span class="font-mono text-sm text-gray-100">' + sub.full_name + '</span>',
    '      ' + extLink,
    '      ' + typeBadge,
    '      ' + sslBadge,
    '    </div>',
    '    <div class="flex items-center gap-2 mt-0.5">' + statusLine + '</div>',
    '    ' + progressEl,
    '    ' + errorEl,
    '  </div>',
    '  <div class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition flex-shrink-0">',
    '    ' + sslBtn,
    '    ' + delBtn,
    '  </div>',
    '</div>'
  ].join('\n');
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPollingSubdomain(domainId, subdomainId) {
  if (_pollingSubdomains.has(subdomainId)) return;

  var intervalId = setInterval(async function() {
    var res = await api.getSubdomainStatus(domainId, subdomainId);
    if (!res.ok) return;
    var sub = res.data;
    updateSubdomainProgress(sub);
    if (sub.status !== 'in_progress' && sub.status !== 'pending') {
      clearInterval(intervalId);
      _pollingSubdomains.delete(subdomainId);
      await loadDomains();
    }
  }, 2000);

  _pollingSubdomains.set(subdomainId, intervalId);
}

function updateSubdomainProgress(sub) {
  var el = document.getElementById('progress-' + sub.id);
  if (!el) return;
  if (sub.status_message) {
    var span = el.querySelector('span');
    if (span) span.textContent = sub.status_message;
  }
}

// ── Add Domain Modal ──────────────────────────────────────────────────────────
function showAddDomainModal() {
  var modal = document.getElementById('modal-add-domain');
  if (!modal) return;
  document.getElementById('add-domain-name').value = '';
  document.getElementById('add-domain-apikey').value = '';
  document.getElementById('add-domain-secret').value = '';
  document.getElementById('add-domain-error').textContent = '';
  var btn = document.getElementById('add-domain-btn');
  btn.disabled = false;
  btn.textContent = 'Добавить';
  modal.classList.remove('hidden');
}

function closeAddDomainModal() {
  var modal = document.getElementById('modal-add-domain');
  if (modal) modal.classList.add('hidden');
}

async function submitAddDomain() {
  var name   = document.getElementById('add-domain-name').value.trim();
  var apiKey = document.getElementById('add-domain-apikey').value.trim();
  var secret = document.getElementById('add-domain-secret').value.trim();
  var errEl  = document.getElementById('add-domain-error');
  var btn    = document.getElementById('add-domain-btn');

  errEl.textContent = '';
  if (!name || !apiKey || !secret) { errEl.textContent = 'Заполните все поля'; return; }

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;"></div> Проверка...';

  var res = await api.addDomain({ name: name, porkbun_api_key: apiKey, porkbun_secret_key: secret });

  btn.disabled = false;
  btn.textContent = 'Добавить';

  if (!res.ok) { errEl.textContent = res.error || 'Ошибка добавления домена'; return; }
  if (res.data.status === 'error') { errEl.textContent = res.data.status_message || 'Ошибка проверки API-ключей'; return; }

  showToast('Домен ' + res.data.name + ' добавлен', 'success');
  closeAddDomainModal();
  await loadDomains();
}

// ── Create Subdomain Modal ────────────────────────────────────────────────────
var _currentDomainId = null;

// Подсказки для каждого типа
var _typeHints = {
  admin_panel:   'Создаст A-запись, выпустит SSL и настроит Nginx-прокси для панели управления',
  client_site:   'Создаст A-запись и SSL. Корень сайта настраивается отдельно',
  swagger:       'Создаст A-запись, выпустит SSL и настроит Nginx-прокси для Swagger UI',
  naiveproxy_eu: 'Зарезервирует поддомен для NaiveProxy EU (A-запись при установке стека)',
  naiveproxy_ru: 'Зарезервирует поддомен для NaiveProxy RU (A-запись при установке стека)',
};

// Авто-имена для каждого типа
var _typeSuggestions = {
  admin_panel:   'admin',
  client_site:   'www',
  swagger:       'api',
  naiveproxy_eu: 'eu',
  naiveproxy_ru: 'ru',
};

function showCreateSubdomainModal(domainId) {
  _currentDomainId = domainId;
  var domain = _domains.find(function(d) { return d.id === domainId; });
  var modal = document.getElementById('modal-create-subdomain');
  if (!modal || !domain) return;

  // Показываем имя домена в шапке и суффикс
  var dnEl = document.getElementById('subdomain-domain-name');
  if (dnEl) dnEl.textContent = domain.name;
  var sfxEl = document.getElementById('subdomain-domain-suffix');
  if (sfxEl) sfxEl.textContent = '.' + domain.name;

  // Умный выбор типа по умолчанию
  var existingTypes = (domain.subdomains || []).map(function(s) { return s.subdomain_type; });
  var defaultType = 'admin_panel';
  if (existingTypes.indexOf('admin_panel') !== -1) {
    if (existingTypes.indexOf('naiveproxy_eu') === -1) defaultType = 'naiveproxy_eu';
    else if (existingTypes.indexOf('naiveproxy_ru') === -1) defaultType = 'naiveproxy_ru';
    else if (existingTypes.indexOf('swagger') === -1) defaultType = 'swagger';
    else defaultType = 'client_site';
  }

  document.getElementById('subdomain-type-select').value = defaultType;
  _updateTypeHint(defaultType);

  // Авто-подсказка имени
  var nameInput = document.getElementById('subdomain-name-input');
  nameInput.value = _typeSuggestions[defaultType] || '';
  _updateFullNamePreview(domain, nameInput.value);

  document.getElementById('create-subdomain-error').textContent = '';
  var btn = document.getElementById('create-subdomain-btn');
  btn.disabled = false;
  btn.textContent = 'Создать';

  modal.classList.remove('hidden');
}

function closeCreateSubdomainModal() {
  var modal = document.getElementById('modal-create-subdomain');
  if (modal) modal.classList.add('hidden');
}

function _updateTypeHint(type) {
  var el = document.getElementById('subdomain-type-hint');
  if (el) el.textContent = _typeHints[type] || '';
}

function _updateFullNamePreview(domain, name) {
  var preview = document.getElementById('subdomain-fullname-preview');
  if (!preview || !domain) return;
  preview.textContent = name ? name + '.' + domain.name : '….' + domain.name;
}

function onSubdomainNameInput() {
  var name = document.getElementById('subdomain-name-input').value.trim().toLowerCase();
  var domain = _domains.find(function(d) { return d.id === _currentDomainId; });
  _updateFullNamePreview(domain, name);
}

function onSubdomainTypeChange() {
  var type = document.getElementById('subdomain-type-select').value;
  _updateTypeHint(type);
  var nameInput = document.getElementById('subdomain-name-input');
  if (nameInput && !nameInput.value.trim()) {
    var s = _typeSuggestions[type] || '';
    if (s) {
      nameInput.value = s;
      onSubdomainNameInput();
    }
  }
}

async function submitCreateSubdomain() {
  var name   = document.getElementById('subdomain-name-input').value.trim().toLowerCase();
  var type   = document.getElementById('subdomain-type-select').value;
  var errEl  = document.getElementById('create-subdomain-error');
  var btn    = document.getElementById('create-subdomain-btn');

  errEl.textContent = '';
  if (!name) { errEl.textContent = 'Введите имя поддомена'; return; }
  if (!/^[a-z0-9-]+$/.test(name)) { errEl.textContent = 'Только латинские буквы, цифры и дефис'; return; }

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;"></div> Создание...';

  var res = await api.createSubdomain(_currentDomainId, { name: name, subdomain_type: type });

  btn.disabled = false;
  btn.textContent = 'Создать';

  if (!res.ok) { errEl.textContent = res.error || 'Ошибка создания поддомена'; return; }

  showToast('Поддомен ' + res.data.full_name + ' создан', 'success');
  closeCreateSubdomainModal();
  await loadDomains();

  if (res.data.status === 'in_progress' || res.data.status === 'pending') {
    startPollingSubdomain(_currentDomainId, res.data.id);
  }
}

// ── Delete Confirmations ──────────────────────────────────────────────────────
async function confirmDeleteDomain(domainId, name) {
  if (!confirm('Удалить домен ' + name + ' и все его поддомены?\n\nДействие необратимо!')) return;
  var res = await api.deleteDomain(domainId);
  if (!res.ok) { showToast('Ошибка удаления: ' + res.error, 'error'); return; }
  showToast('Домен ' + name + ' удалён', 'success');
  await loadDomains();
}

async function confirmDeleteSubdomain(domainId, subdomainId, fullName) {
  if (!confirm('Удалить поддомен ' + fullName + '?\nDNS-запись в Porkbun также будет удалена.')) return;
  var res = await api.deleteSubdomain(domainId, subdomainId);
  if (!res.ok) { showToast('Ошибка удаления: ' + res.error, 'error'); return; }
  showToast('Поддомен ' + fullName + ' удалён', 'success');
  await loadDomains();
}

async function renewSSL(domainId, subdomainId) {
  var res = await api.renewSubdomainSSL(domainId, subdomainId);
  if (!res.ok) { showToast('Ошибка: ' + res.error, 'error'); return; }
  showToast('Обновление SSL запущено', 'info');
  startPollingSubdomain(domainId, subdomainId);
  await loadDomains();
}

// ── Progress Modal ────────────────────────────────────────────────────────────
function showSetupProgressModal(domainId, subdomain) {
  var modal = document.getElementById('modal-setup-progress');
  if (!modal) return;
  modal.classList.remove('hidden');
  document.getElementById('progress-modal-title').textContent = 'Настройка: ' + subdomain.full_name;
  renderProgressSteps(subdomain);
}

function closeProgressModal() {
  var modal = document.getElementById('modal-setup-progress');
  if (modal) modal.classList.add('hidden');
}

function renderProgressSteps(sub) {
  var container = document.getElementById('progress-steps-container');
  if (!container) return;
  var steps = [];
  try { steps = JSON.parse(sub.setup_log || '[]'); } catch(e) { steps = []; }
  if (steps.length === 0) {
    container.innerHTML = '<div class="text-gray-500 text-sm">Ожидание начала настройки…</div>';
    return;
  }
  var icons = { ok: '✅', error: '❌', running: '🔄', skipped: '⏭️' };
  container.innerHTML = steps.map(function(s) {
    return '<div class="flex items-start gap-3 py-1.5 border-b border-gray-800 last:border-0">'
      + '<span class="text-base leading-none">' + (icons[s.status] || '⏳') + '</span>'
      + '<div><div class="text-sm font-medium text-gray-300">' + s.step + '</div>'
      + (s.detail ? '<div class="text-xs text-gray-500 mt-0.5">' + s.detail + '</div>' : '')
      + '</div></div>';
  }).join('');
}

// ── Expose globals ────────────────────────────────────────────────────────────
window.loadDomains             = loadDomains;
window.showAddDomainModal      = showAddDomainModal;
window.closeAddDomainModal     = closeAddDomainModal;
window.submitAddDomain         = submitAddDomain;
window.showCreateSubdomainModal  = showCreateSubdomainModal;
window.closeCreateSubdomainModal = closeCreateSubdomainModal;
window.submitCreateSubdomain   = submitCreateSubdomain;
window.onSubdomainNameInput    = onSubdomainNameInput;
window.onSubdomainTypeChange   = onSubdomainTypeChange;
window.confirmDeleteDomain     = confirmDeleteDomain;
window.confirmDeleteSubdomain  = confirmDeleteSubdomain;
window.renewSSL                = renewSSL;
window.showSetupProgressModal  = showSetupProgressModal;
window.closeProgressModal      = closeProgressModal;

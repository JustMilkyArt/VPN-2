/**
 * Connections tab — v3
 * UX: 2-step wizard (type → servers) → deploy logs modal
 * UI: grouped by EU server → direct / cascade rows
 *     Connection detail: 3 tabs (Configs / Params / Info)
 */

// ─── LOAD & RENDER LIST ──────────────────────────────────────────────────────

async function loadConnectionsGrouped() {
  const listEl  = document.getElementById('connections-list');
  const emptyEl = document.getElementById('connections-empty');
  listEl.innerHTML = `<div class="flex justify-center py-10"><span class="spinner"></span></div>`;

  const res = await api.get('/connections/grouped');
  if (!res.ok) {
    listEl.innerHTML = `<div class="text-center text-red-400 py-8">
      <i class="fas fa-circle-exclamation mr-2"></i>Ошибка загрузки: ${res.error}</div>`;
    return;
  }

  const groups = res.data;
  if (!groups || groups.length === 0) {
    listEl.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }

  emptyEl.classList.add('hidden');
  listEl.innerHTML = groups.map(renderEuGroup).join('');

  // Автоматически запускаем фоновую проверку статусов после отрисовки
  _checkAllConnectionsBackground();
}

// ─── EU SERVER GROUP ─────────────────────────────────────────────────────────

function renderEuGroup(group) {
  const srv    = group.eu_server;
  const flag   = getFlag(srv.country);
  const online = srv.status === 'online';

  // Collect all connection IDs for this group (for per-server refresh)
  const allConns = [...(group.direct || []), ...(group.cascade || [])];
  const connIds  = allConns.map(c => c.id);

  const directRows  = (group.direct  || []).map(c => renderConnRow(c, srv, 'direct')).join('');
  const cascadeRows = (group.cascade || []).map(c => renderConnRow(c, srv, 'cascade')).join('');

  const hasRows = directRows || cascadeRows;
  if (!hasRows) return '';

  return `
<div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden mb-4" id="conn-group-${srv.id}">

  <!-- EU server header -->
  <div class="flex items-center justify-between px-4 py-3 bg-gray-800/60 border-b border-gray-800">
    <div class="flex items-center gap-2.5">
      <span class="text-xl leading-none">${flag}</span>
      <div>
        <div class="font-semibold text-white text-sm">${escapeHtml(srv.name)}</div>
        <div class="text-gray-500 text-xs font-mono">${srv.ip}</div>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <!-- Status indicator -->
      <div class="flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full ${online ? 'bg-green-400' : 'bg-gray-600'}"></span>
        <span class="text-xs ${online ? 'text-green-400' : 'text-gray-500'}">${online ? 'Online' : srv.status}</span>
      </div>
      <!-- Refresh button for this server group -->
      <button id="refresh-group-btn-${srv.id}"
        onclick="checkServerGroup(${srv.id}, [${connIds.join(',')}])"
        class="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-gray-700/60 transition"
        title="Проверить подключения этого сервера">
        <i class="fas fa-arrows-rotate text-xs"></i>
      </button>
    </div>
  </div>

  <!-- Connection rows -->
  <div class="divide-y divide-gray-800/60">
    ${directRows ? `
    <div>
      <div class="px-4 py-1.5 bg-gray-800/30">
        <span class="text-[10px] font-semibold uppercase tracking-widest text-gray-500">
          <i class="fas fa-arrow-right mr-1"></i>Прямые подключения
        </span>
      </div>
      <div class="divide-y divide-gray-800/40">${directRows}</div>
    </div>` : ''}
    ${cascadeRows ? `
    <div>
      <div class="px-4 py-1.5 bg-gray-800/30">
        <span class="text-[10px] font-semibold uppercase tracking-widest text-gray-500">
          <i class="fas fa-shuffle mr-1"></i>Каскадные подключения
        </span>
      </div>
      <div class="divide-y divide-gray-800/40">${cascadeRows}</div>
    </div>` : ''}
  </div>
</div>`;
}

// ─── CONNECTION ROW ──────────────────────────────────────────────────────────

const PROTO_META = {
  vless_reality: { icon: 'fa-shield-halved', label: 'VLESS+Reality', color: 'text-violet-400 bg-violet-900/30 border-violet-800/50' },
  amnezia_wg:    { icon: 'fa-lock',          label: 'AmneziaWG',     color: 'text-blue-400   bg-blue-900/30   border-blue-800/50'   },
  naive_proxy:   { icon: 'fa-globe',          label: 'NaiveProxy',    color: 'text-emerald-400 bg-emerald-900/30 border-emerald-800/50'},
  trojan:        { icon: 'fa-bolt',           label: 'Trojan',        color: 'text-amber-400  bg-amber-900/30  border-amber-800/50'  },
};

const STATUS_META = {
  active:         { dot: 'bg-green-400',  text: 'text-green-400',  label: 'Активно'         },
  inactive:       { dot: 'bg-gray-500',   text: 'text-gray-500',   label: 'Неактивно'       },
  deploying:      { dot: 'bg-amber-400 animate-pulse', text: 'text-amber-400', label: 'Деплой...' },
  error:          { dot: 'bg-red-400',    text: 'text-red-400',    label: 'Ошибка'          },
  server_offline: { dot: 'bg-gray-600',   text: 'text-gray-500',   label: 'Сервер недоступен' },
};

function renderConnRow(conn, euSrv, type) {
  const pm = PROTO_META[conn.protocol] || { icon: 'fa-network-wired', label: conn.protocol, color: 'text-gray-400 bg-gray-800 border-gray-700' };
  // If the EU exit server is offline — show connection as unavailable regardless of DB status
  const effectiveStatus = (euSrv && euSrv.status !== 'online') ? 'server_offline' : conn.status;
  const sm = STATUS_META[effectiveStatus] || STATUS_META.inactive;

  // For cascade: show RU → EU
  let serverLabel = '';
  if (type === 'cascade' && conn.ru_server) {
    const ruFlag = getFlag(conn.ru_server.country);
    const euFlag = getFlag(euSrv.country);
    serverLabel = `${ruFlag} ${escapeHtml(conn.ru_server.name)} → ${euFlag} ${escapeHtml(euSrv.name)}`;
  } else {
    serverLabel = `${getFlag(euSrv.country)} ${escapeHtml(euSrv.name)}`;
  }

  return `
<div class="conn-row flex items-center gap-3 px-4 py-3 hover:bg-gray-800/30 transition group" id="conn-row-${conn.id}">

  <!-- Protocol badge -->
  <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold flex-shrink-0 ${pm.color}">
    <i class="fas ${pm.icon} text-[10px]"></i>${pm.label}
  </span>

  <!-- Server info -->
  <div class="flex-1 min-w-0">
    <div class="text-xs text-gray-400 truncate">${serverLabel}</div>
    <div class="text-[11px] text-gray-600 font-mono">:${conn.port}</div>
  </div>

  <!-- Status -->
  <div class="flex items-center gap-1.5 flex-shrink-0">
    <span class="conn-status-dot w-1.5 h-1.5 rounded-full ${sm.dot}"></span>
    <span class="conn-status-text text-xs ${sm.text}">${sm.label}</span>
  </div>

  <!-- Actions: delete (hover) + open (always visible) -->
  <div class="flex items-center gap-1 flex-shrink-0">
    <button onclick="confirmDeleteConnection(${conn.id})"
      class="opacity-0 group-hover:opacity-100 transition action-btn text-gray-600 hover:text-red-400" title="Удалить">
      <i class="fas fa-trash text-xs"></i>
    </button>
    <button onclick="showConnDetail(${conn.id})"
      class="action-btn text-gray-600 hover:text-brand-400 transition" title="Открыть">
      <i class="fas fa-chevron-right text-xs"></i>
    </button>
  </div>
</div>`;
}


// ═══════════════════════════════════════════════════════════════════════════
// WIZARD — создать подключения
// ═══════════════════════════════════════════════════════════════════════════

let _wizardState = {
  step:         1,
  createDirect:  false,
  createCascade: false,
  canDirect:     false,
  canCascade:    false,
  euServers:     [],
  ruServers:     [],
};

async function showAddConnectionModal() {
  _wizardState = { step: 1, createDirect: false, createCascade: false,
                   canDirect: false, canCascade: false, euServers: [], ruServers: [] };

  // Load available servers
  const res = await api.get('/connections/available-servers');
  if (!res.ok) { toast('Не удалось загрузить серверы', 'error'); return; }

  _wizardState.canDirect  = res.data.can_direct;
  _wizardState.canCascade = res.data.can_cascade;
  _wizardState.euServers  = res.data.eu_servers;
  _wizardState.ruServers  = res.data.ru_servers;

  _renderWizardStep1();
  openModal('modal-wizard-conn');
}

// ── STEP 1: type selector ────────────────────────────────────────────────────

function _renderWizardStep1() {
  _wizardState.step = 1;
  const body = document.getElementById('wizard-body');
  const footer = document.getElementById('wizard-footer');

  const { canDirect, canCascade } = _wizardState;

  body.innerHTML = `
<div class="space-y-4">
  <p class="text-sm text-gray-400">Выберите один или оба типа подключений для создания:</p>

  <div class="grid grid-cols-2 gap-3">
    <!-- Direct -->
    <button id="wiz-btn-direct"
      onclick="wizToggleType('direct')"
      class="wiz-type-btn relative flex flex-col items-center justify-center gap-2 p-5 rounded-xl border-2 transition
             ${canDirect ? 'border-gray-700 bg-gray-800/50 hover:border-gray-500 cursor-pointer' : 'border-gray-800 bg-gray-800/20 opacity-40 cursor-not-allowed'}"
      ${!canDirect ? 'disabled' : ''}>
      <i class="fas fa-arrow-right text-2xl text-gray-400"></i>
      <span class="font-semibold text-sm text-white">Прямое</span>
      ${!canDirect ? '<span class="text-[10px] text-gray-600 mt-0.5">Нет EU серверов</span>' : ''}
      <span id="wiz-check-direct" class="absolute top-2 right-2 w-5 h-5 rounded-full bg-brand-600 text-white flex items-center justify-center text-xs hidden">
        <i class="fas fa-check"></i>
      </span>
    </button>

    <!-- Cascade -->
    <button id="wiz-btn-cascade"
      onclick="wizToggleType('cascade')"
      class="wiz-type-btn relative flex flex-col items-center justify-center gap-2 p-5 rounded-xl border-2 transition
             ${canCascade ? 'border-gray-700 bg-gray-800/50 hover:border-gray-500 cursor-pointer' : 'border-gray-800 bg-gray-800/20 opacity-40 cursor-not-allowed'}"
      ${!canCascade ? 'disabled' : ''}>
      <i class="fas fa-shuffle text-2xl text-gray-400"></i>
      <span class="font-semibold text-sm text-white">Каскадное</span>
      ${!canCascade ? '<span class="text-[10px] text-gray-600 mt-0.5">Нет RU или EU</span>' : ''}
      <span id="wiz-check-cascade" class="absolute top-2 right-2 w-5 h-5 rounded-full bg-brand-600 text-white flex items-center justify-center text-xs hidden">
        <i class="fas fa-check"></i>
      </span>
    </button>
  </div>

  <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg p-3 text-xs text-gray-500">
    <i class="fas fa-info-circle text-brand-400 mr-1.5"></i>
    Будут автоматически созданы все протоколы: VLESS+Reality, AmneziaWG, NaiveProxy
  </div>
</div>`;

  footer.innerHTML = `
<div class="flex justify-between items-center">
  <button onclick="closeModal('modal-wizard-conn')"
    class="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm font-medium transition">
    Отмена
  </button>
  <button id="wiz-next-btn" onclick="wizGoStep2()"
    disabled
    class="px-5 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg text-sm font-semibold text-white transition flex items-center gap-2">
    Далее <i class="fas fa-arrow-right text-xs"></i>
  </button>
</div>`;
}

function wizToggleType(type) {
  if (type === 'direct'  && !_wizardState.canDirect)  return;
  if (type === 'cascade' && !_wizardState.canCascade) return;

  if (type === 'direct')  _wizardState.createDirect  = !_wizardState.createDirect;
  if (type === 'cascade') _wizardState.createCascade = !_wizardState.createCascade;

  // Update button styles
  ['direct', 'cascade'].forEach(t => {
    const btn   = document.getElementById(`wiz-btn-${t}`);
    const check = document.getElementById(`wiz-check-${t}`);
    const sel   = t === 'direct' ? _wizardState.createDirect : _wizardState.createCascade;
    if (!btn) return;
    btn.classList.toggle('border-brand-500', sel);
    btn.classList.toggle('bg-brand-900/20', sel);
    btn.classList.toggle('border-gray-700', !sel);
    btn.classList.toggle('bg-gray-800/50', !sel);
    check.classList.toggle('hidden', !sel);
  });

  // Enable/disable Next button
  const nextBtn = document.getElementById('wiz-next-btn');
  const anySelected = _wizardState.createDirect || _wizardState.createCascade;
  nextBtn.disabled = !anySelected;
}

// ── STEP 2: server selection ─────────────────────────────────────────────────

function wizGoStep2() {
  if (!_wizardState.createDirect && !_wizardState.createCascade) return;
  _wizardState.step = 2;

  // If BOTH selected, cascade drives the EU choice (one EU covers both)
  const needEU = _wizardState.createDirect || _wizardState.createCascade;
  const needRU = _wizardState.createCascade;

  const euOptions = _wizardState.euServers.map(s =>
    `<option value="${s.id}">${getFlag(s.country)} ${escapeHtml(s.name)} (${s.ip})</option>`
  ).join('');
  const ruOptions = _wizardState.ruServers.map(s =>
    `<option value="${s.id}">${getFlag(s.country)} ${escapeHtml(s.name)} (${s.ip})</option>`
  ).join('');

  const directSection = (_wizardState.createDirect && !_wizardState.createCascade) ? `
<div>
  <label class="form-label">EU сервер (выходной)</label>
  <div class="custom-select-wrap">
    <select id="wiz-eu-select" class="form-input custom-select" required>
      <option value="">— Выберите EU сервер —</option>${euOptions}
    </select>
  </div>
</div>` : '';

  const cascadeSection = needRU ? `
<div class="space-y-3">
  ${needRU && _wizardState.createDirect ? '<p class="text-xs text-gray-500">EU сервер будет использован для обоих типов</p>' : ''}
  <div>
    <label class="form-label">RU сервер (входной)</label>
    <div class="custom-select-wrap">
      <select id="wiz-ru-select" class="form-input custom-select" required>
        <option value="">— Выберите RU сервер —</option>${ruOptions}
      </select>
    </div>
  </div>
  <div>
    <label class="form-label">EU сервер (выходной)</label>
    <div class="custom-select-wrap">
      <select id="wiz-eu-select" class="form-input custom-select" required>
        <option value="">— Выберите EU сервер —</option>${euOptions}
      </select>
    </div>
  </div>
</div>` : '';

  const body = document.getElementById('wizard-body');
  body.innerHTML = `
<div class="space-y-4">
  <div class="flex items-center gap-2 text-sm text-gray-400 mb-1">
    ${_wizardState.createDirect  ? '<span class="px-2 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs"><i class="fas fa-arrow-right mr-1"></i>Прямое</span>' : ''}
    ${_wizardState.createCascade ? '<span class="px-2 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs"><i class="fas fa-shuffle mr-1"></i>Каскадное</span>' : ''}
  </div>
  ${directSection}
  ${cascadeSection}
</div>`;

  const footer = document.getElementById('wizard-footer');
  footer.innerHTML = `
<div class="flex justify-between items-center">
  <button onclick="_renderWizardStep1()"
    class="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm font-medium transition flex items-center gap-2">
    <i class="fas fa-arrow-left text-xs"></i> Назад
  </button>
  <button onclick="wizSubmit()"
    class="px-5 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-semibold text-white transition flex items-center gap-2">
    <i class="fas fa-rocket text-xs"></i> Создать подключения
  </button>
</div>`;
}

// ── SUBMIT ────────────────────────────────────────────────────────────────────

async function wizSubmit() {
  const euSelect = document.getElementById('wiz-eu-select');
  const ruSelect = document.getElementById('wiz-ru-select');

  const euServerId = euSelect ? parseInt(euSelect.value) : null;
  const ruServerId = ruSelect ? parseInt(ruSelect.value) : null;

  if (!euServerId) { toast('Выберите EU сервер', 'error'); return; }
  if (_wizardState.createCascade && !ruServerId) { toast('Выберите RU сервер', 'error'); return; }

  closeModal('modal-wizard-conn');

  const res = await api.post('/connections/batch', {
    eu_server_id:   euServerId,
    ru_server_id:   ruServerId || null,
    create_direct:  _wizardState.createDirect,
    create_cascade: _wizardState.createCascade,
  });

  if (!res.ok) {
    toast(`Ошибка создания: ${res.error}`, 'error');
    return;
  }

  const { connection_ids, connections } = res.data;

  // Collect connection metadata for conn-setup modal
  const connTypes = (connections || connection_ids.map(id => ({ id, protocol: '?', connection_type: '?' })));

  // Determine EU server name from wizard state
  const euSrv = (_wizardState.servers || []).find(s => s.id === euServerId);
  const euName = euSrv ? (euSrv.display_name || euSrv.name || euSrv.ip) : '';

  // Try new conn-setup modal; fall back to old deploy-log modal
  const connSetupModal = document.getElementById('modal-conn-setup');
  if (connSetupModal) {
    openConnSetupModal(connection_ids, euName, connTypes);
    _startConnSetupPolling(connection_ids);
    // Also keep old polling for backward compat (updates deploy-log-body in background)
    _startDeployPolling(connection_ids);
  } else {
    _openDeployLogModal();
    _startDeployPolling(connection_ids);
  }
}


// ═══════════════════════════════════════════════════════════════════════════
// DEPLOY LOG MODAL  — пошаговый UI со статус-иконками
// ═══════════════════════════════════════════════════════════════════════════

let _pollInterval = null;

// Карты меток
const _PROTO_LABEL = { vless_reality: 'VLESS', amnezia_wg: 'AWG', naive_proxy: 'NaiveProxy', trojan: 'TRJ' };
const _TYPE_LABEL  = { direct: 'DIRECT', cascade: 'CASCADE' };

// Иконки и цвета для статусов шагов
const _STEP_ICON = {
  running: '<span class="inline-block w-4 h-4 rounded-full border-2 border-blue-400 border-t-transparent animate-spin mr-2 flex-shrink-0"></span>',
  ok:      '<span class="mr-2 flex-shrink-0 text-green-400">✅</span>',
  error:   '<span class="mr-2 flex-shrink-0 text-red-400">❌</span>',
  skip:    '<span class="mr-2 flex-shrink-0 text-gray-500">⏭</span>',
  info:    '<span class="mr-2 flex-shrink-0 text-gray-500">·</span>',
};
const _STEP_TEXT_CLASS = {
  running: 'text-blue-300',
  ok:      'text-green-300',
  error:   'text-red-300',
  skip:    'text-gray-500',
  info:    'text-gray-400',
};

function _setDeployDot(state) {
  const dot = document.getElementById('deploy-log-dot');
  if (!dot) return;
  if (state === 'running') {
    dot.style.background   = '#7c3aed';
    dot.style.boxShadow    = '0 0 0 3px rgba(124,58,237,.25)';
  } else if (state === 'done') {
    dot.style.background   = '#16a34a';
    dot.style.boxShadow    = '0 0 0 3px rgba(22,163,74,.25)';
  } else if (state === 'error') {
    dot.style.background   = '#dc2626';
    dot.style.boxShadow    = '0 0 0 3px rgba(220,38,38,.25)';
  }
}

function _openDeployLogModal() {
  const body = document.getElementById('deploy-log-body');
  body.innerHTML = '';
  document.getElementById('deploy-log-status').textContent = 'Инициализация...';
  document.getElementById('deploy-log-close').style.display = 'none';
  document.getElementById('deploy-log-spinner').style.display = '';
  const prog = document.getElementById('deploy-log-progress');
  if (prog) prog.style.width = '0%';
  _setDeployDot('running');
  // Show modal (wizard-style — not using openModal to avoid overlay conflict)
  const m = document.getElementById('modal-deploy-log');
  if (m) m.classList.remove('hidden');
}

function _deployLogError(msg) {
  document.getElementById('deploy-log-status').textContent = 'Ошибка';
  document.getElementById('deploy-log-spinner').style.display = 'none';
  const closeBtn = document.getElementById('deploy-log-close');
  closeBtn.style.display = '';
  _setDeployDot('error');
  const body = document.getElementById('deploy-log-body');
  const div = document.createElement('div');
  div.className = 'flex items-start py-1 text-red-400 text-xs font-mono';
  div.innerHTML = `${_STEP_ICON.error}<span>${msg}</span>`;
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}

// Хранилище карточек подключений: { [connId]: { el, stepEls: {stepN: el} } }
let _connCards = {};

function _getOrCreateConnCard(c, body) {
  if (_connCards[c.id]) return _connCards[c.id];

  const protoLabel = _PROTO_LABEL[c.protocol] || c.protocol;
  const typeLabel  = _TYPE_LABEL[c.connection_type] || c.connection_type || '';
  const typeColor  = c.connection_type === 'direct' ? 'text-cyan-400' : 'text-purple-400';

  const card = document.createElement('div');
  card.className = 'mb-4 rounded-lg border border-gray-700 bg-gray-800/50 overflow-hidden';
  card.innerHTML = `
    <div class="flex items-center justify-between px-3 py-2 bg-gray-700/40 border-b border-gray-700">
      <span class="font-semibold text-sm text-white">${protoLabel}
        <span class="ml-1 text-xs font-normal ${typeColor}">${typeLabel}</span>
      </span>
      <span class="conn-card-badge text-xs px-2 py-0.5 rounded-full bg-gray-600 text-gray-300">ожидание...</span>
    </div>
    <div class="conn-card-steps px-3 py-2 space-y-1"></div>
  `;
  body.appendChild(card);

  _connCards[c.id] = {
    el:       card,
    badge:    card.querySelector('.conn-card-badge'),
    stepsEl:  card.querySelector('.conn-card-steps'),
    stepEls:  {},
  };
  return _connCards[c.id];
}

function _renderSteps(c) {
  const body = document.getElementById('deploy-log-body');
  const cardData = _getOrCreateConnCard(c, body);
  const steps = c.steps || [];

  // Update badge based on setup_status
  const badge = cardData.badge;
  if (c.setup_status === 'done') {
    badge.className = 'conn-card-badge text-xs px-2 py-0.5 rounded-full bg-green-900/60 text-green-400';
    badge.textContent = 'готово ✅';
  } else if (c.setup_status === 'failed') {
    badge.className = 'conn-card-badge text-xs px-2 py-0.5 rounded-full bg-red-900/60 text-red-400';
    badge.textContent = 'ошибка ❌';
  } else {
    badge.className = 'conn-card-badge text-xs px-2 py-0.5 rounded-full bg-blue-900/40 text-blue-300';
    badge.textContent = 'выполняется...';
  }

  steps.forEach(step => {
    const key = step.is_step ? `step_${step.n}` : `info_${step.msg.slice(0, 30)}`;
    const st  = step.status || 'info';
    const icon = _STEP_ICON[st] || _STEP_ICON.info;
    const textCls = _STEP_TEXT_CLASS[st] || _STEP_TEXT_CLASS.info;

    if (cardData.stepEls[key]) {
      // Update existing row
      const row = cardData.stepEls[key];
      row.innerHTML = `${icon}<span class="${textCls} text-xs font-mono leading-5">${step.msg}</span>`;
    } else {
      // Create new row
      const row = document.createElement('div');
      row.className = 'flex items-start py-0.5';
      row.innerHTML = `${icon}<span class="${textCls} text-xs font-mono leading-5">${step.msg}</span>`;
      cardData.stepsEl.appendChild(row);
      cardData.stepEls[key] = row;
    }
  });

  document.getElementById('deploy-log-body').scrollTop =
    document.getElementById('deploy-log-body').scrollHeight;
}

function _startDeployPolling(connIds) {
  if (_pollInterval) clearInterval(_pollInterval);
  _connCards = {};
  document.getElementById('deploy-log-body').innerHTML = '';

  const statusEl = document.getElementById('deploy-log-status');
  const progEl   = document.getElementById('deploy-log-progress');

  _pollInterval = setInterval(async () => {
    const res = await api.get(`/connections/batch-status?ids=${connIds.join(',')}`);
    if (!res.ok) return;

    const { connections, all_done, any_failed } = res.data;
    connections.forEach(c => _renderSteps(c));

    const done   = connections.filter(c => c.setup_status === 'done').length;
    const failed = connections.filter(c => c.setup_status === 'failed').length;
    const total  = connections.length;
    statusEl.textContent = `${done}/${total} готово${failed ? `, ${failed} ошибок` : ''}`;

    // Update progress bar
    if (progEl) {
      const pct = total ? Math.round((done + failed) / total * 100) : 0;
      progEl.style.width = pct + '%';
      progEl.style.background = any_failed
        ? 'linear-gradient(90deg,#7f1d1d,#dc2626)'
        : 'linear-gradient(90deg,#6d28d9,#7c3aed,#8b5cf6)';
    }

    if (all_done) {
      clearInterval(_pollInterval);
      _pollInterval = null;
      document.getElementById('deploy-log-spinner').style.display = 'none';
      const closeBtn = document.getElementById('deploy-log-close');
      closeBtn.style.display = '';
      if (progEl) progEl.style.width = '100%';
      _setDeployDot(any_failed ? 'error' : 'done');
      statusEl.textContent = any_failed
        ? `Завершено с ошибками (${failed}/${total})`
        : `Все подключения настроены (${total}/${total}) ✅`;
      loadConnectionsGrouped();
    }
  }, 2000);
}

function closeDeployLog() {
  if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
  const m = document.getElementById('modal-deploy-log');
  if (m) m.classList.add('hidden');
}

// CONNECTION DETAIL MODAL
// ═══════════════════════════════════════════════════════════════════════════

let _detailConnId = null;

async function showConnDetail(connId) {
  _detailConnId = connId;
  openModal('modal-conn-detail');

  const header  = document.getElementById('conn-detail-header');
  const content = document.getElementById('conn-detail-content');
  header.innerHTML  = `<span class="text-gray-500 text-sm">Загрузка…</span>`;
  content.innerHTML = `<div class="flex justify-center py-8"><span class="spinner"></span></div>`;

  const res = await api.get(`/connections/${connId}`, { timeout: 10000 });

  // Если модал закрыли пока шла загрузка — ничего не рисуем
  if (document.getElementById('modal-conn-detail').classList.contains('hidden')) return;

  if (!res.ok) {
    // 401 уже обработан в api.js (закрыл модал, показал логин)
    if (res.status === 401) return;
    header.innerHTML  = `<span class="text-red-400 text-sm"><i class="fas fa-circle-exclamation mr-1"></i>Ошибка</span>`;
    content.innerHTML = `<div class="text-red-400 text-sm p-4">
      <i class="fas fa-triangle-exclamation mr-2"></i>${res.error || 'Неизвестная ошибка'}
      <br><button onclick="showConnDetail(${connId})" class="mt-3 text-xs text-brand-400 hover:underline">
        <i class="fas fa-rotate-right mr-1"></i>Повторить
      </button></div>`;
    return;
  }

  try {
    _renderConnDetail(res.data);
  } catch (err) {
    console.error('[showConnDetail] render error:', err);
    const header  = document.getElementById('conn-detail-header');
    const content = document.getElementById('conn-detail-content');
    if (header)  header.innerHTML  = `<span class="text-red-400 text-sm"><i class="fas fa-circle-exclamation mr-1"></i>Ошибка рендера</span>`;
    if (content) content.innerHTML = `<div class="text-red-400 text-sm p-4">
      <i class="fas fa-bug mr-2"></i><b>JS ошибка:</b> ${err.message}
      <br><pre class="mt-2 text-xs text-gray-400 whitespace-pre-wrap">${err.stack || ''}</pre>
      <br><button onclick="showConnDetail(${connId})" class="mt-3 text-xs text-brand-400 hover:underline">
        <i class="fas fa-rotate-right mr-1"></i>Повторить
      </button></div>`;
  }
}

function _renderConnDetail(conn) {
  const pm = PROTO_META[conn.protocol] || { icon: 'fa-network-wired', label: conn.protocol, color: 'text-gray-400 bg-gray-800 border-gray-700' };
  const sm = STATUS_META[conn.status] || STATUS_META.inactive;

  const content = document.getElementById('conn-detail-content');

  // Header
  document.getElementById('conn-detail-header').innerHTML = `
<div class="flex items-center gap-3">
  <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold ${pm.color}">
    <i class="fas ${pm.icon} text-[10px]"></i>${pm.label}
  </span>
  <div class="flex items-center gap-1.5">
    <span class="w-2 h-2 rounded-full ${sm.dot}"></span>
    <span class="text-sm ${sm.text}">${sm.label}</span>
  </div>
</div>`;

  content.innerHTML = `
<!-- Tabs -->
<div class="flex gap-1 mb-4 border-b border-gray-800 pb-0">
  ${['configs','params','info'].map((t,i) => `
  <button onclick="switchDetailTab('${t}')"
    id="dtab-btn-${t}"
    class="detail-tab-btn px-4 py-2 text-sm font-medium border-b-2 transition -mb-px
           ${i===0 ? 'border-brand-500 text-white' : 'border-transparent text-gray-500 hover:text-gray-300'}">
    ${ t==='configs' ? '<i class="fas fa-download mr-1.5"></i>Конфиги' :
       t==='params'  ? '<i class="fas fa-sliders mr-1.5"></i>Параметры' :
                       '<i class="fas fa-circle-info mr-1.5"></i>Инфо' }
  </button>`).join('')}
</div>

<!-- Configs tab -->
<div id="dtab-configs" class="detail-tab-pane space-y-3">
  ${_renderConfigsTab(conn)}
</div>

<!-- Params tab -->
<div id="dtab-params" class="detail-tab-pane hidden space-y-3">
  ${_renderParamsTab(conn)}
</div>

<!-- Info tab -->
<div id="dtab-info" class="detail-tab-pane hidden space-y-3">
  ${_renderInfoTab(conn)}
</div>`;

  // QR generation
  _maybeGenQR(conn);
}

function switchDetailTab(name) {
  document.querySelectorAll('.detail-tab-pane').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.detail-tab-btn').forEach(el => {
    el.classList.remove('border-brand-500', 'text-white');
    el.classList.add('border-transparent', 'text-gray-500');
  });
  document.getElementById(`dtab-${name}`).classList.remove('hidden');
  const btn = document.getElementById(`dtab-btn-${name}`);
  btn.classList.add('border-brand-500', 'text-white');
  btn.classList.remove('border-transparent', 'text-gray-500');
}

// ── Configs tab ──────────────────────────────────────────────────────────────

function _renderConfigsTab(conn) {
  const hasUri  = !!conn.client_link;
  const hasConf = !!conn.config_text;
  const proto   = conn.protocol;
  const SUB_TOKEN = 'dnBuOm1pbGt5aW1zMjAyNA==';
  const subBase = `${location.origin}/api/v1/subscribe/${SUB_TOKEN}`;

  if (!hasUri && !hasConf) return `
<div class="text-center py-8 text-gray-500 text-sm">
  <i class="fas fa-hourglass-half text-2xl mb-2 block"></i>
  Конфиги ещё не сгенерированы — дождитесь завершения деплоя
</div>`;

  // ── VLESS+Reality ──────────────────────────────────────────────────────────
  if (proto === 'vless_reality') return `

<!-- Способ 1: URI -->
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div class="flex items-center justify-between">
    <div>
      <span class="text-xs font-semibold text-white">Способ 1 — URI / QR-код</span>
      <div class="text-xs text-gray-500 mt-0.5">
        <i class="fas fa-mobile-alt mr-1"></i>v2rayTun · HAPP · AmneziaVPN · Hiddify · v2rayNG (Android)
      </div>
    </div>
    <button class="copy-btn text-xs" data-copy-id="uri-${conn.id}">
      <i class="fas fa-copy mr-1"></i>Копировать
    </button>
  </div>
  <div id="uri-${conn.id}" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 break-all select-all max-h-24 overflow-y-auto border border-gray-700">${escapeHtml(conn.client_link)}</div>
  <div class="flex justify-center pt-1">
    <div id="conn-qr-canvas" class="bg-gray-900 rounded-xl p-2" style="min-width:180px;min-height:180px;display:flex;align-items:center;justify-content:center;"></div>
  </div>
  <p class="text-center text-xs text-gray-600">Отсканируй QR или скопируй URI</p>
</div>

<!-- Способ 2: Subscription -->
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div>
    <span class="text-xs font-semibold text-white">Способ 2 — Subscription URL</span>
    <div class="text-xs text-gray-500 mt-0.5">
      <i class="fas fa-mobile-alt mr-1"></i>sing-box · Hiddify · Clash/Mihomo
    </div>
    <p class="text-xs text-gray-600 mt-1">Одна ссылка — все активные подключения сразу</p>
  </div>
  <div class="space-y-2">
    <div class="flex items-center gap-2">
      <span class="text-xs text-gray-400 w-20 shrink-0 font-medium">sing-box</span>
      <div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-sb-${conn.id}">${subBase}?format=singbox</div>
      <button class="copy-btn text-xs shrink-0" data-copy-id="sub-sb-${conn.id}"><i class="fas fa-copy"></i></button>
    </div>
    <div class="flex items-center gap-2">
      <span class="text-xs text-gray-400 w-20 shrink-0 font-medium">Clash</span>
      <div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-cl-${conn.id}">${subBase}?format=clash</div>
      <button class="copy-btn text-xs shrink-0" data-copy-id="sub-cl-${conn.id}"><i class="fas fa-copy"></i></button>
    </div>
  </div>
</div>`;

  // ── AmneziaWG ──────────────────────────────────────────────────────────────
  if (proto === 'amnezia_wg') return `

<!-- Способ 1: .conf файл -->
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div class="flex items-center justify-between">
    <div>
      <span class="text-xs font-semibold text-white">Способ 1 — .conf файл</span>
      <div class="text-xs text-gray-500 mt-0.5">
        <i class="fas fa-mobile-alt mr-1"></i>AmneziaVPN (iOS / Android / Desktop)
      </div>
    </div>
    <div class="flex gap-2">
      <button class="copy-btn text-xs" data-copy-id="conf-${conn.id}">
        <i class="fas fa-copy mr-1"></i>Копировать
      </button>
      <button onclick="downloadConfig(${conn.id})" class="copy-btn text-xs">
        <i class="fas fa-download mr-1"></i>Скачать
      </button>
    </div>
  </div>
  <pre id="conf-${conn.id}" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 whitespace-pre-wrap break-all select-all max-h-44 overflow-y-auto border border-gray-700">${escapeHtml(conn.config_text || '')}</pre>
</div>

<!-- Способ 2: QR -->
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div>
    <span class="text-xs font-semibold text-white">Способ 2 — QR-код</span>
    <div class="text-xs text-gray-500 mt-0.5">
      <i class="fas fa-mobile-alt mr-1"></i>AmneziaVPN (iOS / Android)
    </div>
  </div>
  <div class="flex justify-center">
    <div id="conn-qr-canvas" class="bg-gray-900 rounded-xl p-2" style="min-width:180px;min-height:180px;display:flex;align-items:center;justify-content:center;"></div>
  </div>
  <p class="text-center text-xs text-gray-600">Отсканируй QR в приложении AmneziaVPN</p>
</div>

<div class="bg-yellow-900/30 border border-yellow-700/50 rounded-xl p-3">
  <p class="text-xs text-yellow-400">
    <i class="fas fa-triangle-exclamation mr-1"></i>
    AmneziaWG работает <strong>только</strong> в приложении AmneziaVPN.
    Стандартный WireGuard не подойдёт.
  </p>
</div>`;

  // ── NaiveProxy ─────────────────────────────────────────────────────────────
  if (proto === 'naive_proxy') return `

<!-- Способ 1: Subscription -->
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div>
    <span class="text-xs font-semibold text-white">Способ 1 — Subscription URL</span>
    <div class="text-xs text-gray-500 mt-0.5">
      <i class="fas fa-mobile-alt mr-1"></i>sing-box · Hiddify · Clash/Mihomo
    </div>
    <p class="text-xs text-gray-600 mt-1">Одна ссылка — все активные подключения сразу</p>
  </div>
  <div class="space-y-2">
    <div class="flex items-center gap-2">
      <span class="text-xs text-gray-400 w-20 shrink-0 font-medium">sing-box</span>
      <div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-sb-${conn.id}">${subBase}?format=singbox</div>
      <button class="copy-btn text-xs shrink-0" data-copy-id="sub-sb-${conn.id}"><i class="fas fa-copy"></i></button>
    </div>
    <div class="flex items-center gap-2">
      <span class="text-xs text-gray-400 w-20 shrink-0 font-medium">Clash</span>
      <div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-cl-${conn.id}">${subBase}?format=clash</div>
      <button class="copy-btn text-xs shrink-0" data-copy-id="sub-cl-${conn.id}"><i class="fas fa-copy"></i></button>
    </div>
  </div>
</div>

<!-- Способ 2: JSON конфиг -->
${hasConf ? `
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div class="flex items-center justify-between">
    <div>
      <span class="text-xs font-semibold text-white">Способ 2 — JSON конфиг</span>
      <div class="text-xs text-gray-500 mt-0.5">
        <i class="fas fa-desktop mr-1"></i>NaiveProxy CLI (Windows / macOS / Linux)
      </div>
    </div>
    <div class="flex gap-2">
      <button class="copy-btn text-xs" data-copy-id="conf-${conn.id}">
        <i class="fas fa-copy mr-1"></i>Копировать
      </button>
      <button onclick="downloadConfig(${conn.id})" class="copy-btn text-xs">
        <i class="fas fa-download mr-1"></i>Скачать
      </button>
    </div>
  </div>
  <pre id="conf-${conn.id}" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 whitespace-pre-wrap break-all select-all max-h-44 overflow-y-auto border border-gray-700">${escapeHtml(conn.config_text)}</pre>
</div>` : ''}

<div class="bg-blue-900/30 border border-blue-700/50 rounded-xl p-3">
  <p class="text-xs text-blue-400">
    <i class="fas fa-circle-info mr-1"></i>
    NaiveProxy работает через HTTPS-прокси. Добавляй через Subscription URL — так название отобразится корректно.
  </p>
</div>`;

  // ── Fallback (неизвестный протокол) ────────────────────────────────────────
  return `
${hasUri ? `
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div class="flex items-center justify-between">
    <span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">URI</span>
    <button class="copy-btn text-xs" data-copy-id="uri-${conn.id}"><i class="fas fa-copy mr-1"></i>Копировать</button>
  </div>
  <div id="uri-${conn.id}" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 break-all select-all max-h-28 overflow-y-auto border border-gray-700">${escapeHtml(conn.client_link)}</div>
</div>` : ''}
${hasConf ? `
<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
  <div class="flex items-center justify-between">
    <span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Конфиг</span>
    <button class="copy-btn text-xs" data-copy-id="conf-${conn.id}"><i class="fas fa-copy mr-1"></i>Копировать</button>
  </div>
  <pre id="conf-${conn.id}" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 whitespace-pre-wrap break-all select-all max-h-40 overflow-y-auto border border-gray-700">${escapeHtml(conn.config_text)}</pre>
</div>` : ''}
<div class="flex justify-center pt-1">
  <div id="conn-qr-canvas" class="bg-gray-900 rounded-xl p-2" style="min-width:180px;min-height:180px;display:flex;align-items:center;justify-content:center;"></div>
</div>`;
}

function _maybeGenQR(conn) {
  const qrEl = document.getElementById('conn-qr-canvas');
  if (!qrEl) return;

  let raw = conn.client_link || conn.config_text || '';
  if (!raw) {
    qrEl.innerHTML = '<div class="text-xs text-gray-600 text-center p-4">QR недоступен</div>';
    return;
  }

  // Для vless:// / trojan:// — убираем тег после # (эмодзи ломают QR-библиотеку).
  // Тег после # — только косметика для клиента, на подключение не влияет.
  // Для WireGuard .conf и NaiveProxy JSON — оставляем как есть.
  let qrData = raw;
  if (/^vless:\/\//i.test(raw) || /^trojan:\/\//i.test(raw)) {
    qrData = raw.split('#')[0];
  }

  // Библиотека QRCode не умеет кодировать строки длиннее ~2953 байт (уровень L)
  if (qrData.length > 2048) {
    qrEl.innerHTML = '<div class="text-xs text-gray-600 text-center p-4">URI слишком длинный для QR</div>';
    return;
  }

  qrEl.innerHTML = ''; // очищаем перед перегенерацией
  try {
    new QRCode(qrEl, {
      text: qrData,
      width: 196, height: 196,
      colorDark: '#ffffff', colorLight: '#111827',
      correctLevel: QRCode.CorrectLevel.M,
    });
  } catch(e) {
    qrEl.innerHTML = '<div class="text-xs text-gray-600 text-center p-4">QR ошибка</div>';
  }
}

function downloadConfig(connId) {
  window.open(`/api/v1/connections/${connId}/download`, '_blank');
}

// ── Params tab ───────────────────────────────────────────────────────────────

function _renderParamsTab(conn) {
  if (conn.protocol === 'vless_reality') {
    return _paramsVless(conn);
  } else if (conn.protocol === 'amnezia_wg') {
    return _paramsAwg(conn);
  } else if (conn.protocol === 'naive_proxy') {
    return _paramsNaive(conn);
  }
  return '<div class="text-gray-500 text-sm text-center py-6">Параметры не доступны</div>';
}

function _paramRow(label, field, value, connId, type='text', opts=null) {
  const inputId = `param-${connId}-${field}`;
  let inputEl;

  if (type === 'select' && opts) {
    inputEl = `<select id="${inputId}" class="form-input form-input-sm flex-1 min-w-0">
      ${opts.map(o => `<option value="${o.value}" ${o.value===value?'selected':''}>${escapeHtml(o.label)}</option>`).join('')}
    </select>`;
  } else if (type === 'toggle') {
    inputEl = `<label class="toggle-switch">
      <input type="checkbox" id="${inputId}" ${value ? 'checked' : ''}>
      <span class="toggle-slider"></span>
    </label>`;
  } else {
    inputEl = `<input type="${type}" id="${inputId}" value="${escapeHtml(String(value||''))}"
      class="form-input form-input-sm flex-1 min-w-0 font-mono text-xs">`;
  }

  return `
<div class="flex items-center gap-3 py-2 border-b border-gray-800 last:border-0">
  <span class="text-xs text-gray-500 w-32 flex-shrink-0">${label}</span>
  <div class="flex items-center gap-2 flex-1 min-w-0">
    ${inputEl}
    <button onclick="applyParam(${connId},'${field}',document.getElementById('${inputId}'))"
      class="flex-shrink-0 px-2.5 py-1 bg-gray-700 hover:bg-brand-600 rounded text-xs text-gray-300 hover:text-white transition flex items-center gap-1">
      <i class="fas fa-check text-[10px]"></i>
    </button>
  </div>
</div>`;
}

function _paramsVless(conn) {
  const sniOptions = (window._sniListCache || []).map(s => ({ value: s.domain, label: (s.best?'⭐ ':'')+s.domain }));
  const fpOptions  = ['chrome','firefox','safari','ios','android','edge','360','qq','random','randomized']
    .map(f => ({ value: f, label: f }));

  return `
<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1">
  ${_paramRow('Server Name (SNI)', 'reality_server_name', conn.reality_server_name, conn.id, 'select', sniOptions.length ? sniOptions : [{value: conn.reality_server_name, label: conn.reality_server_name}])}
  ${_paramRow('Fingerprint', 'reality_fingerprint', conn.reality_fingerprint, conn.id, 'select', fpOptions)}
  ${_paramRow('Port', 'port', conn.port, conn.id, 'number')}
  ${_paramRow('UUID', 'uuid', conn.uuid, conn.id, 'text')}
  ${_paramRow('Public Key', 'reality_public_key', conn.reality_public_key, conn.id, 'text')}
  ${_paramRow('Short ID', 'reality_short_id', conn.reality_short_id, conn.id, 'text')}
  ${_paramRow('Split-tunnel RU', 'split_tunnel_enabled', conn.split_tunnel_enabled, conn.id, 'toggle')}
</div>`;
}

function _paramsAwg(conn) {
  return `
<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1">
  ${_paramRow('Port',    'port', conn.port, conn.id, 'number')}
  ${_paramRow('Jc (count)',   'awg_junk_packet_count',    conn.awg_junk_packet_count,    conn.id, 'number')}
  ${_paramRow('Jmin (min)',   'awg_junk_packet_min_size', conn.awg_junk_packet_min_size, conn.id, 'number')}
  ${_paramRow('Jmax (max)',   'awg_junk_packet_max_size', conn.awg_junk_packet_max_size, conn.id, 'number')}
  ${_paramRow('S1',  'awg_s1', conn.awg_s1, conn.id, 'number')}
  ${_paramRow('S2',  'awg_s2', conn.awg_s2, conn.id, 'number')}
  ${_paramRow('H1',  'awg_h1', conn.awg_h1, conn.id, 'number')}
  ${_paramRow('H2',  'awg_h2', conn.awg_h2, conn.id, 'number')}
  ${_paramRow('H3',  'awg_h3', conn.awg_h3, conn.id, 'number')}
  ${_paramRow('H4',  'awg_h4', conn.awg_h4, conn.id, 'number')}
  ${_paramRow('Split-tunnel RU', 'split_tunnel_enabled', conn.split_tunnel_enabled, conn.id, 'toggle')}
</div>`;
}

function _paramsNaive(conn) {
  return `
<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1">
  ${_paramRow('Домен',    'np_domain', conn.np_domain, conn.id, 'text')}
  ${_paramRow('Username', 'np_user',   conn.np_user,   conn.id, 'text')}
  ${_paramRow('Password', 'password',  conn.password,  conn.id, 'text')}
  ${_paramRow('Port',     'port',      conn.port,      conn.id, 'number')}
  ${_paramRow('Split-tunnel RU', 'split_tunnel_enabled', conn.split_tunnel_enabled, conn.id, 'toggle')}
</div>`;
}

async function applyParam(connId, field, inputEl) {
  let value = inputEl.type === 'checkbox' ? inputEl.checked : inputEl.value;
  if (inputEl.type === 'number') value = parseInt(value);

  const btn = inputEl.parentElement.querySelector('button');
  if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin text-[10px]"></i>';

  const res = await api.patch(`/connections/${connId}/param`, { field, value });

  if (btn) btn.innerHTML = res.ok
    ? '<i class="fas fa-check text-[10px] text-green-400"></i>'
    : '<i class="fas fa-xmark text-[10px] text-red-400"></i>';

  setTimeout(() => {
    if (btn) btn.innerHTML = '<i class="fas fa-check text-[10px]"></i>';
  }, 2500);

  if (!res.ok) toast(`Ошибка: ${res.error}`, 'error');
  else toast('Параметр обновлён и применён', 'success', 2000);
}

// ── Info tab ─────────────────────────────────────────────────────────────────

function _renderInfoTab(conn) {
  const typeLabel = conn.connection_type === 'direct' ? 'Прямое' : 'Каскадное';
  const created   = conn.created_at ? new Date(conn.created_at).toLocaleString('ru-RU') : '—';

  // Название в клиенте: приоритет client_name из API, иначе строим сами
  const srv        = conn.server || {};
  const flag       = srv.flag_emoji   || '';
  const dname      = srv.display_name || srv.name || srv.ip || '';
  const protoLabel = { vless_reality: 'VLESS', amnezia_wg: 'AWG', naive_proxy: 'NaiveProxy' }[conn.protocol] || conn.protocol;
  const ctype      = conn.connection_type || 'direct';
  const clientName = conn.client_name || ([flag, dname].filter(Boolean).join(' ') + ` | ${protoLabel} (${ctype})`);

  // RU сервер (для cascade)
  let serverInfo = '';
  if (conn.ru_server) {
    const ruFlag = conn.ru_server.flag_emoji || getFlag(conn.ru_server.country);
    serverInfo = `
    <div class="flex justify-between py-2 border-b border-gray-800">
      <span class="text-xs text-gray-500">RU сервер (вход)</span>
      <span class="text-xs text-white">${ruFlag} ${escapeHtml(conn.ru_server.name)} (${conn.ru_server.ip})</span>
    </div>`;
  }

  // EU сервер
  const euFlag = flag || (srv.country ? getFlag(srv.country) : '');
  const euLabel = dname ? `${euFlag} ${escapeHtml(dname)}` : (srv.ip || '—');

  return `
<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-0">

  <!-- Название в клиенте — самая важная строка -->
  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">Название в клиенте</span>
    <span class="text-sm font-medium text-white">${escapeHtml(clientName)}</span>
  </div>

  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">ID</span>
    <span class="text-xs text-gray-400 font-mono">#${conn.id}</span>
  </div>
  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">Тип</span>
    <span class="text-xs text-white">${typeLabel}</span>
  </div>
  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">Протокол</span>
    <span class="text-xs text-white">${(PROTO_META[conn.protocol]||{label:conn.protocol}).label}</span>
  </div>
  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">EU сервер (выход)</span>
    <span class="text-xs text-white">${euLabel}</span>
  </div>
  ${serverInfo}
  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">Порт</span>
    <span class="text-xs text-gray-400 font-mono">${conn.port}</span>
  </div>
  <div class="flex justify-between py-2 border-b border-gray-800">
    <span class="text-xs text-gray-500">Split-tunnel</span>
    <span class="text-xs ${conn.split_tunnel_enabled ? 'text-green-400' : 'text-gray-500'}">${conn.split_tunnel_enabled ? 'Включён' : 'Выключен'}</span>
  </div>
  <div class="flex items-center justify-between py-2 border-b border-gray-800">
    <div>
      <span class="text-xs text-gray-500">WARP fallback</span>
      <p class="text-[10px] text-gray-600 mt-0.5">Cloudflare WARP как запасной outbound в Xray</p>
    </div>
    <label class="toggle-switch flex-shrink-0" title="Включить/выключить WARP fallback">
      <input type="checkbox" id="warp-toggle-${conn.id}" ${conn.warp_enabled ? 'checked' : ''}
        onchange="toggleWarp(${conn.id}, this.checked)">
      <span class="toggle-slider"></span>
    </label>
  </div>
  <div class="flex justify-between py-2">
    <span class="text-xs text-gray-500">Создан</span>
    <span class="text-xs text-gray-400">${created}</span>
  </div>
</div>

<div class="flex gap-2 mt-2">
  <button onclick="checkConnLive(${conn.id})"
    class="flex-1 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs font-medium transition flex items-center justify-center gap-2">
    <i class="fas fa-stethoscope"></i> Проверить
  </button>
  <button onclick="confirmDeleteConnection(${conn.id})"
    class="py-2 px-3 bg-red-900/30 hover:bg-red-900/50 border border-red-800/50 rounded-lg text-xs text-red-400 transition flex items-center gap-1.5">
    <i class="fas fa-trash text-[10px]"></i> Удалить
  </button>
</div>`;
}

async function checkConnLive(connId) {
  const res = await api.post(`/connections/${connId}/check`, {});
  if (res.ok) {
    const { alive, message } = res.data;
    toast(alive ? `✅ ${message}` : `⚠️ ${message}`, alive ? 'success' : 'warning', 3000);
    // Обновляем точку статуса прямо в строке без перерисовки всего списка
    _applyConnStatusInRow(connId, res.data.status);
    showConnDetail(connId);
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

// ─── CHECK ALL / CHECK GROUP ─────────────────────────────────────────────────

/**
 * Обновляет точку статуса и текст в строке подключения на лету,
 * без перерисовки всего списка.
 */
function _applyConnStatusInRow(connId, statusKey) {
  const row = document.getElementById(`conn-row-${connId}`);
  if (!row) return;
  const sm  = STATUS_META[statusKey] || STATUS_META.inactive;
  const dot = row.querySelector('.conn-status-dot');
  const txt = row.querySelector('.conn-status-text');
  if (dot) { dot.className = `conn-status-dot w-1.5 h-1.5 rounded-full ${sm.dot}`; }
  if (txt) { txt.className = `conn-status-text text-xs ${sm.text}`; txt.textContent = sm.label; }
}

/**
 * Ставит кнопку обновления группы в состояние «крутится» или «готово».
 */
function _setGroupBtnSpinning(srvId, spinning) {
  const btn = document.getElementById(`refresh-group-btn-${srvId}`);
  if (!btn) return;
  btn.disabled  = spinning;
  btn.innerHTML = spinning
    ? '<span class="spinner" style="width:10px;height:10px;display:inline-block;"></span>'
    : '<i class="fas fa-arrows-rotate text-xs"></i>';
}

/**
 * Проверяет подключения одного конкретного сервера (клик на кнопку группы).
 * Посылает check-all на бэкенд и применяет результаты только к этой группе.
 */
async function checkServerGroup(srvId, connIds) {
  _setGroupBtnSpinning(srvId, true);
  // Используем общий /check-all — он проверяет всё, но мы применяем только нужные ids
  const res = await api.post('/connections/check-all', {});
  _setGroupBtnSpinning(srvId, false);
  if (!res.ok) {
    toast(`Ошибка проверки: ${res.error}`, 'error');
    return;
  }
  const results = res.data.results || {};
  let active = 0, total = connIds.length;
  connIds.forEach(id => {
    const r = results[id] || results[String(id)];
    if (r) {
      _applyConnStatusInRow(id, r.status);
      if (r.alive) active++;
    }
  });
  toast(`Проверено: ${active}/${total} активно`, active === total ? 'success' : 'info', 3000);
}

/**
 * Кнопка «Проверить все» в шапке вкладки.
 */
async function checkAllConnections() {
  const btn = document.getElementById('check-all-conns-btn');
  if (btn) {
    btn.disabled  = true;
    btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;display:inline-block;"></span><span class="hidden sm:inline ml-2">Проверяю...</span>';
  }

  const res = await api.post('/connections/check-all', {});

  if (btn) {
    btn.disabled  = false;
    btn.innerHTML = '<i class="fas fa-rotate text-xs"></i><span class="hidden sm:inline ml-2">Проверить все</span>';
  }

  if (!res.ok) {
    toast(`Ошибка: ${res.error}`, 'error');
    return;
  }

  const { results, active, total } = res.data;
  Object.entries(results).forEach(([id, r]) => {
    _applyConnStatusInRow(Number(id), r.status);
  });
  toast(
    `Проверено: ${active}/${total} активно`,
    active === total ? 'success' : active > 0 ? 'info' : 'warning',
    4000
  );
}

/**
 * Фоновая проверка — запускается автоматически после загрузки списка.
 * Тихо обновляет статусы без уведомлений пользователю.
 */
async function _checkAllConnectionsBackground() {
  const res = await api.post('/connections/check-all', {});
  if (!res.ok) return;
  const results = res.data.results || {};
  Object.entries(results).forEach(([id, r]) => {
    _applyConnStatusInRow(Number(id), r.status);
  });
}

async function toggleWarp(connId, enabled) {
  const res = await api.patch(`/connections/${connId}/param`, { field: 'warp_enabled', value: enabled });
  if (res.ok) {
    toast(enabled ? '✅ WARP fallback включён' : 'WARP fallback выключен', 'success', 2500);
  } else {
    toast(`Ошибка: ${res.error || res.data?.message}`, 'error');
    // revert checkbox
    const cb = document.getElementById(`warp-toggle-${connId}`);
    if (cb) cb.checked = !enabled;
  }
}


// ═══════════════════════════════════════════════════════════════════════════
// DELETE
// ═══════════════════════════════════════════════════════════════════════════

async function confirmDeleteConnection(connId) {
  const pm = PROTO_META;
  if (!confirm(`Удалить подключение #${connId}?\n\nКонфигурация будет удалена с сервера.`)) return;

  const res = await api.delete(`/connections/${connId}`);
  if (res.ok || res.status === 204) {
    toast('Подключение удалено', 'success');
    closeModal('modal-conn-detail');
    loadConnectionsGrouped();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}


// ═══════════════════════════════════════════════════════════════════════════
// API HELPERS (если нет глобального api объекта)
// ═══════════════════════════════════════════════════════════════════════════

// Patch api object if needed
if (window.api && !window.api.patch) {
  window.api.patch = async (path, body) => {
    try {
      const r = await fetch(`/api/v1${path}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = r.ok ? await r.json() : null;
      return { ok: r.ok, data, status: r.status, error: data?.detail || r.statusText };
    } catch(e) { return { ok: false, error: e.message }; }
  };
}
if (window.api && !window.api.delete) {
  window.api.delete = async (path) => {
    try {
      const r = await fetch(`/api/v1${path}`, { method: 'DELETE' });
      return { ok: r.ok, status: r.status, error: r.statusText };
    } catch(e) { return { ok: false, error: e.message }; }
  };
}


// ─── Delegated clipboard handler for data-copy-id buttons ────────────────────
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-copy-id]');
  if (!btn) return;
  const targetId = btn.getAttribute('data-copy-id');
  const el = document.getElementById(targetId);
  if (!el) return;
  const text = el.innerText || el.textContent || '';
  navigator.clipboard.writeText(text.trim()).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-check mr-1 text-green-400"></i>Скопировано';
    setTimeout(() => { btn.innerHTML = orig; }, 2000);
    if (window.toast) toast('Скопировано в буфер', 'success', 2000);
  }).catch(() => {
    if (window.toast) toast('Не удалось скопировать', 'error', 2000);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// EXPOSE
// ═══════════════════════════════════════════════════════════════════════════

window.loadConnectionsGrouped   = loadConnectionsGrouped;
window.showAddConnectionModal   = showAddConnectionModal;
window.wizToggleType            = wizToggleType;
window.wizGoStep2               = wizGoStep2;
window.wizSubmit                = wizSubmit;
window.closeDeployLog           = closeDeployLog;
window.showConnDetail           = showConnDetail;
window.switchDetailTab          = switchDetailTab;
window.applyParam               = applyParam;
window.checkConnLive            = checkConnLive;
window.toggleWarp               = toggleWarp;
window.confirmDeleteConnection  = confirmDeleteConnection;
window._renderWizardStep1       = _renderWizardStep1;
window.downloadConfig           = downloadConfig;
window.checkAllConnections      = checkAllConnections;
window.checkServerGroup         = checkServerGroup;

// ═══════════════════════════════════════════════════════════════════════════


// CONNECTION AUTO-SETUP MODAL — protocol-step UI (server-setup style)
// ═══════════════════════════════════════════════════════════════════════════
//
// Layout: 5 steps in top timeline, each step = one protocol or phase:
//   1 = VLESS+Reality  (all vless_reality connections)
//   2 = AmneziaWG      (all amnezia_wg connections)
//   3 = NaiveProxy     (all naive_proxy connections)
//   4 = Cascade        (cascade-specific: step 5+ of naiveproxy, vless cascade)
//   5 = Finish         (WARP / split-tunnel / misc info lines)
//
// Each step accordion shows aggregated logs from matching connections.
// ═══════════════════════════════════════════════════════════════════════════

let _connSetupIds  = [];
let _connSetupPoll = null;
let _connSetupData = {};  // connId -> last known data snapshot

// ── Mappings ──────────────────────────────────────────────────────────────

// Which modal step index (1-5) owns a given protocol
const _CSD_PROTO_STEP = {
  vless_reality: 1,
  amnezia_wg:    2,
  naive_proxy:   3,
};

// Labels for header status dots
const _CSD_STEP_LABEL = { 1:'VLESS+Reality', 2:'AmneziaWG', 3:'NaiveProxy', 4:'Cascade', 5:'Финал' };

// ── Global status dot + progress bar helpers ─────────────────────────────

function _cdSetDot(state) {
  const d = document.getElementById('conn-setup-status-dot');
  if (!d) return;
  const cfg = {
    running: { bg:'#7c3aed', sh:'rgba(124,58,237,0.25)' },
    ok:      { bg:'#16a34a', sh:'rgba(22,163,74,0.25)' },
    error:   { bg:'#dc2626', sh:'rgba(220,38,38,0.25)' },
  };
  const c = cfg[state] || cfg.running;
  d.style.background = c.bg;
  d.style.boxShadow  = `0 0 0 3px ${c.sh}`;
}

function _cdSetProgress(pct) {
  const el = document.getElementById('conn-setup-progress-fill');
  if (el) el.style.width = pct + '%';
}

function _cdShowBtn(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? 'flex' : 'none';
}

// ── Per-step timeline dot helpers (reuse stp-dot CSS from server-setup) ──

function _csdSetDot(n, state) {
  const dot = document.getElementById(`csd-dot-${n}`);
  if (!dot) return;
  dot.className = `stp-dot stp-${state}`;
  const iconMap = {
    pending: 'fa-minus',
    running: 'fa-circle-notch stp-spin',
    ok:      'fa-check',
    error:   'fa-xmark',
    warn:    'fa-triangle-exclamation',
    skip:    'fa-forward',
  };
  dot.innerHTML = `<i class="fas ${iconMap[state] || 'fa-minus'}"></i>`;
}

function _csdSetConn(n, done) {
  const el = document.getElementById(`csd-conn-${n}`);
  if (el) el.className = 'stp-connector' + (done ? ' done' : '');
}

// ── Step accordion toggle ─────────────────────────────────────────────────

function _csdToggleLog(n) {
  const log  = document.getElementById(`csd-log-${n}`);
  const chev = document.getElementById(`csd-chev-${n}`);
  if (!log) return;
  const isHidden = log.classList.toggle('hidden');
  if (chev) chev.style.transform = isHidden ? '' : 'rotate(90deg)';
}

// ── Icon text for step header ─────────────────────────────────────────────

function _csdStepIcon(state) {
  const m = { running:'⏳', ok:'✅', error:'❌', warn:'⚠️', skip:'⏭', pending:'·' };
  return m[state] || '·';
}

// ── Log line classifier (reuse stp-log-line classes) ─────────────────────

function _csdLineClass(line) {
  if (/❌|✖|\berror\b|\bfail\b/i.test(line)) return 'err';
  if (/⚠|\bwarn/i.test(line))                   return 'warn';
  if (/✅|\bok\b|success|done|installed|активен|запущен|задеплоен|сгенерир|готов|открыт/i.test(line)) return 'ok';
  if (/⏳|ожидани|попытк|проверка/i.test(line))   return 'wait';
  if (/^  /.test(line))                           return 'sub';
  return '';
}

function _csdEsc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Append lines to a step log block (incremental) ───────────────────────

function _csdAppendLog(n, headerLabel, lines, autoOpen) {
  const el = document.getElementById(`csd-log-${n}`);
  if (!el || !lines.length) return;

  // Add separator header for this connection if not yet present
  const headerId = `csd-log-${n}-hdr-${CSS.escape(headerLabel)}`;
  if (!el.querySelector(`[data-hdr="${CSS.escape(headerLabel)}"]`)) {
    const hdr = document.createElement('div');
    hdr.className = 'stp-log-line sub';
    hdr.style.cssText = 'margin-top:4px;padding-bottom:2px;border-bottom:1px solid #1f2937;';
    hdr.setAttribute('data-hdr', headerLabel);
    hdr.textContent = '── ' + headerLabel + ' ──';
    el.appendChild(hdr);
  }

  // Append each line (update if already present by key)
  lines.forEach((l, idx) => {
    const key = `${headerLabel}::${idx}`;
    let row = el.querySelector(`[data-key="${CSS.escape(key)}"]`);
    const cls  = _csdLineClass(l);
    const text = _csdEsc(l).replace(/❌/g, '✖');
    if (row) {
      row.className = `stp-log-line ${cls}`;
      row.innerHTML = text;
    } else {
      row = document.createElement('div');
      row.className = `stp-log-line ${cls}`;
      row.setAttribute('data-key', key);
      row.innerHTML = text;
      el.appendChild(row);
    }
  });

  if (autoOpen) el.classList.remove('hidden');

  // Show step wrapper
  const wrap = document.getElementById(`csd-step-${n}-wrap`);
  if (wrap) wrap.classList.remove('hidden');
}

// ── Determine dot state from connection status + its steps ────────────────

function _csdConnDotState(c) {
  if (c.setup_status === 'done')   return 'ok';
  if (c.setup_status === 'failed') return 'error';
  // in-progress: check last step status
  const steps = (c.steps || []).filter(s => s.is_step && s.n >= 1);
  if (!steps.length) return 'running';
  const last = steps[steps.length - 1];
  if (last.status === 'error') return 'error';
  if (last.status === 'ok')    return 'running'; // still more steps ahead
  return 'running';
}

// ── Worst-state aggregator for multiple connections ───────────────────────

function _csdWorstState(states) {
  if (!states.length) return 'pending';
  const priority = ['error', 'warn', 'running', 'ok', 'skip', 'pending'];
  for (const p of priority) {
    if (states.includes(p)) return p;
  }
  return 'pending';
}

// ── Main render: called on every poll tick ────────────────────────────────

function _csdRenderAll(connections) {
  // Group connections by modal step
  const stepConns = { 1:[], 2:[], 3:[], 4:[], 5:[] };

  for (const c of connections) {
    const proto = c.protocol || 'vless_reality';
    const protoStep = _CSD_PROTO_STEP[proto] || 1;
    stepConns[protoStep].push(c);

    // Cascade: any connection with connection_type=cascade also feeds step 4
    if (c.connection_type === 'cascade') {
      stepConns[4].push(c);
    }

    // Finish (step 5): plain info lines from all connections
    stepConns[5].push(c);
  }

  // Process each modal step
  for (let n = 1; n <= 5; n++) {
    const conns = stepConns[n];
    if (!conns.length) continue;

    const dotStates = [];

    for (const c of conns) {
      const proto = c.protocol || 'vless_reality';
      const protoStep = _CSD_PROTO_STEP[proto] || 1;
      const typeLabel = c.connection_type === 'cascade' ? 'CASCADE' : 'DIRECT';
      const protoName = _CSD_STEP_LABEL[protoStep] || proto;
      const headerLabel = `${protoName} · ${typeLabel}`;

      const steps     = c.steps || [];
      const stepItems = steps.filter(s => s.is_step && s.n >= 1);
      const infoItems = steps.filter(s => !s.is_step);

      // For step n == protoStep: show all [STEP:N:...] lines from this connection
      if (n === protoStep) {
        const lines = stepItems.map(s => `[${s.n}] ${s.msg}`);
        _csdAppendLog(n, headerLabel, lines, c.setup_status !== 'done' || stepItems.some(s => s.status === 'error'));
        dotStates.push(_csdConnDotState(c));
      }

      // For cascade step 4: show only cascade-relevant log lines (DIRECT ones excluded)
      if (n === 4 && c.connection_type === 'cascade') {
        // Show last few steps (typically step 5+ in naiveproxy = cascade RU Xray routing)
        const cascadeLines = stepItems
          .filter(s => s.n >= 5)
          .map(s => `[${s.n}] ${s.msg}`);
        const cascadeInfo = infoItems
          .filter(l => /cascade|RU|xray|outbound|warp/i.test(l.msg))
          .map(l => l.msg);
        const allCascade = [...cascadeLines, ...cascadeInfo];
        if (allCascade.length) {
          _csdAppendLog(4, headerLabel, allCascade, c.setup_status === 'failed');
        }
        if (c.setup_status === 'done')        dotStates.push('ok');
        else if (c.setup_status === 'failed') dotStates.push('error');
        else                                   dotStates.push('running');
      }

      // For finish step 5: show WARP / split-tunnel info lines from all connections
      if (n === 5) {
        const finishLines = infoItems
          .filter(l => /warp|split.tunnel|split_tunnel|sni|fallback|финал|finish|mtu|mss/i.test(l.msg))
          .map(l => l.msg);
        if (finishLines.length) {
          _csdAppendLog(5, headerLabel, finishLines, false);
        }
        if (c.setup_status === 'done') dotStates.push('ok');
        else dotStates.push(c.setup_status === 'failed' ? 'error' : 'running');
      }
    }

    // Set dot for this step
    if (dotStates.length) {
      const worst = _csdWorstState(dotStates);

      // Determine if ALL connections in this step are terminal (done or failed)
      const allTerminal = conns.every(c =>
        c.setup_status === 'done' || c.setup_status === 'failed'
      );

      let dotState = worst;
      if (allTerminal) {
        dotState = conns.some(c => c.setup_status === 'failed') ? 'error' : 'ok';
      }

      _csdSetDot(n, dotState);

      // Update step icon in accordion header
      const iconEl = document.getElementById(`csd-icon-${n}`);
      if (iconEl) iconEl.textContent = _csdStepIcon(dotState);

      // Connector to next step: light up if this step is terminal and not error
      if (n < 5 && allTerminal && dotState !== 'error') {
        _csdSetConn(n, true);
      }

      // Auto-open log on error
      if (dotState === 'error') {
        const log = document.getElementById(`csd-log-${n}`);
        if (log) {
          log.classList.remove('hidden');
          const chev = document.getElementById(`csd-chev-${n}`);
          if (chev) chev.style.transform = 'rotate(90deg)';
        }
      }
    }
  }

  // Subtitle: which step is currently active
  const subtEl = document.getElementById('conn-setup-subtitle');
  if (subtEl) {
    const running = connections.filter(c => c.setup_status !== 'done' && c.setup_status !== 'failed');
    if (running.length) {
      const activeProtos = [...new Set(running.map(c => {
        const s = _CSD_PROTO_STEP[c.protocol] || 1;
        return _CSD_STEP_LABEL[s];
      }))];
      subtEl.textContent = `Выполняется: ${activeProtos.join(', ')}...`;
    }
  }

  // Update overall progress
  const done   = connections.filter(c => c.setup_status === 'done').length;
  const failed = connections.filter(c => c.setup_status === 'failed').length;
  const total  = connections.length;
  const pct    = total ? Math.round((done + failed) / total * 100) : 0;
  _cdSetProgress(pct);
}

// ── Open modal ────────────────────────────────────────────────────────────

function openConnSetupModal(connIds, euServerName, connectionTypes) {
  _connSetupIds  = connIds;
  _connSetupData = {};

  const modal = document.getElementById('modal-conn-setup');
  if (!modal) { console.error('[ConnSetup] modal not found!'); return; }

  // Header
  const titleEl = document.getElementById('conn-setup-title');
  const subtEl  = document.getElementById('conn-setup-subtitle');
  const srvEl   = document.getElementById('conn-setup-server-name');
  if (titleEl) titleEl.textContent = 'Настройка подключений';
  if (subtEl)  subtEl.textContent  = 'Шаги выполняются последовательно';
  if (srvEl)   srvEl.textContent   = euServerName || '';

  // Reset step dots
  for (let i = 1; i <= 5; i++) {
    _csdSetDot(i, 'pending');
    _csdSetConn(i, false);
    const log  = document.getElementById(`csd-log-${i}`);
    const wrap = document.getElementById(`csd-step-${i}-wrap`);
    const icon = document.getElementById(`csd-icon-${i}`);
    const chev = document.getElementById(`csd-chev-${i}`);
    if (log)  { log.innerHTML = ''; log.classList.add('hidden'); }
    if (wrap) wrap.classList.add('hidden');
    if (icon) icon.textContent = '·';
    if (chev) chev.style.transform = '';
  }

  // Show steps that are relevant for the connections being deployed
  const hasProto = { vless_reality:false, amnezia_wg:false, naive_proxy:false };
  let hasCascade = false;
  (connectionTypes || []).forEach(ct => {
    if (ct.protocol in hasProto) hasProto[ct.protocol] = true;
    if (ct.connection_type === 'cascade') hasCascade = true;
  });

  // Pre-show step wrappers for present protocols
  const protoToStep = { vless_reality:1, amnezia_wg:2, naive_proxy:3 };
  Object.entries(hasProto).forEach(([p, present]) => {
    if (present) {
      const wrap = document.getElementById(`csd-step-${protoToStep[p]}-wrap`);
      if (wrap) wrap.classList.remove('hidden');
      _csdSetDot(protoToStep[p], 'running');
    }
  });
  if (hasCascade) {
    const w4 = document.getElementById('csd-step-4-wrap');
    if (w4) w4.classList.remove('hidden');
    _csdSetDot(4, 'pending');
  }

  _cdSetDot('running');
  _cdSetProgress(0);

  const errBlock = document.getElementById('conn-setup-error-block');
  if (errBlock) errBlock.classList.add('hidden');
  _cdShowBtn('conn-setup-btn-retry',  false);
  _cdShowBtn('conn-setup-btn-done',   false);
  _cdShowBtn('conn-setup-btn-cancel', true);

  modal.classList.remove('hidden');
  console.log('[ConnSetup] Modal opened for ids:', connIds);
}

// ── Polling ───────────────────────────────────────────────────────────────

function _startConnSetupPolling(connIds) {
  if (_connSetupPoll) clearInterval(_connSetupPoll);
  _connSetupPoll = setInterval(async () => {
    if (!connIds || !connIds.length) return;
    const res = await api.get(`/connections/batch-status?ids=${connIds.join(',')}`);
    if (!res.ok) return;

    const { connections, all_done, any_failed } = res.data;

    _csdRenderAll(connections);

    if (all_done) {
      clearInterval(_connSetupPoll);
      _connSetupPoll = null;
      _cdSetDot(any_failed ? 'error' : 'ok');
      _cdSetProgress(100);

      const done   = connections.filter(c => c.setup_status === 'done').length;
      const failed = connections.filter(c => c.setup_status === 'failed').length;

      const titleEl = document.getElementById('conn-setup-title');
      const subtEl  = document.getElementById('conn-setup-subtitle');
      if (titleEl) titleEl.textContent = any_failed
        ? 'Деплой завершён с ошибками'
        : 'Все подключения настроены';
      if (subtEl) subtEl.textContent = any_failed
        ? `Успешно: ${done}, ошибок: ${failed}`
        : `${done} подключений задеплоено ✅`;

      // Mark all pending dots as skip (not used in this batch)
      for (let i = 1; i <= 5; i++) {
        const dot = document.getElementById(`csd-dot-${i}`);
        if (dot && dot.className.includes('pending')) _csdSetDot(i, 'skip');
      }

      _cdShowBtn('conn-setup-btn-cancel', false);
      _cdShowBtn('conn-setup-btn-retry',  false);
      _cdShowBtn('conn-setup-btn-done',   true);

      if (any_failed) {
        const errEl     = document.getElementById('conn-setup-error-block');
        const errTextEl = document.getElementById('conn-setup-error-text');
        if (errEl)     errEl.classList.remove('hidden');
        if (errTextEl) errTextEl.textContent =
          'Один или несколько деплоев завершились с ошибкой. Разверните шаг для деталей.';
        _cdShowBtn('conn-setup-btn-retry', true);
      }

      loadConnectionsGrouped();
    }
  }, 2000);
}

// ── Close ─────────────────────────────────────────────────────────────────

function closeConnSetup() {
  if (_connSetupPoll) { clearInterval(_connSetupPoll); _connSetupPoll = null; }
  _connSetupIds  = [];
  _connSetupData = {};
  const m = document.getElementById('modal-conn-setup');
  if (m) m.classList.add('hidden');
  loadConnectionsGrouped();
}

// ── Retry ──────────────────────────────────────────────────────────────────

async function retryConnSetup() {
  if (!_connSetupIds.length) return;
  const errBlock = document.getElementById('conn-setup-error-block');
  if (errBlock) errBlock.classList.add('hidden');
  _cdSetDot('running');
  _cdSetProgress(0);
  for (let i = 1; i <= 5; i++) _csdSetDot(i, 'pending');
  _cdShowBtn('conn-setup-btn-retry',  false);
  _cdShowBtn('conn-setup-btn-done',   false);
  _cdShowBtn('conn-setup-btn-cancel', true);
  const titleEl = document.getElementById('conn-setup-title');
  const subtEl  = document.getElementById('conn-setup-subtitle');
  if (titleEl) titleEl.textContent = 'Настройка подключений';
  if (subtEl)  subtEl.textContent  = 'Повторный опрос...';
  _startConnSetupPolling(_connSetupIds);
}

window.openConnSetupModal  = openConnSetupModal;
window.closeConnSetup      = closeConnSetup;
window.retryConnSetup      = retryConnSetup;
window._csdToggleLog       = _csdToggleLog;

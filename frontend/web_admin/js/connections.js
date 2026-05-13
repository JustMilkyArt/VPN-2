/**
 * Connections tab — v3
 * UX: 2-step wizard (type → servers) → deploy logs modal
 * UI: grouped by EU server → direct / cascade rows
 *     Connection detail: 3 tabs (Configs / Params / Info)
 */

// ─── LOAD & RENDER LIST ──────────────────────────────────────────────────────

// Load SNI list from API and cache it globally
async function _loadSniList() {
  if (window._sniListCache && window._sniListCache.length > 0) return; // already loaded
  try {
    const res = await api.get('/connections/sni-list');
    if (res.ok && Array.isArray(res.data)) {
      window._sniListCache = res.data;
    }
  } catch(e) {
    console.warn('SNI list load failed:', e);
  }
}

async function loadConnectionsGrouped() {
  const listEl  = document.getElementById('connections-list');
  const emptyEl = document.getElementById('connections-empty');
  listEl.innerHTML = `<div class="flex justify-center py-10"><span class="spinner"></span></div>`;

  await _loadSniList(); // ensure SNI list is cached before rendering
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
  step:              1,
  createDirect:      false,
  createCascade:     false,
  canDirect:         false,
  canCascade:        false,
  euServers:         [],
  ruServers:         [],
  selectedProtocols: ['vless_reality', 'amnezia_wg', 'naive_proxy'], // все по умолчанию
};

/**
 * Синхронизирует визуальный степ-индикатор в заголовке wizard-модала
 * с текущим _wizardState.step (1, 2 или 3).
 */
function _syncWizSteps() {
  const cur = _wizardState.step;
  [1, 2, 3].forEach(n => {
    const dot   = document.getElementById(`wiz-step-dot-${n}`);
    const label = document.getElementById(`wiz-step-label-${n}`);
    const line  = document.getElementById(`wiz-step-line-${n}`);
    if (!dot) return;
    if (n < cur) {
      // завершённый шаг — зелёная галочка
      dot.className   = 'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all bg-green-600 text-white';
      dot.innerHTML   = '<i class="fas fa-check text-[10px]"></i>';
      if (label) label.className = 'text-xs font-medium text-green-400';
      if (line)  line.style.background = '#16a34a';
    } else if (n === cur) {
      // текущий шаг — brand
      dot.className   = 'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all bg-brand-600 text-white';
      dot.innerHTML   = String(n);
      if (label) label.className = 'text-xs font-medium text-white';
      if (line)  line.style.background = '';
    } else {
      // будущий шаг — серый
      dot.className   = 'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all bg-gray-700 text-gray-500';
      dot.innerHTML   = String(n);
      if (label) label.className = 'text-xs font-medium text-gray-500';
      if (line)  line.style.background = '';
    }
  });
}

async function showAddConnectionModal() {
  _wizardState = { step: 1, createDirect: false, createCascade: false,
                   canDirect: false, canCascade: false, euServers: [], ruServers: [],
                   selectedProtocols: ['vless_reality', 'amnezia_wg', 'naive_proxy'] };

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
  _syncWizSteps();
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
    Далее вы выберете протоколы для создания: VLESS+Reality, AmneziaWG, NaiveProxy
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

// ── STEP 2: protocol selection ───────────────────────────────────────────────

function wizGoStep2() {
  if (!_wizardState.createDirect && !_wizardState.createCascade) return;
  _wizardState.step = 2;
  _syncWizSteps();

  const PROTO_OPTIONS = [
    {
      id:    'vless_reality',
      icon:  'fa-shield-halved',
      label: 'VLESS+Reality',
      desc:  'XTLS Vision, obfuscation через TLS',
      color: 'violet',
    },
    {
      id:    'amnezia_wg',
      icon:  'fa-lock',
      label: 'AmneziaWG',
      desc:  'WireGuard с junk-пакетами',
      color: 'blue',
    },
    {
      id:    'naive_proxy',
      icon:  'fa-globe',
      label: 'NaiveProxy',
      desc:  'HTTPS forward proxy (Caddy)',
      color: 'emerald',
    },
  ];

  const colorMap = {
    violet:  { border: 'border-violet-500', bg: 'bg-violet-900/20', icon: 'text-violet-400', check: 'bg-violet-600' },
    blue:    { border: 'border-blue-500',   bg: 'bg-blue-900/20',   icon: 'text-blue-400',   check: 'bg-blue-600'   },
    emerald: { border: 'border-emerald-500',bg: 'bg-emerald-900/20',icon: 'text-emerald-400',check: 'bg-emerald-600'},
  };

  const body   = document.getElementById('wizard-body');
  const footer = document.getElementById('wizard-footer');

  const cards = PROTO_OPTIONS.map(p => {
    const sel = _wizardState.selectedProtocols.includes(p.id);
    const c   = colorMap[p.color];
    const selBorder = sel ? c.border : 'border-gray-700';
    const selBg     = sel ? c.bg     : 'bg-gray-800/50';
    return `
<button id="wiz-proto-btn-${p.id}"
  onclick="wizToggleProtocol('${p.id}')"
  class="wiz-proto-btn relative flex items-center gap-3 w-full px-4 py-3.5 rounded-xl border-2 transition text-left cursor-pointer
         ${selBorder} ${selBg} hover:border-gray-500">
  <i class="fas ${p.icon} text-xl flex-shrink-0 ${sel ? c.icon : 'text-gray-500'}" id="wiz-proto-icon-${p.id}"></i>
  <div class="flex-1 min-w-0">
    <div class="font-semibold text-sm text-white">${p.label}</div>
    <div class="text-[11px] text-gray-500 mt-0.5">${p.desc}</div>
  </div>
  <span id="wiz-proto-check-${p.id}"
    class="w-5 h-5 rounded-full flex items-center justify-center text-xs flex-shrink-0 transition
           ${sel ? c.check + ' text-white' : 'bg-gray-700 text-gray-500'}">
    <i class="fas ${sel ? 'fa-check' : 'fa-minus'}"></i>
  </span>
</button>`;
  }).join('');

  body.innerHTML = `
<div class="space-y-3">
  <p class="text-sm text-gray-400">Выберите протоколы для создания (можно несколько):</p>
  <div class="space-y-2">
    ${cards}
  </div>
  <div class="flex gap-2 pt-1">
    <button onclick="wizSelectAllProtocols()"
      class="flex-1 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg transition text-gray-400">
      Выбрать все
    </button>
    <button onclick="wizClearAllProtocols()"
      class="flex-1 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg transition text-gray-400">
      Снять все
    </button>
  </div>
</div>`;

  footer.innerHTML = `
<div class="flex justify-between items-center">
  <button onclick="_renderWizardStep1()"
    class="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm font-medium transition flex items-center gap-2">
    <i class="fas fa-arrow-left text-xs"></i> Назад
  </button>
  <button id="wiz-proto-next-btn" onclick="wizGoStep3()"
    class="px-5 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg text-sm font-semibold text-white transition flex items-center gap-2">
    Далее <i class="fas fa-arrow-right text-xs"></i>
  </button>
</div>`;

  _updateProtoNextBtn();
}

function wizToggleProtocol(protoId) {
  const idx = _wizardState.selectedProtocols.indexOf(protoId);
  if (idx === -1) {
    _wizardState.selectedProtocols.push(protoId);
  } else {
    _wizardState.selectedProtocols.splice(idx, 1);
  }
  _refreshProtoCard(protoId);
  _updateProtoNextBtn();
}

function wizSelectAllProtocols() {
  _wizardState.selectedProtocols = ['vless_reality', 'amnezia_wg', 'naive_proxy'];
  ['vless_reality', 'amnezia_wg', 'naive_proxy'].forEach(_refreshProtoCard);
  _updateProtoNextBtn();
}

function wizClearAllProtocols() {
  _wizardState.selectedProtocols = [];
  ['vless_reality', 'amnezia_wg', 'naive_proxy'].forEach(_refreshProtoCard);
  _updateProtoNextBtn();
}

function _refreshProtoCard(protoId) {
  const colorDefs = {
    vless_reality: { border: 'border-violet-500', bg: 'bg-violet-900/20', icon: 'text-violet-400', check: 'bg-violet-600' },
    amnezia_wg:    { border: 'border-blue-500',   bg: 'bg-blue-900/20',   icon: 'text-blue-400',   check: 'bg-blue-600'   },
    naive_proxy:   { border: 'border-emerald-500', bg: 'bg-emerald-900/20',icon: 'text-emerald-400',check: 'bg-emerald-600'},
  };
  const btn   = document.getElementById(`wiz-proto-btn-${protoId}`);
  const iEl   = document.getElementById(`wiz-proto-icon-${protoId}`);
  const chk   = document.getElementById(`wiz-proto-check-${protoId}`);
  if (!btn) return;
  const sel = _wizardState.selectedProtocols.includes(protoId);
  const c   = colorDefs[protoId];

  // border
  btn.classList.toggle(c.border,      sel);
  btn.classList.toggle(c.bg,          sel);
  btn.classList.toggle('border-gray-700', !sel);
  btn.classList.toggle('bg-gray-800/50',  !sel);
  // icon color
  if (iEl) { iEl.className = iEl.className.replace(/text-\w+-\d+|text-gray-\d+/g, '').trim() + ' ' + (sel ? c.icon : 'text-gray-500'); }
  // check badge
  if (chk) {
    chk.className = chk.className.replace(/bg-\w+-\d+|text-\w+-\d+/g, '').trim()
      + ' ' + (sel ? c.check + ' text-white' : 'bg-gray-700 text-gray-500');
    chk.innerHTML = `<i class="fas ${sel ? 'fa-check' : 'fa-minus'}"></i>`;
  }
}

function _updateProtoNextBtn() {
  const btn = document.getElementById('wiz-proto-next-btn');
  if (btn) btn.disabled = _wizardState.selectedProtocols.length === 0;
}

// ── STEP 3: server selection ──────────────────────────────────────────────────

function wizGoStep3() {
  if (_wizardState.selectedProtocols.length === 0) { toast('Выберите хотя бы один протокол', 'error'); return; }
  _wizardState.step = 3;
  _syncWizSteps();

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
  <button onclick="wizGoStep2()"
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

  // ── Show loading state in wizard footer BEFORE sending request ──
  const footer = document.getElementById('wizard-footer');
  if (footer) {
    footer.innerHTML = '<div class="flex items-center justify-center gap-3 py-1">'
      + '<span class="inline-block w-4 h-4 rounded-full border-2 border-brand-400 border-t-transparent animate-spin"></span>'
      + '<span class="text-sm text-gray-400">Создание подключений…</span>'
      + '</div>';
  }

  const res = await api.post('/connections/batch', {
    eu_server_id:   euServerId,
    ru_server_id:   ruServerId || null,
    create_direct:  _wizardState.createDirect,
    create_cascade: _wizardState.createCascade,
    protocols:      _wizardState.selectedProtocols,
  });

  // ── Close wizard only after response ──
  closeModal('modal-wizard-conn');

  if (!res.ok) {
    toast('Ошибка создания: ' + (res.error || 'Неизвестная ошибка'), 'error');
    return;
  }

  const { connection_ids, connections } = res.data;

  if (!connection_ids || connection_ids.length === 0) {
    toast('Все выбранные подключения уже существуют', 'info');
    loadConnectionsGrouped();
    return;
  }

  // connTypes: используем connections из API (batch теперь возвращает их),
  // либо строим из selectedProtocols как fallback
  const connTypes = connections && connections.length
    ? connections
    : connection_ids.map(id => ({ id, protocol: '?', connection_type: '?' }));

  // EU server name — из wizardState.euServers (правильный ключ)
  const euSrv = (_wizardState.euServers || []).find(function(s) { return s.id === euServerId; });
  const euName = euSrv ? (euSrv.display_name || euSrv.name || euSrv.ip) : '';

  // Открываем modal-conn-setup (без _startDeployPolling — только один polling)
  const connSetupModal = document.getElementById('modal-conn-setup');
  if (connSetupModal) {
    openConnSetupModal(connection_ids, euName, connTypes, _wizardState.selectedProtocols);
    _startConnSetupPolling(connection_ids);
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

let _detailConnId     = null;
let _detailRefreshInt = null;

// ── Auto-refresh ──────────────────────────────────────────────────────────────

function _startDetailAutoRefresh(connId) {
  _stopDetailAutoRefresh();
  _detailRefreshInt = setInterval(function() {
    _silentRefreshStatus(connId);
  }, 30000);
}

function _stopDetailAutoRefresh() {
  if (_detailRefreshInt) {
    clearInterval(_detailRefreshInt);
    _detailRefreshInt = null;
  }
}

async function _silentRefreshStatus(connId) {
  try {
    const res = await api.get('/connections/' + connId + '/health', { timeout: 15000 });
    if (!res.ok) return;
    const d = res.data;
    // Update status tab content if visible
    const el = document.getElementById('dstatus-content');
    if (el) {
      el.innerHTML = _buildStatusContent(d, connId);
    }
    // Update header badge
    _updateDetailHeaderBadge(d);
  } catch(e) {
    console.warn('[autoRefresh] error:', e);
  }
}

function _updateDetailHeaderBadge(d) {
  const hbEl = document.getElementById('detail-health-badge');
  if (hbEl && d && d.health_status) {
    hbEl.outerHTML = _healthBadge(d.health_status);
  }
}

// ── Main show/render ──────────────────────────────────────────────────────────

async function showConnDetail(connId) {
  _detailConnId = connId;
  _stopDetailAutoRefresh();
  openModal('modal-conn-detail');

  const header  = document.getElementById('conn-detail-header');
  const content = document.getElementById('conn-detail-content');
  header.innerHTML  = '<span class="text-gray-500 text-sm">Загрузка\u2026</span>';
  content.innerHTML = '<div class="flex justify-center py-8"><span class="spinner"></span></div>';

  const res = await api.get('/connections/' + connId, { timeout: 10000 });

  if (document.getElementById('modal-conn-detail').classList.contains('hidden')) return;

  if (!res.ok) {
    if (res.status === 401) return;
    header.innerHTML  = '<span class="text-red-400 text-sm"><i class="fas fa-circle-exclamation mr-1"></i>Ошибка</span>';
    content.innerHTML = '<div class="text-red-400 text-sm p-4">'
      + '<i class="fas fa-triangle-exclamation mr-2"></i>' + (res.error || 'Неизвестная ошибка')
      + '<br><button onclick="showConnDetail(' + connId + ')" class="mt-3 text-xs text-brand-400 hover:underline">'
      + '<i class="fas fa-rotate-right mr-1"></i>Повторить</button></div>';
    return;
  }

  try {
    _renderConnDetail(res.data);
    // If deploying — poll faster (every 3s) until done
    if (res.data.setup_status === 'deploying' || res.data.setup_status === 'pending') {
      _stopDetailAutoRefresh();
      _detailRefreshInt = setInterval(async function() {
        const r2 = await api.get('/connections/' + connId, { timeout: 10000 });
        if (!r2.ok) return;
        _renderConnDetail(r2.data);
        // Stop fast polling once done
        if (r2.data.setup_status !== 'deploying' && r2.data.setup_status !== 'pending') {
          _stopDetailAutoRefresh();
          _startDetailAutoRefresh(connId);
        }
      }, 3000);
    } else {
      _startDetailAutoRefresh(connId);
    }
  } catch (err) {
    console.error('[showConnDetail] render error:', err);
    if (header)  header.innerHTML  = '<span class="text-red-400 text-sm"><i class="fas fa-circle-exclamation mr-1"></i>Ошибка рендера</span>';
    if (content) content.innerHTML = '<div class="text-red-400 text-sm p-4">'
      + '<i class="fas fa-bug mr-2"></i><b>JS ошибка:</b> ' + err.message
      + '<br><pre class="mt-2 text-xs text-gray-400 whitespace-pre-wrap">' + (err.stack || '') + '</pre>'
      + '<br><button onclick="showConnDetail(' + connId + ')" class="mt-3 text-xs text-brand-400 hover:underline">'
      + '<i class="fas fa-rotate-right mr-1"></i>Повторить</button></div>';
  }
}

// Stop refresh when modal closes
(function() {
  var _origClose = window.closeModal;
  window.closeModal = function(id) {
    if (id === 'modal-conn-detail') _stopDetailAutoRefresh();
    if (_origClose) _origClose(id);
  };
})();

function _renderConnDetail(conn) {
  const pm = PROTO_META[conn.protocol] || { icon: 'fa-network-wired', label: conn.protocol, color: 'text-gray-400 bg-gray-800 border-gray-700' };
  const sm = STATUS_META[conn.status]  || STATUS_META.inactive;

  const content = document.getElementById('conn-detail-content');

  const hs = conn.health_status || null;

  document.getElementById('conn-detail-header').innerHTML =
    '<div class="flex items-center gap-3">'
    + '<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold ' + pm.color + '">'
    + '<i class="fas ' + pm.icon + ' text-[10px]"></i>' + pm.label + '</span>'
    + '<div class="flex items-center gap-1.5">'
    + '<span class="w-2 h-2 rounded-full ' + sm.dot + '"></span>'
    + '<span class="text-sm ' + sm.text + '">' + sm.label + '</span>'
    + '</div>'
    + (hs ? _healthBadge(hs) : '')
    + '</div>';

  // 5 tabs
  var TABS = [
    { id: 'status',  icon: 'fa-heart-pulse',    label: 'Статус' },
    { id: 'config',  icon: 'fa-sliders',         label: 'Протокол' },
    { id: 'routing', icon: 'fa-route',           label: 'Роутинг' },
    { id: 'clients', icon: 'fa-download',        label: 'Клиенты' },
    { id: 'diag',    icon: 'fa-stethoscope',     label: 'Диагностика' }
  ];

  var tabBtns = TABS.map(function(t, i) {
    var active = i === 0
      ? 'border-brand-500 text-white'
      : 'border-transparent text-gray-500 hover:text-gray-300';
    return '<button onclick="switchDetailTab(\'' + t.id + '\')"'
      + ' id="dtab-btn-' + t.id + '"'
      + ' class="detail-tab-btn px-3 py-2 text-xs font-medium border-b-2 transition -mb-px ' + active + '">'
      + '<i class="fas ' + t.icon + ' mr-1.5"></i>' + t.label
      + '</button>';
  }).join('');

  // ── Deploying banner ─────────────────────────────────────────────────────
  var deployBanner = '';
  if (conn.setup_status === 'deploying' || conn.setup_status === 'pending') {
    var stepTxt = conn.setup_step ? (' — ' + conn.setup_step) : '';
    deployBanner = '<div class="flex items-center gap-3 mb-4 px-4 py-3 bg-brand-900/30 border border-brand-600/40 rounded-xl">'
      + '<span class="inline-block w-4 h-4 rounded-full border-2 border-brand-400 border-t-transparent animate-spin flex-shrink-0"></span>'
      + '<div>'
      + '<div class="text-xs font-medium text-brand-300">Деплой в процессе' + stepTxt + '</div>'
      + '<div class="text-[10px] text-gray-500 mt-0.5">Параметры появятся после завершения настройки</div>'
      + '</div>'
      + '<button onclick="showConnDetail(' + conn.id + ')" class="ml-auto text-[10px] text-brand-400 hover:underline flex-shrink-0">'
      + '<i class="fas fa-rotate-right mr-1"></i>Обновить</button>'
      + '</div>';
  } else if (conn.setup_status === 'error') {
    var errTxt = conn.setup_error ? (' ' + conn.setup_error) : '';
    deployBanner = '<div class="flex items-center gap-3 mb-4 px-4 py-3 bg-red-900/30 border border-red-600/40 rounded-xl">'
      + '<i class="fas fa-circle-xmark text-red-400 flex-shrink-0"></i>'
      + '<div>'
      + '<div class="text-xs font-medium text-red-300">Ошибка деплоя' + errTxt + '</div>'
      + '<div class="text-[10px] text-gray-500 mt-0.5">Смотрите вкладку Диагностика → Deploy Log</div>'
      + '</div>'
      + '<button onclick="showConnDetail(' + conn.id + ')" class="ml-auto text-[10px] text-red-400 hover:underline flex-shrink-0">'
      + '<i class="fas fa-rotate-right mr-1"></i>Обновить</button>'
      + '</div>';
  }

  content.innerHTML =
    deployBanner
    + '<div class="flex gap-0.5 mb-4 border-b border-gray-800 pb-0 flex-wrap">'
    + tabBtns
    + '</div>'
    + '<div id="dtab-status"  class="detail-tab-pane space-y-3">'  + _renderStatusTab(conn)  + '</div>'
    + '<div id="dtab-config"  class="detail-tab-pane hidden space-y-3">' + _renderConfigTab(conn)  + '</div>'
    + '<div id="dtab-routing" class="detail-tab-pane hidden space-y-3">' + _renderRoutingTab(conn) + '</div>'
    + '<div id="dtab-clients" class="detail-tab-pane hidden space-y-3">' + _renderClientsTab(conn) + '</div>'
    + '<div id="dtab-diag"    class="detail-tab-pane hidden space-y-3">' + _renderDiagTab(conn)    + '</div>';

  _maybeGenQR(conn);
}

function switchDetailTab(name) {
  document.querySelectorAll('.detail-tab-pane').forEach(function(el) { el.classList.add('hidden'); });
  document.querySelectorAll('.detail-tab-btn').forEach(function(el) {
    el.classList.remove('border-brand-500', 'text-white');
    el.classList.add('border-transparent', 'text-gray-500');
  });
  var pane = document.getElementById('dtab-' + name);
  if (pane) pane.classList.remove('hidden');
  var btn = document.getElementById('dtab-btn-' + name);
  if (btn) {
    btn.classList.add('border-brand-500', 'text-white');
    btn.classList.remove('border-transparent', 'text-gray-500');
  }
  // Generate QR when switching to clients tab
  if (name === 'clients') {
    var conn = window._lastDetailConn;
    if (conn) _maybeGenQR(conn);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _healthBadge(hs) {
  var cfg = {
    HEALTHY:  { cls: 'bg-green-900/40  border-green-600/60  text-green-400',  icon: 'fa-circle-check',         label: 'HEALTHY'  },
    DEGRADED: { cls: 'bg-yellow-900/40 border-yellow-600/60 text-yellow-400', icon: 'fa-triangle-exclamation', label: 'DEGRADED' },
    BROKEN:   { cls: 'bg-red-900/40    border-red-600/60    text-red-400',    icon: 'fa-circle-xmark',         label: 'BROKEN'   }
  };
  var c = cfg[hs] || { cls: 'bg-gray-800 border-gray-700 text-gray-500', icon: 'fa-circle-question', label: hs || 'UNKNOWN' };
  return '<span id="detail-health-badge" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold ' + c.cls + '">'
    + '<i class="fas ' + c.icon + ' text-[9px]"></i>' + c.label + '</span>';
}

function _kv(label, val, mono) {
  var valClass = mono ? 'text-xs text-gray-300 font-mono' : 'text-xs text-gray-300';
  return '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60 last:border-0">'
    + '<span class="text-xs text-gray-500 flex-shrink-0 mr-4">' + label + '</span>'
    + '<span class="' + valClass + ' text-right break-all">' + (val !== null && val !== undefined && val !== '' ? escapeHtml(String(val)) : '<span class="text-gray-600">\u2014</span>') + '</span>'
    + '</div>';
}

function _roRow(label, value, mono) {
  var cls = mono ? 'font-mono text-xs text-gray-300 break-all' : 'text-xs text-gray-300';
  return '<div class="flex items-start gap-3 py-2 border-b border-gray-800 last:border-0">'
    + '<span class="text-xs text-gray-500 w-32 flex-shrink-0">' + label + '</span>'
    + '<div class="flex-1 min-w-0 flex items-center gap-2">'
    + '<span class="' + cls + '">' + (value !== null && value !== undefined && value !== '' ? escapeHtml(String(value)) : '<span class="text-gray-600">\u2014</span>') + '</span>'
    + (value ? '<button onclick="navigator.clipboard.writeText(\'' + escapeHtml(String(value)).replace(/'/g, "\\'") + '\')" class="flex-shrink-0 text-gray-600 hover:text-gray-300 transition" title="Копировать"><i class="fas fa-copy text-[10px]"></i></button>' : '')
    + '</div>'
    + '</div>';
}

// ── Tab 1: Status & Health ────────────────────────────────────────────────────


// ── Observability helpers ──────────────────────────────────────────────────

function _statusRow(label, state, detail) {
  // state: true=ok, false=fail, null=unknown, 'warn'=degraded, 'n/a'=na
  var icon, cls;
  if (state === true)        { icon = 'fa-circle-check';       cls = 'text-green-400'; }
  else if (state === false)  { icon = 'fa-circle-xmark';       cls = 'text-red-400'; }
  else if (state === 'warn') { icon = 'fa-triangle-exclamation'; cls = 'text-yellow-400'; }
  else if (state === 'n/a')  { icon = 'fa-minus-circle';       cls = 'text-gray-600'; }
  else                       { icon = 'fa-circle-question';    cls = 'text-gray-500'; }

  var detailHtml = detail
    ? '<span class="text-[10px] text-gray-600 ml-1 truncate max-w-[120px]">' + escapeHtml(String(detail)) + '</span>'
    : '';

  return '<div class="flex items-center justify-between py-1.5 border-b border-gray-800/60 last:border-0">'
    + '<span class="text-xs text-gray-400">' + label + '</span>'
    + '<div class="flex items-center gap-1.5">'
    + detailHtml
    + '<i class="fas ' + icon + ' text-[11px] ' + cls + '"></i>'
    + '</div>'
    + '</div>';
}

function _metricBar(label, val, max, unit, warnThresh, critThresh) {
  if (val === null || val === undefined) {
    return '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60 last:border-0">'
      + '<span class="text-xs text-gray-400">' + label + '</span>'
      + '<span class="text-xs text-gray-600">—</span>'
      + '</div>';
  }
  var pct = Math.min(100, (val / max) * 100);
  var barCls = val >= critThresh ? 'bg-red-500' : (val >= warnThresh ? 'bg-yellow-500' : 'bg-green-500');
  var valCls = val >= critThresh ? 'text-red-400' : (val >= warnThresh ? 'text-yellow-400' : 'text-green-400');
  return '<div class="py-1.5 border-b border-gray-800/60 last:border-0">'
    + '<div class="flex justify-between items-center mb-1">'
    + '<span class="text-xs text-gray-400">' + label + '</span>'
    + '<span class="text-xs font-mono ' + valCls + '">' + val.toFixed(1) + ' ' + unit + '</span>'
    + '</div>'
    + '<div class="w-full bg-gray-800 rounded-full h-1">'
    + '<div class="' + barCls + ' h-1 rounded-full transition-all" style="width:' + pct + '%"></div>'
    + '</div>'
    + '</div>';
}

function _sectionCard(title, icon, content) {
  return '<div class="bg-gray-800/50 border border-gray-700/80 rounded-xl overflow-hidden">'
    + '<div class="flex items-center gap-2 px-3 py-2 border-b border-gray-700/60 bg-gray-800/30">'
    + '<i class="fas ' + icon + ' text-[10px] text-gray-500"></i>'
    + '<span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">' + title + '</span>'
    + '</div>'
    + '<div class="px-3 py-1">' + content + '</div>'
    + '</div>';
}

function _tunnelStatusBadge(tunnelOk, routingOk, trafficOk) {
  if (tunnelOk === true && routingOk !== false && trafficOk !== false) {
    return '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold bg-green-900/40 border-green-600/60 text-green-400">'
      + '<i class="fas fa-circle-check text-[9px]"></i>CONNECTED</span>';
  } else if (tunnelOk === false) {
    return '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold bg-red-900/40 border-red-600/60 text-red-400">'
      + '<i class="fas fa-circle-xmark text-[9px]"></i>FAILED</span>';
  } else if (tunnelOk === null || tunnelOk === undefined) {
    return '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold bg-gray-800 border-gray-700 text-gray-500">'
      + '<i class="fas fa-circle-question text-[9px]"></i>NOT CHECKED</span>';
  } else {
    return '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold bg-yellow-900/40 border-yellow-600/60 text-yellow-400">'
      + '<i class="fas fa-triangle-exclamation text-[9px]"></i>DEGRADED</span>';
  }
}

function _renderStatusTab(conn) {
  window._lastDetailConn = conn;
  return '<div id="dstatus-content">' + _buildStatusContent(conn, conn.id) + '</div>';
}

function _buildStatusContent(d, connId) {
  var hs = d.health_status || null;
  var proto = d.protocol || '';

  // ── Header: Health badge + кнопка проверки ──────────────────────────────
  var headerRow = '<div class="flex items-center justify-between mb-3">'
    + '<div class="flex items-center gap-2">'
    + '<span class="text-xs text-gray-400 font-medium">Итоговый статус</span>'
    + (hs ? _healthBadge(hs) : '<span class="text-xs text-gray-600">—</span>')
    + '</div>'
    + '<button onclick="runDeepHealthCheck(' + connId + ')" id="hc-btn-' + connId + '" '
    + 'class="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-brand-600 rounded-lg text-xs text-gray-300 hover:text-white transition">'
    + '<i class="fas fa-rotate-right text-[10px]"></i>Проверить</button>'
    + '</div>';

  // ── Section 1: VPN Runtime Status ────────────────────────────────────────

  // Tunnel status
  var tunnelOk   = d.tunnel_ok;
  var routingOk  = d.routing_ok;
  var trafficOk  = d.traffic_ok;
  var dnsOk      = d.dns_ok;

  // Xray / service
  var xrayOk   = d.xray_active;
  if (xrayOk === null || xrayOk === undefined) {
    // fallback: если поле не заполнено, используем last_check_ok
    xrayOk = (d.last_check_ok === true) ? true : (d.last_check_ok === false ? false : null);
  }
  var portOk   = d.port_listening;
  var tlsOk    = d.last_tls_status === 'CONNECTED' ? true
               : (d.last_tls_status === 'REFUSED' || d.last_tls_status === 'TIMEOUT') ? false
               : (d.last_tls_status === 'UNAVAILABLE') ? 'n/a'
               : null;
  var warpOk   = d.warp_enabled ? (d.warp_active === true ? true : d.warp_active === false ? false : null) : 'n/a';
  var splitOk  = d.split_tunnel_enabled ? true : 'n/a';

  // Routing
  var outboundOk = d.last_outbound_ip ? true : null;

  // Internet
  var internetOk = d.internet_ok;
  if (internetOk === null || internetOk === undefined) {
    internetOk = outboundOk;  // fallback
  }

  // ── NOT COLLECTED state helper ──────────────────────────────────────────
  // null/undefined = not collected yet (needs e2e run)
  // true/false = real result from e2e

  var runtimeRows = '';
  runtimeRows += _statusRow('Tunnel Established',  tunnelOk,  tunnelOk === true ? 'OK' : tunnelOk === false ? 'FAILED' : null);
  runtimeRows += _statusRow('Client Connectivity', tunnelOk !== false && routingOk !== false ? (tunnelOk === true ? true : null) : false, null);
  runtimeRows += _statusRow('Traffic Forwarding',  trafficOk !== null && trafficOk !== undefined ? trafficOk : (tunnelOk === true ? null : null),
    trafficOk === true ? 'OK' : trafficOk === false ? 'FAILED' : 'not collected');
  runtimeRows += _statusRow('DNS Resolution',       dnsOk,    dnsOk === true ? 'OK' : dnsOk === false ? 'FAILED' : 'not collected');
  runtimeRows += _statusRow('Internet Access',      internetOk !== null && internetOk !== undefined ? internetOk : null,
    internetOk === true ? 'OK' : internetOk === false ? 'FAILED' : 'not collected');

  // Routing Validation с детальным SHORT-CIRCUIT описанием
  var routingDetail = d.routing_detail || null;
  var routingLabel;
  if (routingOk === false) {
    routingLabel = 'SHORT-CIRCUIT';
  } else if (routingOk === true) {
    routingLabel = routingDetail ? routingDetail.substring(0, 40) : 'OK';
  } else {
    routingLabel = 'not collected';
  }
  runtimeRows += _statusRow('Routing Validation',   routingOk, routingLabel);
  // SHORT-CIRCUIT details inline block
  if (routingOk === false && routingDetail) {
    runtimeRows += '<div class="ml-1 mb-1 px-2 py-1.5 bg-red-950/30 border border-red-800/30 rounded-lg">'
      + '<p class="text-[10px] text-red-400 leading-relaxed">'
      + '<i class="fas fa-route mr-1"></i><strong>SHORT-CIRCUIT:</strong> '
      + escapeHtml(routingDetail.substring(0, 300))
      + '</p>'
      + '<p class="text-[10px] text-gray-500 mt-0.5">Traffic is exiting directly from VPN server instead of being routed through tunnel.</p>'
      + '</div>';
  }

  var isVless = (proto === 'vless_reality');
  var isNaive = (proto === 'naive_proxy');
  if (isVless || isNaive) {
    runtimeRows += _statusRow('Reality / TLS',
      tlsOk,
      d.last_tls_status || null
    );
  }
  runtimeRows += _statusRow('Port Listening',   portOk,   portOk === true ? (d.port ? d.port + '/tcp' : 'OK') : portOk === false ? 'NOT LISTENING' : null);
  runtimeRows += _statusRow('Xray / Service',   xrayOk,   xrayOk === true ? 'active' : xrayOk === false ? 'stopped' : null);
  runtimeRows += _statusRow('WARP Fallback',    warpOk,   warpOk === true ? 'connected' : warpOk === false ? 'disconnected' : warpOk === 'n/a' ? 'disabled' : null);
  runtimeRows += _statusRow('Split Tunnel',     splitOk,  splitOk === true ? 'enabled' : 'disabled');

  var tunnelBadge = _tunnelStatusBadge(tunnelOk, routingOk, trafficOk);
  var runtimeSection = _sectionCard(
    'VPN Runtime Status',
    'fa-shield-halved',
    '<div class="flex items-center justify-between py-2 border-b border-gray-800/80 mb-0.5">'
      + '<span class="text-xs text-gray-300 font-medium">Tunnel</span>'
      + tunnelBadge
      + '</div>'
      + runtimeRows
  );

  // ── Section 2: Network Metrics ────────────────────────────────────────────
  var lat  = d.latency_ms;
  var jit  = d.jitter_ms;
  var loss = d.packet_loss_pct;
  var tLat = d.tunnel_latency_ms;

  var metricsContent = '';
  metricsContent += _metricBar('Latency (ping)',   lat,  300, 'ms', 80, 200);
  metricsContent += _metricBar('Jitter',           jit,  100, 'ms', 20, 50);
  metricsContent += _metricBar('Packet Loss',      loss, 100, '%',  5,  30);
  if (tLat !== null && tLat !== undefined) {
    metricsContent += _metricBar('Tunnel RTT (e2e)', tLat, 500, 'ms', 150, 350);
  } else {
    // Показываем "not collected" если e2e ещё не запускался
    metricsContent += '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60 last:border-0">'
      + '<span class="text-xs text-gray-400">Tunnel RTT (e2e)</span>'
      + '<span class="text-[10px] text-gray-600">not collected — run health check</span>'
      + '</div>';
  }

  var metricsSection = _sectionCard('Network Metrics', 'fa-chart-line', metricsContent);

  // ── Section 3: Exit Information ───────────────────────────────────────────
  var exitIp  = d.tunnel_ip || d.last_outbound_ip  || null;
  var exitGeo = d.tunnel_geo || d.last_outbound_geo || null;

  var exitContent = '';
  // Приоритет: tunnel_ip (e2e реальный exit) > last_outbound_ip (server-side)
  var exitIpLabel = exitIp
    ? escapeHtml(exitIp) + (d.tunnel_ip && d.last_outbound_ip && d.tunnel_ip !== d.last_outbound_ip
        ? ' <span class="text-[9px] text-gray-500">(e2e)</span>' : '')
    : '<span class="text-gray-500 text-[10px]">not collected — run health check</span>';
  var exitGeoLabel = exitGeo || '<span class="text-gray-500 text-[10px]">not collected</span>';
  var tlsLabel = d.last_tls_status
    ? ('<span class="' + (d.last_tls_status === 'CONNECTED' ? 'text-green-400' : d.last_tls_status === 'REFUSED' || d.last_tls_status === 'TIMEOUT' ? 'text-red-400' : 'text-gray-400') + '">' + escapeHtml(d.last_tls_status) + '</span>')
    : '<span class="text-gray-500 text-[10px]">not collected</span>';

  exitContent += '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60">'
    + '<span class="text-xs text-gray-500 flex-shrink-0 mr-4">Outbound IP</span>'
    + '<span class="text-xs text-gray-300 font-mono text-right">' + exitIpLabel + '</span>'
    + '</div>';
  exitContent += '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60">'
    + '<span class="text-xs text-gray-500 flex-shrink-0 mr-4">Geo / Country</span>'
    + '<span class="text-xs text-gray-300 text-right">' + exitGeoLabel + '</span>'
    + '</div>';
  exitContent += '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60">'
    + '<span class="text-xs text-gray-500 flex-shrink-0 mr-4">TLS Status</span>'
    + '<span class="text-xs text-right">' + tlsLabel + '</span>'
    + '</div>';
  exitContent += _kv('Exit Protocol',   proto || '—', false);
  exitContent += _kv('Connection Type', d.connection_type || '—', false);
  if (d.tunnel_latency_ms !== null && d.tunnel_latency_ms !== undefined) {
    exitContent += _kv('Tunnel RTT', d.tunnel_latency_ms.toFixed(1) + ' ms', true);
  }
  if (d.ru_server) {
    exitContent += _kv('Entry Server (RU)', (d.ru_server.flag_emoji || '') + ' ' + (d.ru_server.display_name || d.ru_server.ip || '—'), false);
  }
  if (d.server) {
    exitContent += _kv('Exit Server (EU)', (d.server.flag_emoji || '') + ' ' + (d.server.display_name || d.server.ip || '—'), false);
  }
  // Routing detail block
  if (routingDetail && routingOk !== null) {
    var rdColor = routingOk === true ? 'text-green-400' : routingOk === false ? 'text-red-400' : 'text-gray-400';
    exitContent += '<div class="mt-1 px-2 py-1.5 bg-gray-900/50 border border-gray-700/40 rounded-lg">'
      + '<p class="text-[10px] ' + rdColor + ' leading-relaxed">'
      + '<i class="fas fa-route mr-1"></i>'
      + escapeHtml(routingDetail.substring(0, 200))
      + '</p></div>';
  }
  var exitSection = _sectionCard('Exit Information', 'fa-earth-europe', exitContent);

  // ── Section 4: Recovery & Stability ──────────────────────────────────────
  var rs       = d.recovery_status || null;
  var rsLabels = {
    idle:       '<span class="text-gray-500">—</span>',
    recovering: '<span class="text-yellow-400"><i class="fas fa-spinner fa-spin mr-1 text-[9px]"></i>recovering…</span>',
    recovered:  '<span class="text-green-400"><i class="fas fa-circle-check mr-1 text-[9px]"></i>recovered</span>',
    failed:     '<span class="text-red-400"><i class="fas fa-circle-xmark mr-1 text-[9px]"></i>failed</span>',
  };
  var rsHtml     = rsLabels[rs] || (rs ? '<span class="text-gray-400">' + escapeHtml(rs) + '</span>' : '<span class="text-gray-600">—</span>');
  var lastRecAt  = d.last_recovery_at ? new Date(d.last_recovery_at).toLocaleString('ru-RU') : '—';
  var recCount   = d.recovery_count_24h || 0;
  var lastValErr = d.last_validation_error;
  var validErr   = lastValErr
    ? '<div class="mt-2 px-2 py-1.5 bg-red-900/20 border border-red-800/40 rounded-lg">'
      + '<p class="text-[10px] text-red-400 break-words">'
      + '<i class="fas fa-triangle-exclamation mr-1"></i>'
      + escapeHtml(lastValErr.substring(0, 200))
      + '</p></div>'
    : '';

  var recoveryContent = ''
    + '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60">'
    + '<span class="text-xs text-gray-400">Auto-Recovery</span>'
    + '<span class="text-xs">' + rsHtml + '</span>'
    + '</div>'
    + _kv('Attempts (24h)',   recCount > 0 ? recCount : '0', true)
    + _kv('Last Recovery',    lastRecAt, false)
    + validErr;

  // Stability score
  var stabilityScore = 100;
  if (hs === 'DEGRADED')  stabilityScore = 65;
  if (hs === 'BROKEN')    stabilityScore = 20;
  if (recCount > 0)       stabilityScore = Math.max(20, stabilityScore - recCount * 10);
  if (tunnelOk === false) stabilityScore = Math.min(stabilityScore, 30);
  var scoreCls = stabilityScore >= 80 ? 'text-green-400' : stabilityScore >= 50 ? 'text-yellow-400' : 'text-red-400';
  var scoreBar = stabilityScore >= 80 ? 'bg-green-500' : stabilityScore >= 50 ? 'bg-yellow-500' : 'bg-red-500';
  recoveryContent += '<div class="py-1.5">'
    + '<div class="flex justify-between items-center mb-1">'
    + '<span class="text-xs text-gray-400">Stability Score</span>'
    + '<span class="text-xs font-mono ' + scoreCls + '">' + stabilityScore + '/100</span>'
    + '</div>'
    + '<div class="w-full bg-gray-800 rounded-full h-1.5">'
    + '<div class="' + scoreBar + ' h-1.5 rounded-full" style="width:' + stabilityScore + '%"></div>'
    + '</div></div>';

  var recoverySection = _sectionCard('Recovery & Stability', 'fa-shield-check', recoveryContent);

  // ── Section 5: Time & Runtime ─────────────────────────────────────────────
  var lastCheck   = d.last_check_at       ? new Date(d.last_check_at).toLocaleString('ru-RU')       : '—';
  var lastVal     = d.client_validated_at ? new Date(d.client_validated_at).toLocaleString('ru-RU') : '—';
  var lastActive  = d.last_active_at      ? new Date(d.last_active_at).toLocaleString('ru-RU')      : '—';
  var uptimeSec   = d.total_uptime_seconds || 0;
  var uptimeStr   = uptimeSec > 0 ? _fmtUptime(uptimeSec) : '—';
  var createdAt   = d.created_at          ? new Date(d.created_at).toLocaleString('ru-RU')          : '—';

  // e2e validation state
  var valState = d.client_validated_at ? lastVal
    : '<span class="text-[10px] text-yellow-500/80"><i class="fas fa-triangle-exclamation mr-0.5 text-[9px]"></i>not collected — click "Проверить"</span>';

  var timeContent = ''
    + _kv('Last Health Check',     lastCheck,  false)
    + '<div class="flex justify-between items-center py-1.5 border-b border-gray-800/60">'
    +   '<span class="text-xs text-gray-500 flex-shrink-0 mr-4">Last E2E Validation</span>'
    +   '<span class="text-xs text-right">' + valState + '</span>'
    + '</div>'
    + _kv('Last Active',           lastActive, false)
    + _kv('Uptime',                uptimeStr,  true)
    + _kv('Created',               createdAt,  false);
  var timeSection = _sectionCard('Time & Runtime', 'fa-clock', timeContent);

  return headerRow
    + runtimeSection
    + metricsSection
    + exitSection
    + recoverySection
    + timeSection;
}

function _fmtUptime(sec) {
  var d = Math.floor(sec / 86400);
  var h = Math.floor((sec % 86400) / 3600);
  var m = Math.floor((sec % 3600) / 60);
  var parts = [];
  if (d > 0) parts.push(d + 'д');
  if (h > 0) parts.push(h + 'ч');
  if (m > 0) parts.push(m + 'м');
  return parts.length ? parts.join(' ') : '< 1м';
}

async function runDeepHealthCheck(connId) {
  var btn = document.getElementById('hc-btn-' + connId);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin text-[10px]"></i><span class="ml-1.5">Проверка…</span>';
  }

  try {
    const res = await api.get('/connections/' + connId + '/health', { timeout: 60000 });
    if (res.ok) {
      var el = document.getElementById('dstatus-content');
      if (el) el.innerHTML = _buildStatusContent(res.data, connId);
      _updateDetailHeaderBadge(res.data);
      // Обновляем тоже данные в _lastDetailConn
      if (window._lastDetailConn && window._lastDetailConn.id === connId) {
        Object.assign(window._lastDetailConn, res.data);
      }
      var hStatus = res.data.health_status || 'UNKNOWN';
      var cls = hStatus === 'HEALTHY' ? 'success' : hStatus === 'DEGRADED' ? 'warn' : 'error';
      toast('Health check: ' + hStatus, cls, 3000);
    } else {
      toast('Ошибка health check: ' + (res.error || 'unknown'), 'error');
    }
  } catch(e) {
    toast('Health check error: ' + e.message, 'error');
  }

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-rotate-right text-[10px]"></i>Проверить';
  }
}


// ── Tab 2: Protocol Config ────────────────────────────────────────────────────

function _renderConfigTab(conn) {
  if (conn.protocol === 'vless_reality') return _configVless(conn);
  if (conn.protocol === 'amnezia_wg')   return _configAwg(conn);
  if (conn.protocol === 'naive_proxy')  return _configNaive(conn);
  return '<div class="text-gray-500 text-sm text-center py-6">Параметры не доступны</div>';
}

function _paramRow(label, field, value, connId, type, opts) {
  return _paramRowE(label, field, value, connId, type, opts);
}

function _paramRowE(label, field, value, connId, type, opts) {
  type = type || 'text';
  opts = opts || null;
  var inputId = 'param-' + connId + '-' + field;
  var inputEl;

  if (type === 'select' && opts) {
    inputEl = '<select id="' + inputId + '" class="form-input form-input-sm flex-1 min-w-0">'
      + opts.map(function(o) {
          return '<option value="' + escapeHtml(String(o.value)) + '" ' + (o.value == value ? 'selected' : '') + '>' + escapeHtml(o.label) + '</option>';
        }).join('')
      + '</select>';
  } else if (type === 'toggle') {
    inputEl = '<label class="toggle-switch">'
      + '<input type="checkbox" id="' + inputId + '" ' + (value ? 'checked' : '') + '>'
      + '<span class="toggle-slider"></span></label>';
  } else {
    inputEl = '<input type="' + type + '" id="' + inputId + '" value="' + escapeHtml(String(value || '')) + '"'
      + ' class="form-input form-input-sm flex-1 min-w-0 font-mono text-xs">';
  }

  return '<div class="flex items-center gap-3 py-2 border-b border-gray-800 last:border-0">'
    + '<span class="text-xs text-gray-500 w-36 flex-shrink-0">' + label + '</span>'
    + '<div class="flex items-center gap-2 flex-1 min-w-0">'
    + inputEl
    + '<button onclick="applyParam(' + connId + ',\'' + field + '\',document.getElementById(\'' + inputId + '\'))"'
    + ' class="flex-shrink-0 px-2.5 py-1 bg-gray-700 hover:bg-brand-600 rounded text-xs text-gray-300 hover:text-white transition flex items-center gap-1">'
    + '<i class="fas fa-check text-[10px]"></i></button>'
    + '</div></div>';
}

function _configVless(conn) {
  var sniOptions = (window._sniListCache || []).map(function(s) {
    return { value: s.domain, label: (s.best ? '\u2B50 ' : '') + s.domain };
  });
  var fpOptions = ['chrome','firefox','safari','ios','android','edge','360','qq','random','randomized']
    .map(function(f) { return { value: f, label: f }; });

  // Editable fields
  var editBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">Редактируемые параметры</div>'
    + _paramRowE('Server Name (SNI)', 'reality_server_name', conn.reality_server_name, conn.id, 'select', sniOptions.length ? sniOptions : [{value: conn.reality_server_name, label: conn.reality_server_name}])
    + _paramRowE('Fingerprint', 'reality_fingerprint', conn.reality_fingerprint, conn.id, 'select', fpOptions)
    + _paramRowE('Port', 'port', conn.port, conn.id, 'number')
    + _paramRowE('Transport', 'transport', conn.transport || 'tcp', conn.id, 'select', [{value:'tcp',label:'TCP'},{value:'ws',label:'WebSocket'},{value:'grpc',label:'gRPC'}])
    + _paramRowE('Split-tunnel RU', 'split_tunnel_enabled', conn.split_tunnel_enabled, conn.id, 'toggle')
    + _paramRowE('WARP fallback', 'warp_enabled', conn.warp_enabled !== false, conn.id, 'toggle')
    + '</div>';

  // Readonly fields
  var roBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-0">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">Только чтение</div>'
    + _roRow('UUID', conn.uuid, true)
    + _roRow('Public Key', conn.reality_public_key, true)
    + _roRow('Short ID', conn.reality_short_id, true)
    + '</div>';

  return editBlock + roBlock;
}

function _configAwg(conn) {
  var editBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">AWG параметры</div>'
    + _paramRowE('Port',          'port',                    conn.port,                    conn.id, 'number')
    + _paramRowE('Jc (count)',    'awg_junk_packet_count',   conn.awg_junk_packet_count,   conn.id, 'number')
    + _paramRowE('Jmin',          'awg_junk_packet_min_size',conn.awg_junk_packet_min_size,conn.id, 'number')
    + _paramRowE('Jmax',          'awg_junk_packet_max_size',conn.awg_junk_packet_max_size,conn.id, 'number')
    + _paramRowE('S1',            'awg_s1', conn.awg_s1, conn.id, 'number')
    + _paramRowE('S2',            'awg_s2', conn.awg_s2, conn.id, 'number')
    + _paramRowE('H1',            'awg_h1', conn.awg_h1, conn.id, 'number')
    + _paramRowE('H2',            'awg_h2', conn.awg_h2, conn.id, 'number')
    + _paramRowE('H3',            'awg_h3', conn.awg_h3, conn.id, 'number')
    + _paramRowE('H4',            'awg_h4', conn.awg_h4, conn.id, 'number')
    + '</div>';

  var roBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-0">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">Только чтение</div>'
    + _roRow('Client Public Key', conn.wg_client_public_key, true)
    + _roRow('Client IP',         conn.wg_client_ip, true)
    + '</div>';

  return editBlock + roBlock;
}

function _configNaive(conn) {
  var editBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">NaiveProxy параметры</div>'
    + _paramRowE('Домен',         'np_domain', conn.np_domain, conn.id, 'text')
    + _paramRowE('Username',      'np_user',   conn.np_user,   conn.id, 'text')
    + _paramRowE('Password',      'password',  conn.password,  conn.id, 'text')
    + _paramRowE('Port',          'port',      conn.port,      conn.id, 'number')
    + _paramRowE('Split-tunnel',  'split_tunnel_enabled', conn.split_tunnel_enabled, conn.id, 'toggle')
    + _paramRowE('WARP fallback', 'warp_enabled', conn.warp_enabled !== false, conn.id, 'toggle')
    + '</div>';

  return editBlock;
}

async function applyParam(connId, field, inputEl) {
  var value = inputEl.type === 'checkbox' ? inputEl.checked : inputEl.value;
  if (inputEl.type === 'number') value = parseInt(value);

  var btn = inputEl.parentElement ? inputEl.parentElement.querySelector('button') : null;
  if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin text-[10px]"></i>';

  const res = await api.patch('/connections/' + connId + '/param', { field: field, value: value });

  if (btn) btn.innerHTML = res.ok
    ? '<i class="fas fa-check text-[10px] text-green-400"></i>'
    : '<i class="fas fa-xmark text-[10px] text-red-400"></i>';

  setTimeout(function() {
    if (btn) btn.innerHTML = '<i class="fas fa-check text-[10px]"></i>';
  }, 2500);

  if (!res.ok) toast('Ошибка: ' + res.error, 'error');
  else toast('Параметр обновлён и применён', 'success', 2000);
}

// ── Tab 3: Routing & Network ──────────────────────────────────────────────────

function _renderRoutingTab(conn) {
  var typeLabel = conn.connection_type === 'direct' ? 'Прямое' : 'Каскадное';
  var srv  = conn.server || {};
  var flag = srv.flag_emoji || '';
  var dname = srv.display_name || srv.name || srv.ip || '';
  var euLabel = flag + ' ' + (dname || srv.ip || '\u2014');

  // RU server (cascade)
  var ruRow = '';
  if (conn.ru_server) {
    var ruF = conn.ru_server.flag_emoji || '';
    ruRow = _kv('RU сервер (вход)', ruF + ' ' + escapeHtml(conn.ru_server.name || conn.ru_server.ip), false);
  }

  var topoBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-3 space-y-0">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">Топология</div>'
    + _kv('Режим', typeLabel, false)
    + _kv('EU сервер (выход)', euLabel.trim(), false)
    + ruRow
    + _kv('Тип протокола', (conn.connection_type || 'direct'), false)
    + '</div>';

  var activeOutIP  = conn.last_outbound_ip  || '\u2014';
  var activeOutGeo = conn.last_outbound_geo || '\u2014';
  var exitSrv = conn.exit_server_id ? '#' + conn.exit_server_id : '\u2014';

  var outboundBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-3 space-y-0">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">Активный Outbound</div>'
    + _kv('Exit IP',    activeOutIP,  true)
    + _kv('Geo',        activeOutGeo, false)
    + _kv('Exit server', exitSrv, true)
    + '</div>';

  // WARP toggle
  var warpBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-4">'
    + '<div class="flex items-center justify-between">'
    + '<div>'
    + '<span class="text-xs text-gray-300 font-medium">WARP fallback</span>'
    + '<p class="text-[10px] text-gray-600 mt-0.5">Cloudflare WARP как резервный outbound в Xray</p>'
    + '</div>'
    + '<label class="toggle-switch flex-shrink-0">'
    + '<input type="checkbox" id="warp-toggle-' + conn.id + '" ' + (conn.warp_enabled ? 'checked' : '')
    + ' onchange="toggleWarp(' + conn.id + ', this.checked)">'
    + '<span class="toggle-slider"></span>'
    + '</label>'
    + '</div>'
    + '</div>';

  return topoBlock + outboundBlock + warpBlock;
}

// ── Tab 4: Client Configs ─────────────────────────────────────────────────────

function _renderClientsTab(conn) {
  window._lastDetailConn = conn;
  const hasUri  = !!conn.client_link;
  const hasConf = !!conn.config_text;
  const proto   = conn.protocol;
  const SUB_TOKEN = 'dnBuOm1pbGt5aW1zMjAyNA==';
  const subBase = location.origin + '/api/v1/subscribe/' + SUB_TOKEN;

  if (!hasUri && !hasConf) return '<div class="text-center py-8 text-gray-500 text-sm">'
    + '<i class="fas fa-hourglass-half text-2xl mb-2 block"></i>'
    + 'Конфиги ещё не сгенерированы — дождитесь завершения деплоя</div>';

  if (proto === 'vless_reality') return ''
    + '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div class="flex items-center justify-between">'
    + '<div><span class="text-xs font-semibold text-white">URI / QR-код</span>'
    + '<div class="text-xs text-gray-500 mt-0.5"><i class="fas fa-mobile-alt mr-1"></i>v2rayTun · HAPP · AmneziaVPN · Hiddify · v2rayNG</div></div>'
    + '<button class="copy-btn text-xs" data-copy-id="uri-' + conn.id + '"><i class="fas fa-copy mr-1"></i>Копировать</button>'
    + '</div>'
    + '<div id="uri-' + conn.id + '" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 break-all select-all max-h-24 overflow-y-auto border border-gray-700">' + escapeHtml(conn.client_link) + '</div>'
    + '<div class="flex justify-center pt-1"><div id="conn-qr-canvas" class="bg-gray-900 rounded-xl p-2" style="min-width:180px;min-height:180px;display:flex;align-items:center;justify-content:center;"></div></div>'
    + '<p class="text-center text-xs text-gray-600">Отсканируй QR или скопируй URI</p>'
    + '</div>'
    + '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div><span class="text-xs font-semibold text-white">Subscription URL</span>'
    + '<div class="text-xs text-gray-500 mt-0.5"><i class="fas fa-mobile-alt mr-1"></i>sing-box · Hiddify · Clash/Mihomo</div>'
    + '<p class="text-xs text-gray-600 mt-1">Одна ссылка — все активные подключения сразу</p></div>'
    + '<div class="space-y-2">'
    + '<div class="flex items-center gap-2"><span class="text-xs text-gray-400 w-20 shrink-0 font-medium">sing-box</span>'
    + '<div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-sb-' + conn.id + '">' + subBase + '?format=singbox</div>'
    + '<button class="copy-btn text-xs shrink-0" data-copy-id="sub-sb-' + conn.id + '"><i class="fas fa-copy"></i></button></div>'
    + '<div class="flex items-center gap-2"><span class="text-xs text-gray-400 w-20 shrink-0 font-medium">Clash</span>'
    + '<div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-cl-' + conn.id + '">' + subBase + '?format=clash</div>'
    + '<button class="copy-btn text-xs shrink-0" data-copy-id="sub-cl-' + conn.id + '"><i class="fas fa-copy"></i></button></div>'
    + '</div></div>';

  if (proto === 'amnezia_wg') return ''
    + '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div class="flex items-center justify-between">'
    + '<div><span class="text-xs font-semibold text-white">.conf файл</span>'
    + '<div class="text-xs text-gray-500 mt-0.5"><i class="fas fa-mobile-alt mr-1"></i>AmneziaVPN (iOS / Android / Desktop)</div></div>'
    + '<div class="flex gap-2">'
    + '<button class="copy-btn text-xs" data-copy-id="conf-' + conn.id + '"><i class="fas fa-copy mr-1"></i>Копировать</button>'
    + '<button onclick="downloadConfig(' + conn.id + ')" class="copy-btn text-xs"><i class="fas fa-download mr-1"></i>Скачать</button>'
    + '</div></div>'
    + '<pre id="conf-' + conn.id + '" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 whitespace-pre-wrap break-all select-all max-h-44 overflow-y-auto border border-gray-700">' + escapeHtml(conn.config_text || '') + '</pre>'
    + '</div>'
    + '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div><span class="text-xs font-semibold text-white">QR-код</span>'
    + '<div class="text-xs text-gray-500 mt-0.5"><i class="fas fa-mobile-alt mr-1"></i>AmneziaVPN (iOS / Android)</div></div>'
    + '<div class="flex justify-center"><div id="conn-qr-canvas" class="bg-gray-900 rounded-xl p-2" style="min-width:180px;min-height:180px;display:flex;align-items:center;justify-content:center;"></div></div>'
    + '<p class="text-center text-xs text-gray-600">Отсканируй QR в приложении AmneziaVPN</p>'
    + '</div>'
    + '<div class="bg-yellow-900/30 border border-yellow-700/50 rounded-xl p-3">'
    + '<p class="text-xs text-yellow-400"><i class="fas fa-triangle-exclamation mr-1"></i>AmneziaWG работает <strong>только</strong> в приложении AmneziaVPN.</p>'
    + '</div>';

  if (proto === 'naive_proxy') return ''
    + '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div><span class="text-xs font-semibold text-white">Subscription URL</span>'
    + '<div class="text-xs text-gray-500 mt-0.5"><i class="fas fa-mobile-alt mr-1"></i>sing-box · Hiddify · Clash/Mihomo</div>'
    + '<p class="text-xs text-gray-600 mt-1">Одна ссылка — все активные подключения сразу</p></div>'
    + '<div class="space-y-2">'
    + '<div class="flex items-center gap-2"><span class="text-xs text-gray-400 w-20 shrink-0 font-medium">sing-box</span>'
    + '<div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-sb-' + conn.id + '">' + subBase + '?format=singbox</div>'
    + '<button class="copy-btn text-xs shrink-0" data-copy-id="sub-sb-' + conn.id + '"><i class="fas fa-copy"></i></button></div>'
    + '<div class="flex items-center gap-2"><span class="text-xs text-gray-400 w-20 shrink-0 font-medium">Clash</span>'
    + '<div class="flex-1 font-mono text-xs text-gray-300 bg-gray-900 rounded-lg px-3 py-2 truncate border border-gray-700" id="sub-cl-' + conn.id + '">' + subBase + '?format=clash</div>'
    + '<button class="copy-btn text-xs shrink-0" data-copy-id="sub-cl-' + conn.id + '"><i class="fas fa-copy"></i></button></div>'
    + '</div></div>'
    + (hasConf ? '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div class="flex items-center justify-between">'
    + '<div><span class="text-xs font-semibold text-white">JSON конфиг</span>'
    + '<div class="text-xs text-gray-500 mt-0.5"><i class="fas fa-desktop mr-1"></i>NaiveProxy CLI</div></div>'
    + '<div class="flex gap-2"><button class="copy-btn text-xs" data-copy-id="conf-' + conn.id + '"><i class="fas fa-copy mr-1"></i>Копировать</button>'
    + '<button onclick="downloadConfig(' + conn.id + ')" class="copy-btn text-xs"><i class="fas fa-download mr-1"></i>Скачать</button></div></div>'
    + '<pre id="conf-' + conn.id + '" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 whitespace-pre-wrap break-all select-all max-h-44 overflow-y-auto border border-gray-700">' + escapeHtml(conn.config_text) + '</pre>'
    + '</div>' : '')
    + '<div class="bg-blue-900/30 border border-blue-700/50 rounded-xl p-3">'
    + '<p class="text-xs text-blue-400"><i class="fas fa-circle-info mr-1"></i>NaiveProxy работает через HTTPS-прокси.</p>'
    + '</div>';

  // Fallback
  return (hasUri ? '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div class="flex items-center justify-between"><span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">URI</span>'
    + '<button class="copy-btn text-xs" data-copy-id="uri-' + conn.id + '"><i class="fas fa-copy mr-1"></i>Копировать</button></div>'
    + '<div id="uri-' + conn.id + '" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 break-all select-all max-h-28 overflow-y-auto border border-gray-700">' + escapeHtml(conn.client_link) + '</div>'
    + '</div>' : '')
    + (hasConf ? '<div class="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">'
    + '<div class="flex items-center justify-between"><span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Конфиг</span>'
    + '<button class="copy-btn text-xs" data-copy-id="conf-' + conn.id + '"><i class="fas fa-copy mr-1"></i>Копировать</button></div>'
    + '<pre id="conf-' + conn.id + '" class="font-mono text-xs text-gray-300 bg-gray-900 rounded-lg p-3 whitespace-pre-wrap break-all select-all max-h-40 overflow-y-auto border border-gray-700">' + escapeHtml(conn.config_text) + '</pre>'
    + '</div>' : '')
    + '<div class="flex justify-center pt-1"><div id="conn-qr-canvas" class="bg-gray-900 rounded-xl p-2" style="min-width:180px;min-height:180px;display:flex;align-items:center;justify-content:center;"></div></div>';
}

function _maybeGenQR(conn) {
  const qrEl = document.getElementById('conn-qr-canvas');
  if (!qrEl) return;

  let raw = conn.client_link || conn.config_text || '';
  if (!raw) {
    qrEl.innerHTML = '<div class="text-xs text-gray-600 text-center p-4">QR недоступен</div>';
    return;
  }

  let qrData = raw;
  if (/^vless:\/\//i.test(raw) || /^trojan:\/\//i.test(raw)) {
    qrData = raw.split('#')[0];
  }

  if (qrData.length > 2048) {
    qrEl.innerHTML = '<div class="text-xs text-gray-600 text-center p-4">URI слишком длинный для QR</div>';
    return;
  }

  qrEl.innerHTML = '';
  try {
    new QRCode(qrEl, {
      text: qrData, width: 196, height: 196,
      colorDark: '#ffffff', colorLight: '#111827',
      correctLevel: QRCode.CorrectLevel.M,
    });
  } catch(e) {
    qrEl.innerHTML = '<div class="text-xs text-gray-600 text-center p-4">QR ошибка</div>';
  }
}

function downloadConfig(connId) {
  window.open('/api/v1/connections/' + connId + '/download', '_blank');
}

// ── Tab 5: Diagnostics & Logs ─────────────────────────────────────────────────

function _renderDiagTab(conn) {
  var deployLog  = conn.setup_log    || '';
  var recovLog   = conn.recovery_log || '';

  var deployBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-3">'
    + '<div class="flex items-center justify-between mb-2">'
    + '<span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Deploy Log</span>'
    + '<button onclick="_loadDiagLog(' + conn.id + ', \'setup\')" class="text-[10px] text-brand-400 hover:underline"><i class="fas fa-rotate-right mr-1"></i>Обновить</button>'
    + '</div>'
    + '<pre id="diag-deploy-log" class="font-mono text-[10px] text-gray-400 bg-gray-900 rounded-lg p-2.5 whitespace-pre-wrap max-h-48 overflow-y-auto border border-gray-800">'
    + (deployLog ? escapeHtml(deployLog) : '<span class="text-gray-600">Лог недоступен</span>')
    + '</pre>'
    + '</div>';

  var hcLogBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-3">'
    + '<div class="flex items-center justify-between mb-2">'
    + '<span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Health Check</span>'
    + '<div class="flex items-center gap-2">'
    + (conn.last_check_at ? '<span class="text-[10px] text-gray-600">Последняя: ' + new Date(conn.last_check_at).toLocaleTimeString('ru-RU') + '</span>' : '')
    + '</div>'
    + '</div>'
    + '<div class="space-y-1">'
    + _kv('Статус', conn.health_status || '\u2014', false)
    + _kv('Latency', conn.latency_ms !== null && conn.latency_ms !== undefined ? conn.latency_ms.toFixed(1) + ' ms' : '\u2014', true)
    + _kv('Jitter', conn.jitter_ms !== null && conn.jitter_ms !== undefined ? conn.jitter_ms.toFixed(1) + ' ms' : '\u2014', true)
    + _kv('Packet loss', conn.packet_loss_pct !== null && conn.packet_loss_pct !== undefined ? conn.packet_loss_pct.toFixed(1) + '%' : '\u2014', true)
    + _kv('TLS', conn.last_tls_status || '\u2014', false)
    + _kv('Outbound IP', conn.last_outbound_ip || '\u2014', true)
    + _kv('Outbound Geo', conn.last_outbound_geo || '\u2014', false)
    + '</div>'
    + '</div>';

  var recovBlock = '<div class="bg-gray-800/50 border border-gray-700 rounded-xl p-3">'
    + '<div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2 font-semibold">Recovery Log</div>'
    + '<pre id="diag-recovery-log" class="font-mono text-[10px] text-gray-400 bg-gray-900 rounded-lg p-2.5 whitespace-pre-wrap max-h-40 overflow-y-auto border border-gray-800">'
    + (recovLog ? escapeHtml(recovLog) : '<span class="text-gray-600">Нет записей</span>')
    + '</pre>'
    + '</div>';

  return deployBlock + hcLogBlock + recovBlock;
}

async function _loadDiagLog(connId, type) {
  const res = await api.get('/connections/' + connId, { timeout: 10000 });
  if (!res.ok) return;
  const d = res.data;
  if (type === 'setup') {
    var el = document.getElementById('diag-deploy-log');
    if (el) el.innerHTML = d.setup_log ? escapeHtml(d.setup_log) : '<span class="text-gray-600">Лог недоступен</span>';
  }
}

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
window._loadSniList             = _loadSniList;
window.showAddConnectionModal   = showAddConnectionModal;
window.wizToggleType            = wizToggleType;
window.wizGoStep2               = wizGoStep2;
window.wizToggleProtocol        = wizToggleProtocol;
window.wizSelectAllProtocols    = wizSelectAllProtocols;
window.wizClearAllProtocols     = wizClearAllProtocols;
window.wizGoStep3               = wizGoStep3;
window.wizSubmit                = wizSubmit;
window._syncWizSteps            = _syncWizSteps;
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
// Динамический маппинг: protocol -> step index (заполняется в openConnSetupModal)
let _csdDynStep    = {};  // { vless_reality: 1, amnezia_wg: 2, ... }
let _csdDynTotal   = 0;   // кол-во точек в timeline

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
  // Используем динамический маппинг (заполнен в openConnSetupModal)
  const dynStep  = _csdDynStep;
  const dynTotal = _csdDynTotal || 1;

  // Индекс cascade-шага и финального шага (если есть)
  const cascadeN = dynStep['__cascade__'] || 0;
  const finishN  = dynStep['__finish__']  || 0;

  // Group connections by modal step
  const stepConns = {};
  for (let i = 1; i <= dynTotal; i++) stepConns[i] = [];

  for (const c of connections) {
    const proto = c.protocol || 'vless_reality';
    const protoStep = dynStep[proto] || 1;
    if (stepConns[protoStep]) stepConns[protoStep].push(c);

    // Cascade step: connections with connection_type=cascade
    if (c.connection_type === 'cascade' && cascadeN) {
      if (!stepConns[cascadeN]) stepConns[cascadeN] = [];
      stepConns[cascadeN].push(c);
    }

    // Finish step: all connections feed finish info
    if (finishN) {
      if (!stepConns[finishN]) stepConns[finishN] = [];
      stepConns[finishN].push(c);
    }
  }

  // Process each modal step
  for (let n = 1; n <= dynTotal; n++) {
    const conns = stepConns[n] || [];
    if (!conns.length) continue;

    const dotStates = [];

    for (const c of conns) {
      const proto = c.protocol || 'vless_reality';
      const protoStep = dynStep[proto] || 1;
      const typeLabel = c.connection_type === 'cascade' ? 'CASCADE' : 'DIRECT';
      const protoName = _CSD_STEP_LABEL[protoStep] || proto;
      const headerLabel = `${protoName} · ${typeLabel}`;

      const steps     = c.steps || [];
      const stepItems = steps.filter(s => s.is_step && s.n >= 1);
      const infoItems = steps.filter(s => !s.is_step);

      // For step n == protoStep: show all [STEP:N:...] lines from this connection
      if (n === protoStep && n !== cascadeN && n !== finishN) {
        const lines = stepItems.map(s => `[${s.n}] ${s.msg}`);
        _csdAppendLog(n, headerLabel, lines, c.setup_status !== 'done' || stepItems.some(s => s.status === 'error'));
        dotStates.push(_csdConnDotState(c));
      }

      // For cascade step: show only cascade-relevant log lines (DIRECT ones excluded)
      if (cascadeN && n === cascadeN && c.connection_type === 'cascade') {
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

      // For finish step: show WARP / split-tunnel info lines from all connections
      if (finishN && n === finishN) {
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
      if (n < dynTotal && allTerminal && dotState !== 'error') {
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
        const s = dynStep[c.protocol] || 1;
        return _CSD_STEP_LABEL[s] || c.protocol;
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

function openConnSetupModal(connIds, euServerName, connectionTypes, selectedProtocols) {
  _connSetupIds  = connIds;
  _connSetupData = {};

  const modal = document.getElementById('modal-conn-setup');
  if (!modal) { console.error('[ConnSetup] modal not found!'); return; }

  // ── Определяем набор протоколов и флаг cascade ──────────────────────
  // selectedProtocols — массив из wizard (приоритет, до поллинга)
  // connectionTypes   — массив из API: [{protocol, connection_type}, ...]
  const hasProto = { vless_reality:false, amnezia_wg:false, naive_proxy:false };
  let hasCascade = false;

  // Приоритет: selectedProtocols из wizard (известны сразу при открытии)
  if (selectedProtocols && selectedProtocols.length) {
    selectedProtocols.forEach(p => { if (p in hasProto) hasProto[p] = true; });
  }
  // Дополнительно connectionTypes из API (уточняет cascade-флаг)
  (connectionTypes || []).forEach(ct => {
    if (ct.protocol in hasProto) hasProto[ct.protocol] = true;
    if (ct.connection_type === 'cascade') hasCascade = true;
  });

  // ── Строим динамический список слотов ───────────────────────────────
  // Порядок: выбранные протоколы → Cascade (если есть) → Финал (если > 1 или cascade)
  const PROTO_DEFS = [
    { key: 'vless_reality', label: 'VLESS+Reality', dotLabel: 'VLESS'      },
    { key: 'amnezia_wg',    label: 'AmneziaWG',     dotLabel: 'AWG'        },
    { key: 'naive_proxy',   label: 'NaiveProxy',    dotLabel: 'NaiveProxy' },
  ];

  const slots = [];
  PROTO_DEFS.forEach(pd => { if (hasProto[pd.key]) slots.push(pd); });
  if (hasCascade) slots.push({ key: '__cascade__', label: 'Cascade / RU Xray routing', dotLabel: 'Cascade' });
  if (hasCascade || slots.length > 1) {
    slots.push({ key: '__finish__', label: 'WARP / Split-tunnel / Финал', dotLabel: 'Финал' });
  }

  // ── Записываем динамический маппинг ─────────────────────────────────
  _csdDynStep  = {};
  _csdDynTotal = slots.length;
  slots.forEach((s, idx) => { _csdDynStep[s.key] = idx + 1; });

  // Синхронизируем _CSD_STEP_LABEL под текущий набор слотов
  slots.forEach((s, idx) => { _CSD_STEP_LABEL[idx + 1] = s.label; });

  // ── Рендерим timeline-точки в #csd-timeline-wrap ────────────────────
  const timelineWrap = document.getElementById('csd-timeline-wrap');
  if (timelineWrap) {
    timelineWrap.innerHTML = '';
    slots.forEach((s, idx) => {
      const n = idx + 1;
      const dotWrap = document.createElement('div');
      dotWrap.className = 'flex flex-col items-center';
      dotWrap.innerHTML =
        '<div class="stp-dot stp-pending" id="csd-dot-' + n + '"></div>' +
        '<span class="text-[9px] text-gray-600 mt-1.5 whitespace-nowrap">' + s.dotLabel + '</span>';
      timelineWrap.appendChild(dotWrap);
      // Коннектор между точками (не после последней)
      if (n < slots.length) {
        const conn = document.createElement('div');
        conn.className = 'stp-connector flex-1';
        conn.id = 'csd-conn-' + n;
        timelineWrap.appendChild(conn);
      }
    });
  }

  // ── Сбрасываем и показываем accordion-блоки ─────────────────────────
  // Фиксированные HTML-номера accordion: VLESS=1, AWG=2, Naive=3, Cascade=4, Финал=5
  for (let i = 1; i <= 5; i++) {
    const wrap = document.getElementById('csd-step-' + i + '-wrap');
    const log  = document.getElementById('csd-log-' + i);
    const icon = document.getElementById('csd-icon-' + i);
    const chev = document.getElementById('csd-chev-' + i);
    if (wrap) wrap.classList.add('hidden');
    if (log)  { log.innerHTML = ''; log.classList.add('hidden'); }
    if (icon) icon.textContent = '·';
    if (chev) chev.style.transform = '';
  }
  // Показываем только accordion'ы для реально выбранных слотов
  const HTML_ACCORDION = { vless_reality:1, amnezia_wg:2, naive_proxy:3, __cascade__:4, __finish__:5 };
  slots.forEach(s => {
    const htmlN = HTML_ACCORDION[s.key];
    if (!htmlN) return;
    const wrap = document.getElementById('csd-step-' + htmlN + '-wrap');
    if (!wrap) return;
    wrap.classList.remove('hidden');
    // Обновляем текст заголовка accordion под текущий слот
    // Ищем span с заголовком (класс text-[11px] font-semibold в кнопке accordion)
    const labelSpan = wrap.querySelector('button span.flex-1');
    if (labelSpan) labelSpan.textContent = s.label;
  });

  // ── Header ──────────────────────────────────────────────────────────
  const titleEl = document.getElementById('conn-setup-title');
  const subtEl  = document.getElementById('conn-setup-subtitle');
  const srvEl   = document.getElementById('conn-setup-server-name');
  if (titleEl) titleEl.textContent = 'Настройка подключений';
  if (subtEl)  subtEl.textContent  = 'Шаги выполняются последовательно';
  if (srvEl)   srvEl.textContent   = euServerName || '';

  _cdSetDot('running');
  _cdSetProgress(0);

  const errBlock = document.getElementById('conn-setup-error-block');
  if (errBlock) errBlock.classList.add('hidden');
  _cdShowBtn('conn-setup-btn-retry',  false);
  _cdShowBtn('conn-setup-btn-done',   false);
  _cdShowBtn('conn-setup-btn-cancel', true);

  modal.classList.remove('hidden');
  console.log('[ConnSetup] Opened | ids:', connIds,
    '| slots:', slots.map(s => s.dotLabel).join(' + '),
    '| dynStep:', JSON.stringify(_csdDynStep));
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
      for (let i = 1; i <= (_csdDynTotal || 5); i++) {
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
  for (let i = 1; i <= (_csdDynTotal || 5); i++) _csdSetDot(i, 'pending');
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

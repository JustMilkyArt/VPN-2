/**
 * Connections tab logic — v2
 * Supports: VLESS+Reality, AmneziaWG, Trojan, NaiveProxy
 * Features: SNI top-10 picker, QR-code, multi-format config, smart form UX
 */

// ─── LOAD CONNECTIONS ────────────────────────────────────────────────────────
async function loadConnectionsGrouped() {
  const listEl = document.getElementById('connections-list');
  const emptyEl = document.getElementById('connections-empty');
  listEl.innerHTML = `<div class="flex justify-center py-8"><span class="spinner"></span></div>`;

  const res = await api.getConnectionsGrouped();
  if (!res.ok) {
    listEl.innerHTML = `<div class="text-center text-red-400 py-8">
      <i class="fas fa-circle-exclamation mr-2"></i>Ошибка: ${res.error}
    </div>`;
    return;
  }

  const groups = res.data;
  const hasConnections = groups.some(g => g.connections.length > 0);

  if (!hasConnections) {
    listEl.innerHTML = '';
    emptyEl.classList.remove('hidden');
    return;
  }

  emptyEl.classList.add('hidden');
  listEl.innerHTML = groups.map(renderConnectionGroup).filter(Boolean).join('');
}

// ─── RENDER GROUP ────────────────────────────────────────────────────────────
function renderConnectionGroup(group) {
  if (group.connections.length === 0) return '';
  const { server } = group;
  const flag = getFlag(server.country);

  return `
<div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
  <div class="flex items-center justify-between px-4 py-3 bg-gray-800/50 border-b border-gray-800">
    <div class="flex items-center gap-2.5">
      <span class="text-xl">${flag}</span>
      <div>
        <div class="font-semibold text-white text-sm">${server.name}</div>
        <div class="text-gray-500 text-xs font-mono">${server.ip}</div>
      </div>
      ${roleLabel(server.role)}
    </div>
    <div class="flex items-center gap-1.5">
      ${statusDot(server.status)}
      ${statusText(server.status)}
    </div>
  </div>
  <div class="p-3 space-y-2">
    ${group.connections.map(conn => renderConnectionRow(conn, server)).join('')}
  </div>
</div>`;
}

// ─── RENDER ROW ──────────────────────────────────────────────────────────────
function renderConnectionRow(conn, server) {
  const proto = protocolLabel(conn.protocol);
  const statusClass = {
    active:    'text-green-400 bg-green-900/30',
    inactive:  'text-gray-500 bg-gray-800',
    deploying: 'text-amber-400 bg-amber-900/30',
    error:     'text-red-400 bg-red-900/30',
  }[conn.status] || 'text-gray-500';

  return `
<div class="connection-row flex items-center gap-3" id="conn-row-${conn.id}">
  <span class="protocol-badge ${conn.protocol} flex-shrink-0">
    <i class="fas ${proto.icon}"></i>${proto.text}
  </span>
  <div class="flex-1 min-w-0">
    <div class="text-sm font-medium text-white truncate">${escapeHtml(conn.name)}</div>
    <div class="text-xs text-gray-500 font-mono">:${conn.port}</div>
  </div>
  <span class="text-xs px-2 py-0.5 rounded ${statusClass} flex-shrink-0">${conn.status}</span>
  <label class="toggle-switch flex-shrink-0">
    <input type="checkbox" ${conn.is_active ? 'checked' : ''} onchange="toggleConn(${conn.id}, this.checked)">
    <span class="toggle-slider"></span>
  </label>
  <div class="flex items-center gap-1 flex-shrink-0">
    <button onclick="showClientConfig(${conn.id})" class="action-btn" title="Конфигурация и QR">
      <i class="fas fa-qrcode"></i>
    </button>
    <button onclick="confirmDeleteConnection(${conn.id}, '${escapeHtml(conn.name)}')" class="action-btn danger" title="Удалить">
      <i class="fas fa-trash"></i>
    </button>
  </div>
</div>`;
}

// ─── TOGGLE ──────────────────────────────────────────────────────────────────
async function toggleConn(connId, active) {
  const res = await api.toggleConnection(connId, active);
  if (res.ok) {
    toast(`Подключение ${active ? 'включено' : 'отключено'}`, 'success', 2000);
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
    loadConnectionsGrouped();
  }
}

// ─── SNI CACHE ───────────────────────────────────────────────────────────────
let _sniList = null;
async function _loadSniList() {
  if (_sniList) return _sniList;
  const res = await api.getSniList();
  if (res.ok) _sniList = res.data;
  return _sniList || [];
}

function _buildSniOptions(list) {
  return list.map(item => {
    const star = item.best ? '⭐ ' : '';
    const rec = item.best ? ' (рекомендуется)' : '';
    return `<option value="${item.domain}" ${item.best ? 'selected' : ''}>${star}${item.domain} — ${item.note}${rec}</option>`;
  }).join('');
}

// ─── PROTOCOL HINTS ──────────────────────────────────────────────────────────
const PROTO_HINTS = {
  vless_reality: '🔒 Максимальная защита от DPI. Маскируется под легитимный TLS-сайт.',
  amnezia_wg:    '🛡️ WireGuard с обфускацией трафика. Работает там, где WireGuard заблокирован.',
  trojan:        '⚡ TLS-туннель, выглядит как HTTPS. Требует домен и сертификат.',
  naive_proxy:   '🌐 HTTPS-прокси через Caddy. Простая установка, хорошая скрытость.',
};

// ─── SMART FORM: protocol change handler ─────────────────────────────────────
async function onConnProtocolChange() {
  const proto = document.getElementById('conn-protocol-select').value;
  const sniBlock = document.getElementById('conn-sni-block');
  const exitBlock = document.getElementById('conn-exit-server-block');
  const hintEl = document.getElementById('conn-proto-hint');
  const nameInput = document.getElementById('conn-name-input');

  // Show/hide SNI block
  if (proto === 'vless_reality') {
    sniBlock.classList.remove('hidden');
    // Fill SNI options
    const sniSelect = document.getElementById('conn-sni-select');
    if (!sniSelect.options.length || sniSelect.options.length === 1) {
      sniSelect.innerHTML = '<option value="">Загрузка...</option>';
      const list = await _loadSniList();
      sniSelect.innerHTML = _buildSniOptions(list);
    }
  } else {
    sniBlock.classList.add('hidden');
  }

  // Exit server — only show for non-EU server contexts (future)
  // For now: show for vless_reality and trojan (cascade capable)
  if (proto === 'vless_reality') {
    exitBlock.classList.remove('hidden');
  } else {
    exitBlock.classList.add('hidden');
  }

  // Protocol hint
  hintEl.textContent = PROTO_HINTS[proto] || '';

  // Auto-fill name suggestion if empty
  if (nameInput && !nameInput.value) {
    const serverSelect = document.getElementById('conn-server-select');
    const serverOpt = serverSelect.options[serverSelect.selectedIndex];
    const serverTag = serverOpt && serverOpt.dataset.country ? serverOpt.dataset.country : 'SRV';
    const protoTag = { vless_reality: 'VLESS', amnezia_wg: 'AWG', trojan: 'TRJ', naive_proxy: 'NP' }[proto] || proto.toUpperCase();
    nameInput.placeholder = `${protoTag}-${serverTag}-01`;
  }
}

function onConnServerChange() {
  // Re-trigger protocol handler to update name hint
  onConnProtocolChange();
}

// ─── ADD CONNECTION MODAL ─────────────────────────────────────────────────────
async function showAddConnectionModal() {
  document.getElementById('add-connection-form').reset();
  document.getElementById('add-connection-error').classList.add('hidden');
  document.getElementById('add-connection-progress').classList.add('hidden');
  document.getElementById('conn-exit-server-block').classList.add('hidden');
  document.getElementById('conn-sni-block').classList.add('hidden');
  document.getElementById('conn-proto-hint').textContent = '';

  // Load servers
  const res = await api.getServers();
  if (!res.ok) { toast('Не удалось загрузить серверы', 'error'); return; }

  const servers = res.data.filter(s => s.is_active);
  const select = document.getElementById('conn-server-select');
  const exitSelect = document.getElementById('conn-exit-select');

  select.innerHTML = '<option value="">— Выберите сервер —</option>' +
    servers.map(s =>
      `<option value="${s.id}" data-country="${s.country}" data-role="${s.role}">${getFlag(s.country)} ${escapeHtml(s.name)} (${s.ip}) — ${s.role}</option>`
    ).join('');

  const euServers = servers.filter(s => s.role === 'EU' || s.role === 'MIXED');
  exitSelect.innerHTML = '<option value="">— Прямой выход (без каскада) —</option>' +
    euServers.map(s =>
      `<option value="${s.id}">${getFlag(s.country)} ${escapeHtml(s.name)} (${s.ip})</option>`
    ).join('');

  // Pre-select VLESS+Reality and trigger UI update
  const protoSelect = document.getElementById('conn-protocol-select');
  protoSelect.value = 'vless_reality';
  await onConnProtocolChange();

  openModal('modal-add-connection');
}

// ─── FORM SUBMIT ─────────────────────────────────────────────────────────────
document.getElementById('add-connection-form').addEventListener('submit', (e) => {
  e.preventDefault();
  closeModal('modal-add-connection');
});

// Attach change listeners
document.getElementById('conn-protocol-select').addEventListener('change', onConnProtocolChange);
document.getElementById('conn-server-select').addEventListener('change', onConnServerChange);

// ─── CLIENT CONFIG MODAL ──────────────────────────────────────────────────────
async function showClientConfig(connId) {
  openModal('modal-client-config');
  const content = document.getElementById('client-config-content');
  content.innerHTML = '<div class="flex justify-center py-8"><span class="spinner"></span></div>';

  const res = await api.getClientConfig(connId);
  if (!res.ok) {
    content.innerHTML = `<div class="text-red-400 text-sm p-4">Ошибка: ${res.error}</div>`;
    return;
  }

  const cfg = res.data;
  const proto = protocolLabel(cfg.protocol);
  content.innerHTML = renderClientConfigContent(cfg, proto);

  // Generate QR after render
  const qrEl = document.getElementById('config-qr-canvas');
  const qrData = cfg.client_link || cfg.config_json || '';
  if (qrEl && qrData && qrData.length < 2048) {
    try {
      new QRCode(qrEl, {
        text: qrData,
        width: 200,
        height: 200,
        colorDark: '#ffffff',
        colorLight: '#1f2937',
        correctLevel: QRCode.CorrectLevel.M,
      });
    } catch (e) {
      qrEl.innerHTML = '<div class="text-gray-600 text-xs text-center py-4">QR недоступен</div>';
    }
  } else if (qrEl) {
    qrEl.innerHTML = '<div class="text-gray-600 text-xs text-center py-4">Конфиг слишком большой для QR</div>';
  }
}

function renderClientConfigContent(cfg, proto) {
  const isVless    = cfg.protocol === 'vless_reality';
  const isAwg      = cfg.protocol === 'amnezia_wg';
  const isTrojan   = cfg.protocol === 'trojan';
  const isNaive    = cfg.protocol === 'naive_proxy';

  // ── Tab buttons ──
  const hasTabs = cfg.client_link || cfg.config_json;
  const tabs = [];
  if (cfg.client_link) tabs.push({ id: 'tab-uri',  label: 'URI / Ссылка', icon: 'fa-link' });
  if (cfg.config_json) tabs.push({ id: 'tab-conf', label: isAwg ? '.conf файл' : 'JSON конфиг', icon: 'fa-file-code' });
  tabs.push({ id: 'tab-qr', label: 'QR-код', icon: 'fa-qrcode' });

  const tabButtons = tabs.map((t, i) =>
    `<button type="button" onclick="switchConfigTab('${t.id}')"
      id="tabBtn-${t.id}"
      class="config-tab-btn px-3 py-1.5 text-xs rounded-lg font-medium transition ${i === 0 ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'}"
    ><i class="fas ${t.icon} mr-1"></i>${t.label}</button>`
  ).join('');

  // ── Details block ──
  let details = '';
  if (isVless) {
    details = `
<div class="space-y-2 text-xs font-mono">
  ${cfgRow('UUID', cfg.uuid)}
  ${cfgRow('Public Key', cfg.reality_public_key)}
  ${cfgRow('Short ID', cfg.reality_short_id)}
  ${cfgRow('SNI', cfg.reality_server_name)}
</div>`;
  } else if (isAwg) {
    details = `
<div class="space-y-2 text-xs font-mono">
  ${cfgRow('Server Public Key', cfg.wg_public_key)}
  ${cfgRow('Client IP', cfg.wg_client_ip)}
  ${cfgRow('Jc (junk packets)', cfg.awg_junk_packet_count)}
  ${cfgRow('Preshared Key', cfg.wg_preshared_key, true)}
</div>`;
  } else if (isTrojan || isNaive) {
    details = `
<div class="space-y-2 text-xs font-mono">
  ${cfgRow('Password', cfg.password, true)}
</div>`;
  }

  // ── URI tab content ──
  const uriContent = cfg.client_link ? `
<div class="space-y-2">
  <div class="flex items-center justify-between">
    <span class="text-gray-500 text-xs">Строка подключения</span>
    <button onclick="copyText('${escapeAttr(cfg.client_link)}')" class="copy-btn text-xs">
      <i class="fas fa-copy mr-1"></i>Копировать
    </button>
  </div>
  <div class="bg-gray-800 rounded-lg p-3 font-mono text-xs text-gray-300 break-all select-all leading-relaxed border border-gray-700 max-h-32 overflow-y-auto">
${escapeHtml(cfg.client_link)}
  </div>
</div>` : '<div class="text-gray-500 text-sm text-center py-4">Ссылка недоступна</div>';

  // ── Config file tab content ──
  const confContent = cfg.config_json ? `
<div class="space-y-2">
  <div class="flex items-center justify-between">
    <span class="text-gray-500 text-xs">${isAwg ? 'WireGuard/AmneziaWG .conf' : 'JSON конфиг'}</span>
    <button onclick="copyText('${escapeAttr(cfg.config_json)}')" class="copy-btn text-xs">
      <i class="fas fa-copy mr-1"></i>Копировать
    </button>
  </div>
  <pre class="bg-gray-800 rounded-lg p-3 font-mono text-xs text-gray-300 leading-relaxed border border-gray-700 max-h-52 overflow-y-auto whitespace-pre-wrap break-all select-all">${escapeHtml(cfg.config_json)}</pre>
</div>` : '';

  // ── QR tab ──
  const qrContent = `
<div class="flex flex-col items-center gap-3 py-2">
  <div id="config-qr-canvas" class="bg-gray-800 rounded-xl p-2 flex items-center justify-center" style="min-width:216px;min-height:216px;"></div>
  <p class="text-gray-500 text-xs text-center">Отсканируйте в v2rayNG, Shadowrocket, Hiddify или AmneziaVPN</p>
</div>`;

  // ── Tips ──
  const tips = {
    vless_reality: 'v2rayNG (Android), Shadowrocket / Hiddify (iOS), Nekoray / Xray (Windows)',
    amnezia_wg:    'AmneziaVPN (Android / iOS / Desktop) — импортируйте .conf файл',
    trojan:        'v2rayNG, Shadowrocket, Hiddify, NekoRay',
    naive_proxy:   'Браузерный прокси или NaiveProxy клиент',
  };

  const firstTabId = tabs[0]?.id || 'tab-qr';

  return `
<div class="space-y-4">
  <!-- Protocol badge + name -->
  <div class="flex items-center gap-2">
    <span class="protocol-badge ${cfg.protocol}">
      <i class="fas ${proto.icon}"></i>${proto.text}
    </span>
    <span class="text-gray-300 text-sm font-medium">${escapeHtml(cfg.name)}</span>
    <span class="text-gray-600 text-xs font-mono">:${cfg.port}</span>
  </div>

  <!-- Details -->
  ${details ? `<div class="bg-gray-800/70 rounded-lg p-3 border border-gray-700">${details}</div>` : ''}

  <!-- Format tabs -->
  ${hasTabs || true ? `
  <div class="flex gap-1.5 flex-wrap">${tabButtons}</div>

  <div id="tab-uri"  class="config-tab-pane">${uriContent}</div>
  <div id="tab-conf" class="config-tab-pane ${!cfg.config_json ? 'hidden' : cfg.client_link ? 'hidden' : ''}">${confContent}</div>
  <div id="tab-qr"   class="config-tab-pane hidden">${qrContent}</div>
  ` : ''}

  <!-- Tips -->
  <div class="bg-gray-800/40 rounded-lg p-3 text-xs text-gray-500">
    <i class="fas fa-mobile-screen text-brand-400 mr-1"></i>
    Клиенты: ${tips[cfg.protocol] || 'любой совместимый VPN-клиент'}
  </div>
</div>`;
}

function cfgRow(label, value, secret = false) {
  if (!value) return '';
  const display = secret
    ? `<span class="blur-sm hover:blur-none transition-all cursor-pointer" title="Нажмите чтобы показать">${escapeHtml(String(value))}</span>`
    : `<span class="select-all truncate max-w-[220px] inline-block align-bottom">${escapeHtml(String(value))}</span>`;
  return `
<div class="flex justify-between items-center gap-2">
  <span class="text-gray-500 flex-shrink-0">${label}:</span>
  ${display}
</div>`;
}

function escapeAttr(str) {
  return String(str || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n');
}

// ─── TAB SWITCHER (config modal) ─────────────────────────────────────────────
function switchConfigTab(tabId) {
  document.querySelectorAll('.config-tab-pane').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.config-tab-btn').forEach(el => {
    el.classList.remove('bg-brand-600', 'text-white');
    el.classList.add('text-gray-400', 'hover:text-white', 'hover:bg-gray-700');
  });
  const pane = document.getElementById(tabId);
  if (pane) pane.classList.remove('hidden');
  const btn = document.getElementById(`tabBtn-${tabId}`);
  if (btn) {
    btn.classList.add('bg-brand-600', 'text-white');
    btn.classList.remove('text-gray-400', 'hover:text-white', 'hover:bg-gray-700');
  }
}

// ─── DELETE ───────────────────────────────────────────────────────────────────
async function confirmDeleteConnection(connId, name) {
  if (!confirm(`Удалить подключение "${name}"?\n\nКонфигурация будет удалена с сервера.`)) return;
  const res = await api.deleteConnection(connId);
  if (res.ok || res.status === 204) {
    toast(`Подключение ${name} удалено`, 'success');
    loadConnectionsGrouped();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

// ─── EXPOSE ───────────────────────────────────────────────────────────────────
window.loadConnectionsGrouped  = loadConnectionsGrouped;
window.toggleConn              = toggleConn;
window.showAddConnectionModal  = showAddConnectionModal;
window.showClientConfig        = showClientConfig;
window.confirmDeleteConnection = confirmDeleteConnection;
window.switchConfigTab         = switchConfigTab;
window.onConnProtocolChange    = onConnProtocolChange;
window.onConnServerChange      = onConnServerChange;

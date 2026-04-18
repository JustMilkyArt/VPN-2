/**
 * Connections tab logic
 */

// ───────────────── LOAD CONNECTIONS ─────────────────
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

// ───────────────── RENDER GROUP ─────────────────
function renderConnectionGroup(group) {
  if (group.connections.length === 0) return '';

  const { server } = group;
  const flag = getFlag(server.country);

  return `
<div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
  <!-- Server header -->
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

  <!-- Connections list -->
  <div class="p-3 space-y-2">
    ${group.connections.map(conn => renderConnectionRow(conn, server)).join('')}
  </div>
</div>
  `;
}

// ───────────────── RENDER CONNECTION ROW ─────────────────
function renderConnectionRow(conn, server) {
  const proto = protocolLabel(conn.protocol);
  const statusClass = {
    active: 'text-green-400 bg-green-900/30',
    inactive: 'text-gray-500 bg-gray-800',
    deploying: 'text-amber-400 bg-amber-900/30',
    error: 'text-red-400 bg-red-900/30',
  }[conn.status] || 'text-gray-500';

  return `
<div class="connection-row flex items-center gap-3" id="conn-row-${conn.id}">
  <!-- Protocol badge -->
  <span class="protocol-badge ${conn.protocol} flex-shrink-0">
    <i class="fas ${proto.icon}"></i>
    ${proto.text}
  </span>

  <!-- Name & port -->
  <div class="flex-1 min-w-0">
    <div class="text-sm font-medium text-white truncate">${conn.name}</div>
    <div class="text-xs text-gray-500 font-mono">:${conn.port}</div>
  </div>

  <!-- Status -->
  <span class="text-xs px-2 py-0.5 rounded ${statusClass} flex-shrink-0">${conn.status}</span>

  <!-- Toggle -->
  <label class="toggle-switch flex-shrink-0">
    <input type="checkbox" ${conn.is_active ? 'checked' : ''} onchange="toggleConn(${conn.id}, this.checked)">
    <span class="toggle-slider"></span>
  </label>

  <!-- Actions -->
  <div class="flex items-center gap-1 flex-shrink-0">
    <button onclick="showClientConfig(${conn.id})" class="action-btn" title="Конфигурация клиента">
      <i class="fas fa-key"></i>
    </button>
    <button onclick="confirmDeleteConnection(${conn.id}, '${conn.name}')" class="action-btn danger" title="Удалить">
      <i class="fas fa-trash"></i>
    </button>
  </div>
</div>
  `;
}

// ───────────────── TOGGLE CONNECTION ─────────────────
async function toggleConn(connId, active) {
  const res = await api.toggleConnection(connId, active);
  if (res.ok) {
    toast(`Подключение ${active ? 'включено' : 'отключено'}`, 'success', 2000);
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
    loadConnectionsGrouped();
  }
}

// ───────────────── ADD CONNECTION MODAL ─────────────────
async function showAddConnectionModal() {
  document.getElementById('add-connection-form').reset();
  document.getElementById('add-connection-error').classList.add('hidden');
  document.getElementById('add-connection-progress').classList.add('hidden');
  document.getElementById('conn-exit-server-block').classList.add('hidden');
  document.getElementById('conn-sni-block').classList.add('hidden');

  // Load servers into dropdowns
  const res = await api.getServers();
  if (!res.ok) {
    toast('Не удалось загрузить серверы', 'error');
    return;
  }

  const servers = res.data.filter(s => s.is_active);
  const select = document.getElementById('conn-server-select');
  const exitSelect = document.getElementById('conn-exit-select');

  select.innerHTML = '<option value="">— Выберите сервер —</option>' +
    servers.map(s => `<option value="${s.id}">${getFlag(s.country)} ${s.name} (${s.ip}) — ${s.role}</option>`).join('');

  const euServers = servers.filter(s => s.role === 'EU' || s.role === 'MIXED');
  exitSelect.innerHTML = '<option value="">— Прямой выход —</option>' +
    euServers.map(s => `<option value="${s.id}">${getFlag(s.country)} ${s.name} (${s.ip})</option>`).join('');

  openModal('modal-add-connection');
}

// Show exit server block for RU role
document.getElementById('conn-server-select').addEventListener('change', function() {
  // Will be set up after DOM loads
});
document.getElementById('conn-protocol-select').addEventListener('change', function() {
  const proto = this.value;
  const exitBlock = document.getElementById('conn-exit-server-block');
  const sniBlock = document.getElementById('conn-sni-block');

  // Show exit server selection for all protocols (chain routing)
  exitBlock.classList.toggle('hidden', !proto);
  // Show SNI only for VLESS+Reality
  sniBlock.classList.toggle('hidden', proto !== 'vless_reality');
});

document.getElementById('add-connection-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  const data = {};

  for (const [k, v] of formData.entries()) {
    if (v !== '') data[k] = v;
  }

  if (!data.server_id) { toast('Выберите сервер', 'error'); return; }
  if (!data.protocol) { toast('Выберите протокол', 'error'); return; }

  data.server_id = parseInt(data.server_id);
  if (data.exit_server_id) data.exit_server_id = parseInt(data.exit_server_id);

  const submitBtn = form.querySelector('[type=submit]');
  const progressEl = document.getElementById('add-connection-progress');
  const errorEl = document.getElementById('add-connection-error');

  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner"></span> Деплой...';
  progressEl.classList.remove('hidden');
  errorEl.classList.add('hidden');

  const res = await api.createConnection(data);

  submitBtn.disabled = false;
  submitBtn.innerHTML = '<i class="fas fa-rocket text-xs"></i> Создать и задеплоить';
  progressEl.classList.add('hidden');

  if (res.ok) {
    closeModal('modal-add-connection');
    const conn = res.data;
    toast(
      conn.status === 'active'
        ? `✓ Подключение "${conn.name}" задеплоено на порту ${conn.port}`
        : `⚠ Подключение создано, но деплой завершился с ошибкой`,
      conn.status === 'active' ? 'success' : 'error',
      6000
    );
    loadConnectionsGrouped();
  } else {
    errorEl.textContent = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
    errorEl.classList.remove('hidden');
  }
});

// ───────────────── CLIENT CONFIG ─────────────────
async function showClientConfig(connId) {
  openModal('modal-client-config');
  const content = document.getElementById('client-config-content');
  content.innerHTML = '<div class="flex justify-center py-4"><span class="spinner"></span></div>';

  const res = await api.getClientConfig(connId);
  if (!res.ok) {
    content.innerHTML = `<div class="text-red-400 text-sm">Ошибка: ${res.error}</div>`;
    return;
  }

  const cfg = res.data;
  const proto = protocolLabel(cfg.protocol);

  let details = '';
  if (cfg.protocol === 'vless_reality') {
    details = `
<div class="space-y-2 text-xs font-mono">
  <div class="flex justify-between items-center">
    <span class="text-gray-500">UUID:</span>
    <span class="text-gray-300 select-all truncate max-w-[200px]">${cfg.uuid || '—'}</span>
  </div>
  <div class="flex justify-between items-center">
    <span class="text-gray-500">Public Key:</span>
    <span class="text-gray-300 select-all truncate max-w-[200px]">${cfg.reality_public_key || '—'}</span>
  </div>
  <div class="flex justify-between items-center">
    <span class="text-gray-500">Short ID:</span>
    <span class="text-gray-300 select-all">${cfg.reality_short_id || '—'}</span>
  </div>
  <div class="flex justify-between items-center">
    <span class="text-gray-500">SNI:</span>
    <span class="text-gray-300">${cfg.reality_server_name || '—'}</span>
  </div>
</div>`;
  } else if (cfg.protocol === 'trojan' || cfg.protocol === 'naive_proxy') {
    details = `
<div class="space-y-2 text-xs font-mono">
  <div class="flex justify-between items-center">
    <span class="text-gray-500">Password:</span>
    <span class="text-gray-300 select-all truncate max-w-[200px]">${cfg.password || '—'}</span>
  </div>
</div>`;
  }

  const clientLink = cfg.client_link || '';
  const hasLink = clientLink && clientLink.length > 0;

  content.innerHTML = `
<div class="space-y-4">
  <!-- Protocol info -->
  <div class="flex items-center gap-2">
    <span class="protocol-badge ${cfg.protocol}">
      <i class="fas ${proto.icon}"></i> ${proto.text}
    </span>
    <span class="text-gray-400 text-sm">${cfg.name}</span>
    <span class="text-gray-600 text-xs font-mono">:${cfg.port}</span>
  </div>

  <!-- Details -->
  ${details ? `<div class="bg-gray-800 rounded-lg p-3">${details}</div>` : ''}

  <!-- Client link -->
  ${hasLink ? `
  <div>
    <div class="flex items-center justify-between mb-1.5">
      <span class="text-gray-400 text-xs font-semibold uppercase tracking-wider">Строка подключения</span>
      <button id="copy-link-btn" onclick="copyText('${clientLink.replace(/'/g, "\\'")}', this)" class="copy-btn">
        Копировать
      </button>
    </div>
    <div class="bg-gray-800 rounded-lg p-3 font-mono text-xs text-gray-300 break-all select-all leading-relaxed">
${clientLink}
    </div>
  </div>
  ` : `
  <div class="bg-amber-900/30 border border-amber-800 rounded-lg p-3 text-amber-300 text-xs">
    <i class="fas fa-triangle-exclamation mr-1"></i>
    Строка подключения ещё не сгенерирована. Проверьте статус деплоя.
  </div>
  `}

  <!-- Tips -->
  <div class="bg-gray-800/50 rounded-lg p-3 text-xs text-gray-500 space-y-1">
    <div><i class="fas fa-circle-info text-brand-400 mr-1"></i>Используйте в клиентах: v2rayNG, Shadowrocket, Nekoray, Hiddify</div>
    ${cfg.protocol === 'vless_reality' ? '<div><i class="fas fa-shield-halved text-green-400 mr-1"></i>VLESS+Reality — максимальная защита от DPI и блокировок</div>' : ''}
  </div>
</div>
  `;
}

// ───────────────── DELETE CONNECTION ─────────────────
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

// Expose globally
window.loadConnectionsGrouped = loadConnectionsGrouped;
window.toggleConn = toggleConn;
window.showAddConnectionModal = showAddConnectionModal;
window.showClientConfig = showClientConfig;
window.confirmDeleteConnection = confirmDeleteConnection;

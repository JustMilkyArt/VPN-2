/**
 * Servers tab logic
 */

let serversData = [];

// ───────────────── LOAD SERVERS ─────────────────
async function loadServers() {
  const grid = document.getElementById('servers-grid');
  const empty = document.getElementById('servers-empty');
  grid.innerHTML = `<div class="col-span-full flex justify-center py-8"><span class="spinner"></span></div>`;

  const res = await api.getServers();
  if (!res.ok) {
    grid.innerHTML = `<div class="col-span-full text-center text-red-400 py-8">
      <i class="fas fa-circle-exclamation mr-2"></i>Ошибка загрузки: ${res.error}
    </div>`;
    return;
  }

  serversData = res.data;

  if (serversData.length === 0) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }

  empty.classList.add('hidden');
  grid.innerHTML = serversData.map(renderServerCard).join('');
}

// ───────────────── SERVER CARD ─────────────────
function renderServerCard(server) {
  const flag = getFlag(server.country);
  const services = [];
  if (server.xray_installed) services.push('<span class="text-xs bg-indigo-900/50 text-indigo-300 border border-indigo-800 px-2 py-0.5 rounded">Xray</span>');
  if (server.naiveproxy_installed) services.push('<span class="text-xs bg-green-900/50 text-green-300 border border-green-800 px-2 py-0.5 rounded">NaiveProxy</span>');
  if (server.trojan_installed) services.push('<span class="text-xs bg-red-900/50 text-red-300 border border-red-800 px-2 py-0.5 rounded">Trojan</span>');
  if (server.warp_installed) services.push('<span class="text-xs bg-orange-900/50 text-orange-300 border border-orange-800 px-2 py-0.5 rounded">WARP</span>');

  return `
<div class="server-card" id="server-card-${server.id}">
  <!-- Header -->
  <div class="flex items-start justify-between mb-3">
    <div class="flex items-center gap-2.5">
      <div class="text-2xl leading-none">${flag}</div>
      <div>
        <div class="font-semibold text-white text-sm leading-tight">${server.name}</div>
        <div class="text-gray-500 text-xs mt-0.5 font-mono">${server.ip}</div>
      </div>
    </div>
    <div class="flex items-center gap-1.5">
      ${roleLabel(server.role)}
      ${statusDot(server.status)}
    </div>
  </div>

  <!-- Status row -->
  <div class="flex items-center gap-2 text-xs mb-3">
    ${statusText(server.status)}
    <span class="text-gray-700">·</span>
    <span class="text-gray-500">SSH :${server.ssh_port}</span>
    ${server.domain ? `<span class="text-gray-700">·</span><span class="text-gray-500 truncate max-w-[120px]">${server.domain}</span>` : ''}
  </div>

  <!-- Services badges -->
  ${services.length > 0 ? `<div class="flex flex-wrap gap-1 mb-3">${services.join('')}</div>` : 
    '<div class="mb-3 text-xs text-gray-600 italic">Сервисы не установлены</div>'}

  <!-- Active toggle -->
  <div class="flex items-center justify-between border-t border-gray-800 pt-3 mt-3">
    <label class="flex items-center gap-2 cursor-pointer">
      <label class="toggle-switch">
        <input type="checkbox" ${server.is_active ? 'checked' : ''} onchange="toggleServer(${server.id}, this.checked)">
        <span class="toggle-slider"></span>
      </label>
      <span class="text-xs text-gray-400">${server.is_active ? 'Включён' : 'Отключён'}</span>
    </label>

    <!-- Action buttons -->
    <div class="flex items-center gap-1">
      <button onclick="pingServer(${server.id})" class="action-btn" title="Проверить связь">
        <i class="fas fa-satellite-dish"></i>
      </button>
      <button onclick="showServerDetail(${server.id})" class="action-btn" title="Детали">
        <i class="fas fa-circle-info"></i>
      </button>
      <button onclick="showInstallModal(${server.id})" class="action-btn success" title="Установить стек">
        <i class="fas fa-download"></i>
      </button>
      <button onclick="confirmDeleteServer(${server.id}, '${server.name}')" class="action-btn danger" title="Удалить">
        <i class="fas fa-trash"></i>
      </button>
    </div>
  </div>
</div>
  `;
}

// ───────────────── TOGGLE SERVER ─────────────────
async function toggleServer(id, active) {
  const res = await api.updateServer(id, { is_active: active });
  if (res.ok) {
    toast(`Сервер ${active ? 'включён' : 'отключён'}`, 'success');
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
    loadServers();
  }
}

// ───────────────── PING SERVER ─────────────────
async function pingServer(serverId) {
  toast('Проверяю соединение...', 'info', 3000);
  const res = await api.pingServer(serverId);
  if (res.ok) {
    const { reachable, message, status } = res.data;
    toast(
      reachable ? `✓ Сервер доступен (${status})` : `✗ Недоступен: ${message}`,
      reachable ? 'success' : 'error',
      5000
    );
    loadServers();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

// ───────────────── CHECK ALL ─────────────────
async function checkAllServers() {
  const btn = document.getElementById('check-all-btn');
  const original = btn.innerHTML;
  btn.innerHTML = '<span class="spinner"></span> Проверяю...';
  btn.disabled = true;

  const res = await api.checkAllServers();
  btn.innerHTML = original;
  btn.disabled = false;

  if (res.ok) {
    const results = res.data;
    const online = Object.values(results).filter(s => s.status === 'online').length;
    const total = Object.values(results).length;
    toast(`Проверено: ${online}/${total} онлайн`, online === total ? 'success' : 'info');
    loadServers();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

// ───────────────── ADD SERVER MODAL ─────────────────
function toggleServerAdvanced() {
  const fields = document.getElementById('server-advanced-fields');
  const icon = document.getElementById('server-adv-icon');
  const isHidden = fields.classList.contains('hidden');
  if (isHidden) {
    fields.classList.remove('hidden');
    icon.classList.add('rotate-90');
  } else {
    fields.classList.add('hidden');
    icon.classList.remove('rotate-90');
  }
}

function showAddServerModal() {
  document.getElementById('add-server-form').reset();
  document.getElementById('add-server-error').classList.add('hidden');
  // Reset advanced fields to defaults and hide
  const fields = document.getElementById('server-advanced-fields');
  const icon = document.getElementById('server-adv-icon');
  fields.classList.add('hidden');
  icon.classList.remove('rotate-90');
  // Restore defaults
  const form = document.getElementById('add-server-form');
  form.querySelector('[name=ssh_user]').value = 'root';
  form.querySelector('[name=ssh_port]').value = '22';
  openModal('modal-add-server');
}

document.getElementById('add-server-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form).entries());

  // Type coercions
  data.ssh_port = parseInt(data.ssh_port) || 22;
  if (!data.ssh_key) delete data.ssh_key;
  if (!data.ssh_password) delete data.ssh_password;
  if (!data.domain) delete data.domain;

  const submitBtn = form.querySelector('[type=submit]');
  submitBtn.innerHTML = '<span class="spinner"></span> Добавление...';
  submitBtn.disabled = true;

  const res = await api.createServer(data);
  submitBtn.innerHTML = '<i class="fas fa-plus text-xs"></i> Добавить';
  submitBtn.disabled = false;

  if (res.ok) {
    closeModal('modal-add-server');
    toast(`Сервер ${res.data.name} добавлен`, 'success');
    loadServers();
  } else {
    const errEl = document.getElementById('add-server-error');
    errEl.textContent = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
    errEl.classList.remove('hidden');
  }
});

// ───────────────── SERVER DETAIL ─────────────────
async function showServerDetail(serverId) {
  openModal('modal-server-detail');
  const content = document.getElementById('server-detail-content');
  const title = document.getElementById('server-detail-title');
  content.innerHTML = '<div class="flex justify-center py-8"><span class="spinner"></span></div>';

  const server = serversData.find(s => s.id === serverId);
  if (!server) return;

  title.innerHTML = `<i class="fas fa-server text-brand-400"></i> ${server.name}`;

  // Get system info
  const infoRes = await api.serverInfo(serverId);
  const info = infoRes.ok ? infoRes.data.system_info : {};

  content.innerHTML = `
<div class="space-y-5">
  <!-- Basic Info -->
  <div class="grid grid-cols-2 gap-3 text-sm">
    <div>
      <div class="text-gray-500 text-xs mb-1">IP адрес</div>
      <div class="font-mono text-white text-sm">${server.ip}</div>
    </div>
    <div>
      <div class="text-gray-500 text-xs mb-1">SSH пользователь</div>
      <div class="font-mono text-white text-sm">${server.ssh_user}:${server.ssh_port}</div>
    </div>
    <div>
      <div class="text-gray-500 text-xs mb-1">Страна</div>
      <div>${getFlag(server.country)} ${server.country}</div>
    </div>
    <div>
      <div class="text-gray-500 text-xs mb-1">Роль</div>
      <div>${roleLabel(server.role)}</div>
    </div>
    ${server.domain ? `<div class="col-span-2">
      <div class="text-gray-500 text-xs mb-1">Домен</div>
      <div class="font-mono text-white text-sm">${server.domain}</div>
    </div>` : ''}
  </div>

  <!-- System info -->
  ${Object.keys(info).length > 0 ? `
  <div class="bg-gray-800 rounded-lg p-3">
    <div class="text-gray-400 text-xs font-semibold mb-2 uppercase tracking-wider">Система</div>
    <div class="grid grid-cols-2 gap-2 text-xs">
      ${info.os ? `<div><span class="text-gray-500">ОС:</span> <span class="text-gray-300">${info.os}</span></div>` : ''}
      ${info.cpu_cores ? `<div><span class="text-gray-500">CPU:</span> <span class="text-gray-300">${info.cpu_cores} ядер</span></div>` : ''}
      ${info.memory ? `<div><span class="text-gray-500">RAM:</span> <span class="text-gray-300">${info.memory} MB</span></div>` : ''}
      ${info.uptime ? `<div><span class="text-gray-500">Uptime:</span> <span class="text-gray-300">${info.uptime}</span></div>` : ''}
    </div>
  </div>` : ''}

  <!-- Installed services -->
  <div>
    <div class="text-gray-400 text-xs font-semibold mb-2 uppercase tracking-wider">Сервисы</div>
    <div class="grid grid-cols-2 gap-2 text-xs">
      ${renderServiceBadge('Xray-core', server.xray_installed)}
      ${renderServiceBadge('NaiveProxy', server.naiveproxy_installed)}
      ${renderServiceBadge('Trojan', server.trojan_installed)}
      ${renderServiceBadge('WARP', server.warp_installed)}
    </div>
  </div>

  <!-- Actions -->
  <div class="flex flex-wrap gap-2 pt-2 border-t border-gray-800">
    <button onclick="pingServer(${serverId})" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-satellite-dish"></i> Пинг
    </button>
    <button onclick="restartServerServices(${serverId})" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-rotate"></i> Restart
    </button>
    <button onclick="redeployServerConfig(${serverId})" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-upload"></i> Redeploy
    </button>
    <button onclick="showInstallModal(${serverId})" class="px-3 py-2 bg-green-900/50 hover:bg-green-900 border border-green-800 rounded-lg text-xs text-green-300 transition flex items-center gap-1.5">
      <i class="fas fa-download"></i> Установить стек
    </button>
    <button onclick="confirmDeleteServer(${serverId}, '${server.name}'); closeModal('modal-server-detail')" 
      class="px-3 py-2 bg-red-900/50 hover:bg-red-900 border border-red-800 rounded-lg text-xs text-red-300 transition flex items-center gap-1.5">
      <i class="fas fa-trash"></i> Удалить
    </button>
  </div>
</div>
  `;
}

function renderServiceBadge(name, installed) {
  return `<div class="flex items-center gap-1.5 p-2 rounded ${installed ? 'bg-green-900/30' : 'bg-gray-800'}">
    <i class="fas ${installed ? 'fa-circle-check text-green-400' : 'fa-circle-xmark text-gray-600'} text-xs"></i>
    <span class="${installed ? 'text-gray-300' : 'text-gray-500'}">${name}</span>
  </div>`;
}

// ───────────────── INSTALL MODAL ─────────────────
function showInstallModal(serverId) {
  document.getElementById('install-server-id').value = serverId;
  document.getElementById('install-output').classList.add('hidden');
  document.getElementById('install-output').textContent = '';
  openModal('modal-install-stack');
}

async function confirmInstallStack() {
  const serverId = document.getElementById('install-server-id').value;
  const installXray = document.getElementById('install-xray').checked;
  const installWarp = document.getElementById('install-warp').checked;

  const outputEl = document.getElementById('install-output');
  outputEl.classList.remove('hidden');
  outputEl.textContent = 'Установка... это может занять 2-5 минут...';

  const res = await api.installStack(serverId, {
    install_xray: installXray,
    install_naiveproxy: false,
    install_trojan: false,
    install_warp: installWarp,
  });

  if (res.ok) {
    const results = res.data.results;
    let output = '';
    for (const [svc, r] of Object.entries(results)) {
      output += `[${r.success ? 'OK' : 'ERR'}] ${svc}: ${r.message}\n`;
    }
    outputEl.textContent = output || 'Готово';
    toast('Установка завершена', 'success');
    loadServers();
  } else {
    outputEl.textContent = `Ошибка: ${res.error}`;
    toast(`Ошибка установки: ${res.error}`, 'error');
  }
}

// ───────────────── SERVER ACTIONS ─────────────────
async function restartServerServices(serverId) {
  toast('Перезапуск сервисов...', 'info', 3000);
  const res = await api.restartServices(serverId);
  if (res.ok) {
    toast(`Сервисы перезапущены: ${res.data.message}`, 'success', 5000);
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

async function redeployServerConfig(serverId) {
  toast('Redeploy конфигураций...', 'info', 3000);
  const res = await api.redeployServer(serverId);
  if (res.ok) {
    toast(res.data.message, 'success');
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

// ───────────────── DELETE SERVER ─────────────────
async function confirmDeleteServer(serverId, name) {
  if (!confirm(`Удалить сервер "${name}"?\n\nВсе подключения этого сервера также будут удалены.`)) return;

  const res = await api.deleteServer(serverId);
  if (res.ok || res.status === 204) {
    toast(`Сервер ${name} удалён`, 'success');
    loadServers();
  } else {
    toast(`Ошибка удаления: ${res.error}`, 'error');
  }
}

// Expose globally
window.toggleServerAdvanced = toggleServerAdvanced;
window.loadServers = loadServers;
window.toggleServer = toggleServer;
window.pingServer = pingServer;
window.checkAllServers = checkAllServers;
window.showAddServerModal = showAddServerModal;
window.showServerDetail = showServerDetail;
window.showInstallModal = showInstallModal;
window.confirmInstallStack = confirmInstallStack;
window.confirmDeleteServer = confirmDeleteServer;
window.restartServerServices = restartServerServices;
window.redeployServerConfig = redeployServerConfig;

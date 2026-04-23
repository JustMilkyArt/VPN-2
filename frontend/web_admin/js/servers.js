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
  if (server.xray_installed)       services.push('<span class="text-xs bg-indigo-900/50 text-indigo-300 border border-indigo-800 px-2 py-0.5 rounded">Xray</span>');
  if (server.naiveproxy_installed) services.push('<span class="text-xs bg-green-900/50 text-green-300 border border-green-800 px-2 py-0.5 rounded">NaiveProxy</span>');
  if (server.awg_installed)        services.push('<span class="text-xs bg-purple-900/50 text-purple-300 border border-purple-800 px-2 py-0.5 rounded">AmneziaWG</span>');
  if (server.warp_installed)       services.push('<span class="text-xs bg-orange-900/50 text-orange-300 border border-orange-800 px-2 py-0.5 rounded">WARP</span>');

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
    ${server.domain ? `<span class="text-gray-700">·</span><span class="text-gray-500 truncate max-w-[120px]">${server.domain}</span>` : ''}
  </div>

  <!-- Services badges -->
  ${services.length > 0
    ? `<div class="flex flex-wrap gap-1 mb-3">${services.join('')}</div>`
    : '<div class="mb-3 text-xs text-gray-600 italic">Сервисы не установлены</div>'}

  <!-- Action buttons -->
  <div class="flex items-center justify-end gap-1 border-t border-gray-800 pt-3 mt-3">
    <button onclick="pingServer(${server.id})" class="action-btn" title="Пинг">
      <i class="fas fa-satellite-dish"></i>
    </button>
    <button onclick="showServerDetail(${server.id})" class="action-btn" title="Детали">
      <i class="fas fa-circle-info"></i>
    </button>
    <button onclick="showInstallModal(${server.id})" class="action-btn success" title="Установить стек">
      <i class="fas fa-download"></i>
    </button>
    <button onclick="showServerSettings(${server.id})" class="action-btn" title="Настройки">
      <i class="fas fa-gear"></i>
    </button>
    <button onclick="confirmDeleteServer(${server.id}, '${server.name}')" class="action-btn danger" title="Удалить">
      <i class="fas fa-trash"></i>
    </button>
  </div>
</div>
  `;
}

// ───────────────── PING SERVER ─────────────────
async function pingServer(serverId) {
  toast('Проверяю соединение...', 'info', 3000);
  const res = await api.pingServer(serverId);
  if (res.ok) {
    const { reachable, message, latency_ms } = res.data;
    const latencyStr = latency_ms !== null ? ` — ${latency_ms} мс` : '';
    toast(
      reachable
        ? `✓ Сервер доступен${latencyStr}`
        : `✗ Недоступен: ${message}`,
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

function selectRole(role) {
  // Update radio inputs
  document.querySelector('#add-server-form [name=role][value=EU]').checked = (role === 'EU');
  document.querySelector('#add-server-form [name=role][value=RU]').checked = (role === 'RU');
  // Update card styles
  document.getElementById('role-card-eu').classList.toggle('role-card-active', role === 'EU');
  document.getElementById('role-card-ru').classList.toggle('role-card-active', role === 'RU');
}

function showAddServerModal() {
  document.getElementById('add-server-form').reset();
  document.getElementById('add-server-error').classList.add('hidden');
  document.getElementById('add-server-country-flag').textContent = '';
  document.getElementById('add-server-role-hint').textContent = '';
  // Reset SSH defaults
  document.querySelector('#add-server-form [name=ssh_user]').value = 'root';
  document.querySelector('#add-server-form [name=ssh_port]').value = '22';
  // Reset role to EU
  selectRole('EU');
  openModal('modal-add-server');
}

// Auto-detect country and role by IP
async function detectIpInfo() {
  const ip = document.getElementById('add-server-ip').value.trim();
  const flagEl = document.getElementById('add-server-country-flag');
  const hintEl = document.getElementById('add-server-role-hint');
  const countrySelect = document.getElementById('add-server-country'); // скрытый select

  if (!ip || !/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)) {
    flagEl.textContent = '';
    hintEl.textContent = '';
    return;
  }

  flagEl.textContent = '⏳';
  hintEl.textContent = 'Определяю страну...';
  hintEl.className = 'text-xs text-gray-500';

  try {
    const resp = await fetch(`https://ip-api.com/json/${ip}?fields=status,country,countryCode`);
    const data = await resp.json();
    if (data.status === 'success') {
      const code = data.countryCode;
      const name = data.country;

      // Заполняем скрытый select страны
      let matched = false;
      for (const opt of countrySelect.options) {
        if (opt.value === code) { opt.selected = true; matched = true; break; }
      }
      if (!matched) countrySelect.value = '??';

      // Автоматически выставляем роль: RU → Entry, всё остальное → Exit
      const role = (code === 'RU') ? 'RU' : 'EU';
      selectRole(role);

      flagEl.textContent = getFlag(code);
      hintEl.textContent = `${name} · роль автоматически выбрана`;
      hintEl.className = 'text-xs ' + (role === 'RU' ? 'text-orange-400' : 'text-green-400');
    } else {
      flagEl.textContent = '🌍';
      hintEl.textContent = 'Страна не определена — выберите роль вручную';
      hintEl.className = 'text-xs text-gray-500';
    }
  } catch {
    flagEl.textContent = '';
    hintEl.textContent = 'Не удалось определить страну';
    hintEl.className = 'text-xs text-red-400';
  }
}

document.getElementById('add-server-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form).entries());

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
      <div class="text-gray-500 text-xs mb-1">SSH</div>
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
      ${info.os       ? `<div><span class="text-gray-500">ОС:</span> <span class="text-gray-300">${info.os}</span></div>` : ''}
      ${info.cpu_cores ? `<div><span class="text-gray-500">CPU:</span> <span class="text-gray-300">${info.cpu_cores} ядер</span></div>` : ''}
      ${info.memory   ? `<div><span class="text-gray-500">RAM:</span> <span class="text-gray-300">${info.memory} MB</span></div>` : ''}
      ${info.uptime   ? `<div><span class="text-gray-500">Uptime:</span> <span class="text-gray-300">${info.uptime}</span></div>` : ''}
    </div>
  </div>` : ''}

  <!-- Installed services -->
  <div>
    <div class="text-gray-400 text-xs font-semibold mb-2 uppercase tracking-wider">Сервисы</div>
    <div class="grid grid-cols-2 gap-2 text-xs">
      ${renderServiceBadge('Xray-core', server.xray_installed)}
      ${renderServiceBadge('NaiveProxy', server.naiveproxy_installed)}
      ${renderServiceBadge('AmneziaWG', server.awg_installed)}
      ${renderServiceBadge('WARP', server.warp_installed)}
    </div>
  </div>

  <!-- Actions -->
  <div class="flex flex-wrap gap-2 pt-2 border-t border-gray-800">
    <button onclick="pingServer(${serverId})" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-satellite-dish"></i> Пинг
    </button>
    <button onclick="restartServerServices(${serverId})" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-rotate"></i> Рестарт сервисов
    </button>
    <button onclick="redeployServerConfig(${serverId})" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-upload"></i> Redeploy
    </button>
    <button onclick="showInstallModal(${serverId})" class="px-3 py-2 bg-green-900/50 hover:bg-green-900 border border-green-800 rounded-lg text-xs text-green-300 transition flex items-center gap-1.5">
      <i class="fas fa-download"></i> Установить стек
    </button>
    <button onclick="closeModal('modal-server-detail'); showServerSettings(${serverId})"
      class="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300 transition flex items-center gap-1.5">
      <i class="fas fa-gear"></i> Настройки
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
  const installXray    = document.getElementById('install-xray').checked;
  const installNaive   = document.getElementById('install-naive').checked;
  const installAwg     = document.getElementById('install-awg').checked;
  const installWarp    = document.getElementById('install-warp').checked;

  const outputEl = document.getElementById('install-output');
  outputEl.classList.remove('hidden');
  outputEl.textContent = 'Установка... это может занять 2–5 минут...';

  const res = await api.installStack(serverId, {
    install_xray:       installXray,
    install_naiveproxy: installNaive,
    install_awg:        installAwg,
    install_warp:       installWarp,
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

// ───────────────── SERVER SETTINGS ─────────────────
function showServerSettings(serverId) {
  const server = serversData.find(s => s.id === serverId);
  if (!server) return;

  document.getElementById('settings-server-id').value = serverId;
  document.getElementById('settings-server-title').textContent = server.name;

  // Fill edit fields
  document.getElementById('settings-name').value    = server.name;
  document.getElementById('settings-domain').value  = server.domain || '';
  document.getElementById('settings-notes').value   = server.notes || '';

  // Uninstall checkboxes — only show installed ones
  document.getElementById('uninst-xray-wrap').classList.toggle('hidden', !server.xray_installed);
  document.getElementById('uninst-naive-wrap').classList.toggle('hidden', !server.naiveproxy_installed);
  document.getElementById('uninst-awg-wrap').classList.toggle('hidden', !server.awg_installed);
  document.getElementById('uninst-warp-wrap').classList.toggle('hidden', !server.warp_installed);
  document.getElementById('uninst-xray').checked = false;
  document.getElementById('uninst-naive').checked = false;
  document.getElementById('uninst-awg').checked   = false;
  document.getElementById('uninst-warp').checked  = false;

  // Clear password/key fields
  document.getElementById('settings-new-password').value  = '';
  document.getElementById('settings-ssh-pubkey').value    = '';
  document.getElementById('settings-action-msg').textContent = '';

  openModal('modal-server-settings');
}

async function saveServerInfo() {
  const serverId = document.getElementById('settings-server-id').value;
  const name   = document.getElementById('settings-name').value.trim();
  const domain = document.getElementById('settings-domain').value.trim();
  const notes  = document.getElementById('settings-notes').value.trim();

  const res = await api.updateServer(serverId, {
    name:   name || undefined,
    domain: domain || undefined,
    notes:  notes || undefined,
  });
  if (res.ok) {
    toast('Настройки сохранены', 'success');
    loadServers();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

async function rebootServerAction() {
  const serverId = document.getElementById('settings-server-id').value;
  const server   = serversData.find(s => s.id === parseInt(serverId));
  if (!confirm(`Перезагрузить сервер "${server?.name}"?\n\nСервер будет недоступен ~30–60 секунд.`)) return;

  toast('Отправляю команду перезагрузки...', 'info', 3000);
  const res = await api.rebootServer(serverId);
  if (res.ok) {
    toast(`✓ ${res.data.message}`, 'success', 6000);
    loadServers();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

async function changeServerPasswordAction() {
  const serverId    = document.getElementById('settings-server-id').value;
  const newPassword = document.getElementById('settings-new-password').value;

  if (!newPassword || newPassword.length < 8) {
    toast('Пароль должен быть не менее 8 символов', 'error');
    return;
  }

  toast('Меняю пароль...', 'info', 3000);
  const res = await api.changeServerPassword(serverId, newPassword);
  if (res.ok) {
    document.getElementById('settings-new-password').value = '';
    toast(`✓ ${res.data.message}`, 'success');
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

async function addServerSSHKeyAction() {
  const serverId = document.getElementById('settings-server-id').value;
  const pubKey   = document.getElementById('settings-ssh-pubkey').value.trim();

  if (!pubKey || !pubKey.startsWith('ssh-')) {
    toast('Введите корректный публичный SSH-ключ (начинается с ssh-rsa или ssh-ed25519)', 'error');
    return;
  }

  toast('Добавляю SSH-ключ...', 'info', 3000);
  const res = await api.addServerSSHKey(serverId, pubKey);
  if (res.ok) {
    document.getElementById('settings-ssh-pubkey').value = '';
    toast(`✓ ${res.data.message}`, 'success');
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

async function uninstallStackAction() {
  const serverId = document.getElementById('settings-server-id').value;
  const xray  = document.getElementById('uninst-xray').checked;
  const naive = document.getElementById('uninst-naive').checked;
  const awg   = document.getElementById('uninst-awg').checked;
  const warp  = document.getElementById('uninst-warp').checked;

  if (!xray && !naive && !awg && !warp) {
    toast('Выберите хотя бы один сервис для удаления', 'error');
    return;
  }

  const names = [xray && 'Xray', naive && 'NaiveProxy', awg && 'AmneziaWG', warp && 'WARP'].filter(Boolean);
  if (!confirm(`Удалить ${names.join(', ')} с сервера?\n\nВсе активные подключения через эти сервисы перестанут работать.`)) return;

  toast('Удаляю сервисы...', 'info', 5000);
  const res = await api.uninstallStack(serverId, {
    uninstall_xray:       xray,
    uninstall_naiveproxy: naive,
    uninstall_awg:        awg,
    uninstall_warp:       warp,
  });

  if (res.ok) {
    toast(`✓ ${res.data.message}`, 'success');
    closeModal('modal-server-settings');
    loadServers();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
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
window.selectRole              = selectRole;
window.toggleServerAdvanced    = toggleServerAdvanced;
window.detectIpInfo            = detectIpInfo;
window.loadServers             = loadServers;
window.pingServer              = pingServer;
window.checkAllServers         = checkAllServers;
window.showAddServerModal      = showAddServerModal;
window.showServerDetail        = showServerDetail;
window.showInstallModal        = showInstallModal;
window.confirmInstallStack     = confirmInstallStack;
window.showServerSettings      = showServerSettings;
window.saveServerInfo          = saveServerInfo;
window.rebootServerAction      = rebootServerAction;
window.changeServerPasswordAction = changeServerPasswordAction;
window.addServerSSHKeyAction   = addServerSSHKeyAction;
window.uninstallStackAction    = uninstallStackAction;
window.confirmDeleteServer     = confirmDeleteServer;
window.restartServerServices   = restartServerServices;
window.redeployServerConfig    = redeployServerConfig;

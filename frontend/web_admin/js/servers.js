/**
 * Servers tab logic
 */

let serversData = [];

// ───────────────── LOAD SERVERS ─────────────────
async function loadServers() {
  const container = document.getElementById('servers-grid');
  const empty = document.getElementById('servers-empty');
  container.innerHTML = `<div class="col-span-full flex justify-center py-8"><span class="spinner"></span></div>`;

  const res = await api.getServers();
  if (!res.ok) {
    container.innerHTML = `<div class="col-span-full text-center text-red-400 py-8">
      <i class="fas fa-circle-exclamation mr-2"></i>Ошибка загрузки: ${res.error}
    </div>`;
    return;
  }

  serversData = res.data;

  if (serversData.length === 0) {
    container.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }

  empty.classList.add('hidden');
  renderServerSections(container);

  // Автопинг всех серверов при загрузке
  silentCheckAllServers();

  // Для серверов с неизвестной страной — определяем по IP
  serversData.forEach(server => {
    if (!server.country || server.country === '??') {
      resolveCountryForCard(server.id, server.ip);
    }
  });
}

// ───────────────── RENDER SECTIONS RU / EU ─────────────────
function renderServerSections(container) {
  const eu = serversData.filter(s => s.role === 'EU');
  const ru = serversData.filter(s => s.role === 'RU');

  // RU — слева (первой), EU — справа (второй)
  const sections = [];

  if (ru.length > 0) {
    sections.push(`
    <div class="server-section">
      <div class="server-section-header">
        <svg width="18" height="18" viewBox="0 0 72 72" style="flex-shrink:0;opacity:0.9">
          <clipPath id="rc"><circle cx="36" cy="36" r="34"/></clipPath>
          <rect x="0" y="0" width="72" height="24" fill="#f0f0f0" clip-path="url(#rc)"/>
          <rect x="0" y="24" width="72" height="24" fill="#0039a6" clip-path="url(#rc)"/>
          <rect x="0" y="48" width="72" height="24" fill="#d52b1e" clip-path="url(#rc)"/>
          <circle cx="36" cy="36" r="34" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="1"/>
        </svg>
        <span class="server-section-title">RU Entry</span>
        <span class="server-section-count">${ru.length}</span>
      </div>
      <div class="server-cards-list">
        ${ru.map(renderServerCard).join('')}
      </div>
    </div>`);
  }

  if (eu.length > 0) {
    sections.push(`
    <div class="server-section">
      <div class="server-section-header">
        <svg width="18" height="18" viewBox="0 0 72 72" style="flex-shrink:0;opacity:0.8">
          <circle cx="36" cy="36" r="34" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1.5"/>
          <ellipse cx="36" cy="36" rx="34" ry="13" fill="none" stroke="#60a5fa" stroke-width="0.8" opacity="0.6"/>
          <line x1="2" y1="36" x2="70" y2="36" stroke="#60a5fa" stroke-width="0.8" opacity="0.6"/>
          <ellipse cx="36" cy="36" rx="13" ry="34" fill="none" stroke="#60a5fa" stroke-width="0.8" opacity="0.6"/>
        </svg>
        <span class="server-section-title">EU Exit</span>
        <span class="server-section-count">${eu.length}</span>
      </div>
      <div class="server-cards-list">
        ${eu.map(renderServerCard).join('')}
      </div>
    </div>`);
  }

  // Два блока рядом (если оба есть), иначе один во всю ширину
  if (sections.length === 2) {
    container.innerHTML = `<div class="server-sections-grid">${sections.join('')}</div>`;
  } else {
    container.innerHTML = `<div class="server-sections-single">${sections.join('')}</div>`;
  }
}

// ───────────────── SILENT AUTO-PING ON TAB OPEN ─────────────
async function silentCheckAllServers() {
  for (const server of serversData) {
    try {
      const res = await api.pingServer(server.id);
      if (!res.ok) continue;
      const { reachable, latency_ms } = res.data;
      const newStatus = reachable ? 'online' : 'offline';

      // Обновляем точку и текст статуса на карточке без перерендера
      const dot  = document.getElementById(`status-dot-${server.id}`);
      const txt  = document.getElementById(`status-text-${server.id}`);
      const ping = document.getElementById(`ping-val-${server.id}`);

      if (dot) {
        dot.className = `status-dot ${newStatus}`;
      }
      if (txt) {
        txt.className = reachable ? 'text-green-400 text-xs font-medium' : 'text-red-400 text-xs font-medium';
        txt.textContent = reachable ? 'Online' : 'Offline';
      }
      if (ping && latency_ms !== null) {
        ping.textContent = `пинг: ${latency_ms} ms`;
        ping.style.color = latency_ms < 100 ? '#4ade80' : latency_ms < 300 ? '#facc15' : '#f87171';
        ping.classList.remove('hidden');
      }

      // Обновляем локальный кеш
      server.status = newStatus;
    } catch (_) { /* игнорируем */ }
  }
}

// ───────────────── SERVER CARD ─────────────────
function renderServerCard(server) {
  const flag      = getFlag(server.country);
  const isOnline  = server.status === 'online';
  const isOffline = server.status === 'offline';

  return `
<div class="server-card" id="server-card-${server.id}">

  <!-- Шапка: флаг+название слева, статус справа -->
  <div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;margin-bottom:0.875rem;">

    <!-- Флаг + название -->
    <div style="display:flex;align-items:center;gap:0.625rem;min-width:0;flex:1;">
      <div id="server-flag-${server.id}" style="flex-shrink:0;">${flag}</div>
      <span style="font-weight:600;color:#f9fafb;font-size:0.9rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${server.name}</span>
    </div>

    <!-- Статус справа -->
    <div style="display:flex;align-items:center;gap:0.35rem;flex-shrink:0;">
      <span id="status-dot-${server.id}" class="status-dot ${server.status}"></span>
      <span id="status-text-${server.id}" style="font-size:0.72rem;font-weight:600;color:${isOnline ? '#4ade80' : isOffline ? '#f87171' : '#6b7280'};">${isOnline ? 'Online' : isOffline ? 'Offline' : 'Unknown'}</span>
    </div>

  </div>

  <!-- IP -->
  <div style="margin-bottom:0.25rem;">
    <span style="font-family:monospace;font-size:0.8rem;color:#4b5563;">${server.ip}</span>
  </div>

  <!-- Латентность (появляется после пинга) -->
  <div style="margin-bottom:0.875rem;min-height:1.1rem;">
    <span id="ping-val-${server.id}" class="hidden" style="font-size:0.75rem;font-weight:500;"></span>
  </div>

  <!-- Кнопки -->
  <div style="display:flex;align-items:center;justify-content:flex-end;gap:0.25rem;border-top:1px solid #1f2937;padding-top:0.625rem;">
    <button onclick="pingServer(${server.id})" class="action-btn" title="Пинг">
      <i class="fas fa-satellite-dish"></i>
    </button>
    <button onclick="showServerDetail(${server.id})" class="action-btn" title="Настройки">
      <i class="fas fa-sliders"></i>
    </button>
    <button onclick="confirmDeleteServer(${server.id}, '${server.name}')" class="action-btn danger" title="Удалить">
      <i class="fas fa-trash"></i>
    </button>
  </div>

</div>`;
}

// ───────────────── PING SERVER ─────────────────
async function pingServer(serverId) {
  // Анимируем кнопку пинга
  const card = document.getElementById(`server-card-${serverId}`);
  const btn  = card?.querySelector('[title="Пинг"]');
  if (btn) { btn.innerHTML = '<span class="spinner" style="width:10px;height:10px;"></span>'; btn.disabled = true; }

  const res = await api.pingServer(serverId);

  if (btn) { btn.innerHTML = '<i class="fas fa-satellite-dish"></i>'; btn.disabled = false; }

  if (res.ok) {
    const { reachable, message, latency_ms } = res.data;

    // Обновляем карточку без перерендера
    const dot  = document.getElementById(`status-dot-${serverId}`);
    const txt  = document.getElementById(`status-text-${serverId}`);
    const ping = document.getElementById(`ping-val-${serverId}`);

    if (dot) dot.className = `status-dot ${reachable ? 'online' : 'offline'}`;
    if (txt) {
      txt.style.color  = reachable ? '#4ade80' : '#f87171';
      txt.textContent  = reachable ? 'Online' : 'Offline';
    }
    if (ping) {
      if (latency_ms !== null) {
        ping.textContent = `пинг: ${latency_ms} ms`;
        ping.style.color = latency_ms < 100 ? '#4ade80' : latency_ms < 300 ? '#facc15' : '#f87171';
        ping.classList.remove('hidden');
      }
    }

    const latencyStr = latency_ms !== null ? ` — ${latency_ms} ms` : '';
    toast(
      reachable ? `✓ Доступен${latencyStr}` : `✗ Недоступен: ${message}`,
      reachable ? 'success' : 'error', 4000
    );

    // Обновляем кеш
    const srv = serversData.find(s => s.id === serverId);
    if (srv) srv.status = reachable ? 'online' : 'offline';
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
  document.querySelector('#add-server-form [name=role][value=EU]').checked = (role === 'EU');
  document.querySelector('#add-server-form [name=role][value=RU]').checked = (role === 'RU');

  const euBtn = document.getElementById('role-card-eu');
  const ruBtn = document.getElementById('role-card-ru');

  // Сброс стилей
  const base = 'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.75rem;padding:1.5rem 1rem;border-radius:0.875rem;cursor:pointer;width:100%;transition:all 0.2s;';
  const active = base + 'border:2px solid #6366f1;background:#1e1b4b;box-shadow:0 0 0 2px #6366f1,0 4px 24px rgba(99,102,241,0.35);opacity:1;';
  const dim    = base + 'border:2px solid #374151;background:#111827;opacity:0.4;';

  euBtn.style.cssText = (role === 'EU') ? active : dim;
  ruBtn.style.cssText = (role === 'RU') ? active : dim;

  // Показываем поля формы
  document.getElementById('server-fields').classList.remove('hidden');
}

function showAddServerModal() {
  document.getElementById('add-server-form').reset();
  document.getElementById('add-server-error').classList.add('hidden');
  document.getElementById('add-server-geo').classList.add('hidden');
  document.getElementById('add-server-country').value = '??';
  // Скрываем поля — видны только кнопки выбора роли
  document.getElementById('server-fields').classList.add('hidden');
  // Reset SSH defaults
  document.querySelector('#add-server-form [name=ssh_user]').value = 'root';
  document.querySelector('#add-server-form [name=ssh_port]').value = '22';
  // Hide advanced
  document.getElementById('server-advanced-fields').classList.add('hidden');
  document.getElementById('server-adv-icon').classList.remove('rotate-90');
  // Сбрасываем кнопки роли в нейтральное состояние
  const baseStyle = 'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.75rem;padding:1.5rem 1rem;border-radius:0.875rem;border:2px solid #374151;background:#111827;cursor:pointer;width:100%;transition:all 0.2s;opacity:1;';
  document.getElementById('role-card-eu').style.cssText = baseStyle;
  document.getElementById('role-card-ru').style.cssText = baseStyle;
  document.querySelector('#add-server-form [name=role][value=EU]').checked = false;
  document.querySelector('#add-server-form [name=role][value=RU]').checked = false;
  openModal('modal-add-server');
}

// ───────── Автодетект страны для карточки сервера (если country = '??') ─────────
async function resolveCountryForCard(serverId, ip) {
  try {
    const resp = await fetch(`https://ipwho.is/${ip}`);
    const data = await resp.json();
    if (!data.success || !data.country_code) return;

    const code  = data.country_code.toUpperCase();
    const lower = code.toLowerCase();

    // Обновляем флаг на карточке
    const flagEl = document.getElementById(`server-flag-${serverId}`);
    if (flagEl) {
      flagEl.innerHTML = `<img src="https://flagcdn.com/32x24/${lower}.png" alt="${code}" class="country-flag">`;
    }

    // Сохраняем в БД через API
    await api.updateServer(serverId, { country: code });

    // Обновляем локальный кеш
    const srv = serversData.find(s => s.id === serverId);
    if (srv) srv.country = code;
  } catch (_) { /* тихо игнорируем */ }
}

// Auto-detect country by IP — показываем флаг через flagcdn.com
let _ipDetectTimer = null;
async function detectIpInfo() {
  const ip = document.getElementById('add-server-ip').value.trim();
  const geoEl  = document.getElementById('add-server-geo');
  const flagImg = document.getElementById('add-server-flag-img');
  const geoText = document.getElementById('add-server-geo-text');
  const countryInput = document.getElementById('add-server-country');

  // Дебаунс — запрашиваем только когда IP введён полностью
  clearTimeout(_ipDetectTimer);
  if (!ip || !/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)) {
    geoEl.classList.add('hidden');
    countryInput.value = '??';
    return;
  }

  _ipDetectTimer = setTimeout(async () => {
    geoEl.classList.remove('hidden');
    flagImg.src = '';
    geoText.textContent = 'Определяю страну...';

    try {
      const resp = await fetch(`https://ipwho.is/${ip}`);
      const data = await resp.json();

      if (data.success && data.country_code) {
        const code = data.country_code.toLowerCase();
        const name = data.country;

        countryInput.value = data.country_code.toUpperCase();

        flagImg.src = `https://flagcdn.com/24x18/${code}.png`;
        flagImg.alt = name;
        geoText.textContent = name;
        geoText.className = 'text-xs text-gray-300';
      } else {
        geoEl.classList.add('hidden');
        countryInput.value = '??';
      }
    } catch {
      geoEl.classList.add('hidden');
    }
  }, 600); // ждём 600мс после последнего ввода
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
      <div class="flex items-center gap-2">${getFlag(server.country)}<span class="text-white text-sm">${server.country}</span></div>
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

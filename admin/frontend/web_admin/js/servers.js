/**
 * Servers tab logic
 */

let serversData = [];

// ISO 3166-1 alpha-2 → полное название страны
const ISO_COUNTRY_NAMES = {
  AF:'Афганистан',AL:'Албания',DZ:'Алжир',AD:'Андорра',AO:'Ангола',
  AG:'Антигуа и Барбуда',AR:'Аргентина',AM:'Армения',AU:'Австралия',
  AT:'Австрия',AZ:'Азербайджан',BS:'Багамы',BH:'Бахрейн',BD:'Бангладеш',
  BB:'Барбадос',BY:'Беларусь',BE:'Бельгия',BZ:'Белиз',BJ:'Бенин',
  BT:'Бутан',BO:'Боливия',BA:'Босния и Герцеговина',BW:'Ботсвана',
  BR:'Бразилия',BN:'Бруней',BG:'Болгария',BF:'Буркина-Фасо',BI:'Бурунди',
  CV:'Кабо-Верде',KH:'Камбоджа',CM:'Камерун',CA:'Канада',CF:'ЦАР',
  TD:'Чад',CL:'Чили',CN:'Китай',CO:'Колумбия',KM:'Коморы',
  CD:'ДР Конго',CG:'Конго',CR:'Коста-Рика',HR:'Хорватия',CU:'Куба',
  CY:'Кипр',CZ:'Чехия',DK:'Дания',DJ:'Джибути',DM:'Доминика',
  DO:'Доминиканская Республика',EC:'Эквадор',EG:'Египет',SV:'Сальвадор',
  GQ:'Экватор. Гвинея',ER:'Эритрея',EE:'Эстония',SZ:'Эсватини',
  ET:'Эфиопия',FJ:'Фиджи',FI:'Финляндия',FR:'Франция',GA:'Габон',
  GM:'Гамбия',GE:'Грузия',DE:'Германия',GH:'Гана',GR:'Греция',
  GD:'Гренада',GT:'Гватемала',GN:'Гвинея',GW:'Гвинея-Бисау',
  GY:'Гайана',HT:'Гаити',HN:'Гондурас',HU:'Венгрия',IS:'Исландия',
  IN:'Индия',ID:'Индонезия',IR:'Иран',IQ:'Ирак',IE:'Ирландия',
  IL:'Израиль',IT:'Италия',JM:'Ямайка',JP:'Япония',JO:'Иордания',
  KZ:'Казахстан',KE:'Кения',KI:'Кирибати',KP:'Сев. Корея',KR:'Юж. Корея',
  KW:'Кувейт',KG:'Кыргызстан',LA:'Лаос',LV:'Латвия',LB:'Ливан',
  LS:'Лесото',LR:'Либерия',LY:'Ливия',LI:'Лихтенштейн',LT:'Литва',
  LU:'Люксембург',MG:'Мадагаскар',MW:'Малави',MY:'Малайзия',MV:'Мальдивы',
  ML:'Мали',MT:'Мальта',MH:'Маршалловы о-ва',MR:'Мавритания',MU:'Маврикий',
  MX:'Мексика',FM:'Микронезия',MD:'Молдова',MC:'Монако',MN:'Монголия',
  ME:'Черногория',MA:'Марокко',MZ:'Мозамбик',MM:'Мьянма',NA:'Намибия',
  NR:'Науру',NP:'Непал',NL:'Нидерланды',NZ:'Новая Зеландия',NI:'Никарагуа',
  NE:'Нигер',NG:'Нигерия',MK:'Сев. Македония',NO:'Норвегия',OM:'Оман',
  PK:'Пакистан',PW:'Палау',PA:'Панама',PG:'Папуа — Нов. Гвинея',
  PY:'Парагвай',PE:'Перу',PH:'Филиппины',PL:'Польша',PT:'Португалия',
  QA:'Катар',RO:'Румыния',RU:'Россия',RW:'Руанда',KN:'Сент-Китс и Невис',
  LC:'Сент-Люсия',VC:'Сент-Винсент',WS:'Самоа',SM:'Сан-Марино',
  ST:'Сан-Томе и Принсипи',SA:'Саудовская Аравия',SN:'Сенегал',RS:'Сербия',
  SC:'Сейшелы',SL:'Сьерра-Леоне',SG:'Сингапур',SK:'Словакия',SI:'Словения',
  SB:'Соломоновы о-ва',SO:'Сомали',ZA:'ЮАР',SS:'Юж. Судан',ES:'Испания',
  LK:'Шри-Ланка',SD:'Судан',SR:'Суринам',SE:'Швеция',CH:'Швейцария',
  SY:'Сирия',TW:'Тайвань',TJ:'Таджикистан',TZ:'Танзания',TH:'Таиланд',
  TL:'Тимор-Лесте',TG:'Того',TO:'Тонга',TT:'Тринидад и Тобаго',
  TN:'Тунис',TR:'Турция',TM:'Туркменистан',TV:'Тувалу',UG:'Уганда',
  UA:'Украина',AE:'ОАЭ',GB:'Великобритания',US:'США',UY:'Уругвай',
  UZ:'Узбекистан',VU:'Вануату',VE:'Венесуэла',VN:'Вьетнам',
  YE:'Йемен',ZM:'Замбия',ZW:'Зимбабве',
};

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

  // Статистика подключений для каждого сервера
  serversData.forEach(server => loadConnStats(server.id));

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
      // Не пингуем серверы в процессе настройки
      if (server.setup_status === 'in_progress' || server.status === 'setting_up') continue;

      const res = await api.pingServer(server.id);
      if (!res.ok) continue;
      const { reachable, latency_ms } = res.data;
      const newStatus = reachable ? 'online' : 'offline';

      const dot  = document.getElementById(`status-dot-${server.id}`);
      const txt  = document.getElementById(`status-text-${server.id}`);
      const ping = document.getElementById(`ping-val-${server.id}`);

      if (dot) dot.className = `status-dot ${newStatus}`;
      if (txt) {
        txt.style.color = reachable ? '#4ade80' : '#f87171';
        txt.textContent = reachable ? 'Online' : 'Offline';
      }
      if (ping) {
        if (latency_ms !== null) {
          ping.textContent = `${latency_ms} ms`;
          ping.style.color = latency_ms < 100 ? '#4ade80' : latency_ms < 300 ? '#facc15' : '#f87171';
          ping.classList.remove('hidden');
        } else if (!reachable) {
          ping.textContent = 'недоступен';
          ping.style.color = '#6b7280';
          ping.classList.remove('hidden');
        }
      }

      server.status = newStatus;
    } catch (_) { /* игнорируем */ }
  }
}

// ───────────────── SERVER CARD ─────────────────

/** Возвращает мета-данные для статус-точки Online/Offline/Setting up */
function _getServerStatusMeta(server) {
  const isSettingUp = server.status === 'setting_up' || server.setup_status === 'in_progress';
  if (isSettingUp)               return { color: '#facc15', label: 'Setting up', dot: 'setting_up' };
  if (server.status === 'online') return { color: '#4ade80', label: 'Online',     dot: 'online'    };
  if (server.status === 'offline')return { color: '#f87171', label: 'Offline',    dot: 'offline'   };
  return { color: '#6b7280', label: 'Unknown', dot: '' };
}

/** Возвращает мета-данные для бейджа «Configured / Setting up / Not configured» */
function _getSetupBadgeMeta(server) {
  const s = server.setup_status;
  if (s === 'done')        return { color: '#4ade80', bg: 'rgba(74,222,128,0.12)', label: 'Configured'     };
  if (s === 'in_progress') return { color: '#facc15', bg: 'rgba(250,204,21,0.12)',  label: 'Setting up...'  };
  if (s === 'failed')      return { color: '#f87171', bg: 'rgba(248,113,113,0.12)', label: 'Setup failed'   };
  return                          { color: '#6b7280', bg: 'rgba(107,114,128,0.12)', label: 'Not configured' };
}

function renderServerCard(server) {
  const flag  = getFlag(server.country);
  const sm    = _getServerStatusMeta(server);
  const badge = _getSetupBadgeMeta(server);

  return `
<div class="server-card" id="server-card-${server.id}">

  <!-- Шапка: флаг+название слева, статус справа -->
  <div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;margin-bottom:0.5rem;">

    <!-- Флаг + название -->
    <div style="display:flex;align-items:center;gap:0.625rem;min-width:0;flex:1;">
      <div id="server-flag-${server.id}" style="flex-shrink:0;">${flag}</div>
      <span style="font-weight:600;color:#f9fafb;font-size:0.9rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${server.name}</span>
    </div>

    <!-- Online/Offline точка справа -->
    <div style="display:flex;align-items:center;gap:0.35rem;flex-shrink:0;">
      <span id="status-dot-${server.id}" class="status-dot ${sm.dot}"></span>
      <span id="status-text-${server.id}" style="font-size:0.72rem;font-weight:600;color:${sm.color};">${sm.label}</span>
    </div>

  </div>

  <!-- Бейдж setup-статуса -->
  <div style="margin-bottom:0.625rem;">
    <span id="setup-badge-${server.id}"
      style="display:inline-block;font-size:0.65rem;font-weight:600;padding:1px 7px;border-radius:999px;
             color:${badge.color};background:${badge.bg};border:1px solid ${badge.color}33;">
      ${badge.label}
    </span>
  </div>

  <!-- IP -->
  <div style="margin-bottom:0.25rem;">
    <span style="font-family:monospace;font-size:0.8rem;color:#4b5563;">${server.ip}</span>
  </div>

  <!-- Пинг (появляется после обновления) -->
  <div style="margin-bottom:0.25rem;min-height:1rem;">
    <span id="ping-val-${server.id}" class="hidden" style="font-size:0.72rem;color:#6b7280;"></span>
  </div>

  <!-- Статистика подключений -->
  <div style="margin-bottom:0.625rem;min-height:1rem;">
    <span id="conn-stats-${server.id}" style="font-size:0.72rem;color:#6b7280;"></span>
  </div>

  <!-- Кнопки -->
  <div style="display:flex;align-items:center;justify-content:flex-end;gap:0.25rem;border-top:1px solid #1f2937;padding-top:0.625rem;">
    <button id="update-btn-${server.id}" onclick="pingServer(${server.id})" class="action-btn" title="Обновить статус и пинг">
      <i class="fas fa-arrows-rotate"></i>
    </button>
    <button onclick="showServerSettings(${server.id})" class="action-btn" title="Настройки">
      <i class="fas fa-sliders"></i>
    </button>
    <button onclick="confirmDeleteServer(${server.id}, '${server.name}')" class="action-btn danger" title="Удалить">
      <i class="fas fa-trash"></i>
    </button>
  </div>

</div>`;
}

// ───────────────── CONNECTION STATS ─────────────────
async function loadConnStats(serverId) {
  const el = document.getElementById(`conn-stats-${serverId}`);
  if (!el) return;
  const res = await api.serverStats(serverId);
  if (!res.ok) { el.textContent = ''; return; }
  const { active, total, protocols } = res.data;
  // Строка протоколов: «AWG ×2, Xray ×1»
  const protoStr = Object.entries(protocols)
    .map(([p, n]) => `${p.toUpperCase()}${n > 1 ? ' ×' + n : ''}`)
    .join(', ');
  if (total === 0) {
    el.textContent = 'нет подключений';
    el.style.color = '#4b5563';
  } else {
    el.innerHTML = `<i class="fas fa-users" style="margin-right:3px;"></i>`
      + `<span style="color:${active > 0 ? '#4ade80' : '#6b7280'}">${active} акт.</span>`
      + ` / ${total} всего`
      + (protoStr ? `<span style="color:#4b5563;"> · ${protoStr}</span>` : '');
  }
}

// ───────────────── PING SERVER ─────────────────
async function pingServer(serverId) {
  // Анимируем кнопку обновления
  const btn = document.getElementById(`update-btn-${serverId}`);
  if (btn) { btn.innerHTML = '<span class="spinner" style="width:10px;height:10px;"></span>'; btn.disabled = true; }

  const res = await api.pingServer(serverId);

  if (btn) { btn.innerHTML = '<i class="fas fa-arrows-rotate"></i>'; btn.disabled = false; }

  if (res.ok) {
    const { reachable, latency_ms } = res.data;

    const dot  = document.getElementById(`status-dot-${serverId}`);
    const txt  = document.getElementById(`status-text-${serverId}`);
    const ping = document.getElementById(`ping-val-${serverId}`);

    if (dot) dot.className = `status-dot ${reachable ? 'online' : 'offline'}`;
    if (txt) { txt.style.color = reachable ? '#4ade80' : '#f87171'; txt.textContent = reachable ? 'Online' : 'Offline'; }

    // Показываем пинг сразу
    if (ping) {
      if (latency_ms !== null) {
        ping.textContent = `${latency_ms} ms`;
        ping.style.color = latency_ms < 100 ? '#4ade80' : latency_ms < 300 ? '#facc15' : '#f87171';
        ping.classList.remove('hidden');
      } else if (!reachable) {
        ping.textContent = 'недоступен';
        ping.style.color = '#6b7280';
        ping.classList.remove('hidden');
      }
    }

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
  // Устанавливаем radio
  const radioEU = document.querySelector('#add-server-form [name=role][value=EU]');
  const radioRU = document.querySelector('#add-server-form [name=role][value=RU]');
  if (radioEU) radioEU.checked = (role === 'EU');
  if (radioRU) radioRU.checked = (role === 'RU');

  const euBtn = document.getElementById('role-card-eu');
  const ruBtn = document.getElementById('role-card-ru');

  const base   = 'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.75rem;padding:1.5rem 1rem;border-radius:0.875rem;cursor:pointer;width:100%;transition:all 0.2s;';
  const active = base + 'border:2px solid #6366f1;background:#1e1b4b;box-shadow:0 0 0 2px #6366f1,0 4px 24px rgba(99,102,241,0.35);opacity:1;';
  const dim    = base + 'border:2px solid #374151;background:#111827;opacity:0.4;';

  euBtn.style.cssText = (role === 'EU') ? active : dim;
  ruBtn.style.cssText = (role === 'RU') ? active : dim;

  // Показываем общие поля
  document.getElementById('server-fields').classList.remove('hidden');

  // Показываем нужные поля, скрываем ненужные
  const euFields = document.getElementById('eu-fields');
  const ruFields = document.getElementById('ru-fields');

  if (role === 'EU') {
    euFields.classList.remove('hidden');
    ruFields.classList.add('hidden');
    // Делаем пароль обязательным для EU
    document.getElementById('add-server-password').required = true;
    document.getElementById('add-server-ssh-user-ru').required = false;
  } else {
    euFields.classList.add('hidden');
    ruFields.classList.remove('hidden');
    // Для RU пароль не нужен
    document.getElementById('add-server-password').required = false;
    document.getElementById('add-server-ssh-user-ru').required = true;
  }
}

function showAddServerModal() {
  document.getElementById('add-server-form').reset();
  document.getElementById('add-server-error').classList.add('hidden');
  document.getElementById('add-server-geo').classList.add('hidden');
  document.getElementById('add-server-country').value = '??';

  // Скрываем все поля — видны только кнопки выбора роли
  document.getElementById('server-fields').classList.add('hidden');
  document.getElementById('eu-fields').classList.add('hidden');
  document.getElementById('ru-fields').classList.add('hidden');

  // Сбрасываем SSH дефолты EU
  document.getElementById('add-server-ssh-user').value = 'root';
  document.querySelector('#add-server-form [name=ssh_port]').value = '22';
  document.getElementById('server-advanced-fields').classList.add('hidden');
  document.getElementById('server-adv-icon').classList.remove('rotate-90');

  // Сбрасываем загрузку ключа RU
  document.getElementById('add-server-ssh-key').value = '';
  document.getElementById('ssh-key-filename').textContent = 'Перетащите файл ключа или нажмите для выбора';
  document.getElementById('ssh-key-drop-area').classList.remove('border-brand-400', 'border-green-500');

  // Сбрасываем кнопки роли
  const baseStyle = 'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.75rem;padding:1.5rem 1rem;border-radius:0.875rem;border:2px solid #374151;background:#111827;cursor:pointer;width:100%;transition:all 0.2s;opacity:1;';
  document.getElementById('role-card-eu').style.cssText = baseStyle;
  document.getElementById('role-card-ru').style.cssText = baseStyle;
  document.querySelector('#add-server-form [name=role][value=EU]').checked = false;
  document.querySelector('#add-server-form [name=role][value=RU]').checked = false;

  // Сбрасываем превью имени
  document.getElementById('conn-name-preview')?.classList.add('hidden');

  openModal('modal-add-server');
}

// Превью названия подключения в клиенте
function _updateConnNamePreview() {
  const flag = document.getElementById('add-server-flag-emoji')?.value.trim() || '';
  const name = document.getElementById('add-server-display-name')?.value.trim() || '';
  const previewEl = document.getElementById('conn-name-preview');
  const textEl    = document.getElementById('conn-name-preview-text');
  if (!previewEl || !textEl) return;
  if (flag || name) {
    const label = [flag, name].filter(Boolean).join(' ');
    textEl.textContent = `${label} (direct) / ${label} (cascade)`;
    previewEl.classList.remove('hidden');
  } else {
    previewEl.classList.add('hidden');
  }
}
// Вешаем обработчики после загрузки DOM
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('add-server-flag-emoji')
    ?.addEventListener('input', _updateConnNamePreview);
  document.getElementById('add-server-display-name')
    ?.addEventListener('input', _updateConnNamePreview);
});

// ───────────────── SSH KEY FILE HANDLERS ─────────────────
function handleSshKeyFile(input) {
  const file = input.files[0];
  if (!file) return;
  readSshKeyFile(file);
}

function handleSshKeyDrop(event) {
  event.preventDefault();
  document.getElementById('ssh-key-drop-area').classList.remove('border-brand-400');
  const file = event.dataTransfer.files[0];
  if (!file) return;
  readSshKeyFile(file);
}

function readSshKeyFile(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    const content = e.target.result;
    document.getElementById('add-server-ssh-key').value = content;
    document.getElementById('ssh-key-filename').textContent = `✓ ${file.name}`;
    document.getElementById('ssh-key-filename').style.color = '#4ade80';
    document.getElementById('ssh-key-drop-area').style.borderColor = '#22c55e';
  };
  reader.readAsText(file);
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
    geoText.className = 'text-xs text-gray-400';

    // Пробуем ip-api.com (надёжнее, не требует ключа для локальных запросов)
    try {
      const resp = await fetch(`https://ip-api.com/json/${ip}?fields=status,country,countryCode`);
      const data = await resp.json();

      if (data.status === 'success' && data.countryCode) {
        const code = data.countryCode.toLowerCase();
        const name = data.country;
        countryInput.value = data.countryCode.toUpperCase();
        flagImg.src = `https://flagcdn.com/24x18/${code}.png`;
        flagImg.alt = name;
        geoText.textContent = name;
        geoText.className = 'text-xs text-gray-300';
        return;
      }
    } catch { /* fallback */ }

    // Фallback на ipwho.is
    try {
      const resp2 = await fetch(`https://ipwho.is/${ip}`);
      const data2 = await resp2.json();
      if (data2.success && data2.country_code) {
        const code = data2.country_code.toLowerCase();
        countryInput.value = data2.country_code.toUpperCase();
        flagImg.src = `https://flagcdn.com/24x18/${code}.png`;
        flagImg.alt = data2.country;
        geoText.textContent = data2.country;
        geoText.className = 'text-xs text-gray-300';
        return;
      }
    } catch { /* ignore */ }

    geoEl.classList.add('hidden');
    countryInput.value = '??';
  }, 700);
}

document.getElementById('add-server-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const errEl = document.getElementById('add-server-error');
  errEl.classList.add('hidden');

  // Страна определяется автоматически в шаге 4 автонастройки

  const role = form.querySelector('[name=role]:checked')?.value;
  if (!role) {
    errEl.textContent = 'Выберите роль сервера';
    errEl.classList.remove('hidden');
    return;
  }

  // Собираем данные в зависимости от роли
  const data = {
    name:         form.querySelector('[name=name]').value.trim(),
    ip:           form.querySelector('[name=ip]').value.trim(),
    country:      document.getElementById('add-server-country').value || '??',
    role,
    ssh_port:     22,
    flag_emoji:   (form.querySelector('[name=flag_emoji]')?.value || '').trim(),
    display_name: (form.querySelector('[name=display_name]')?.value || '').trim(),
  };

  if (role === 'EU') {
    data.ssh_user     = document.getElementById('add-server-ssh-user').value.trim() || 'root';
    data.ssh_port     = parseInt(form.querySelector('[name=ssh_port]').value) || 22;
    data.ssh_password = document.getElementById('add-server-password').value;
    if (!data.ssh_password) {
      errEl.textContent = 'Введите пароль SSH';
      errEl.classList.remove('hidden');
      return;
    }
  } else {
    // RU
    data.ssh_user = document.getElementById('add-server-ssh-user-ru').value.trim();
    data.ssh_key  = document.getElementById('add-server-ssh-key').value.trim();
    if (!data.ssh_user) {
      errEl.textContent = 'Введите имя пользователя SSH';
      errEl.classList.remove('hidden');
      return;
    }
    if (!data.ssh_key) {
      errEl.textContent = 'Загрузите файл SSH-ключа';
      errEl.classList.remove('hidden');
      return;
    }
  }

  if (!data.name || !data.ip) {
    errEl.textContent = 'Заполните название и IP-адрес';
    errEl.classList.remove('hidden');
    return;
  }

  const submitBtn = form.querySelector('[type=submit]');
  submitBtn.innerHTML = '<span class="spinner"></span> Добавление...';
  submitBtn.disabled = true;

  const res = await api.createServer(data);
  submitBtn.innerHTML = '<i class="fas fa-plus text-xs"></i> Добавить';
  submitBtn.disabled = false;

  if (res.ok) {
    closeModal('modal-add-server');
    // Запускаем автонастройку сервера
    const srv = res.data;
    await api.request('POST', `/servers/${srv.id}/setup`);
    openServerSetupModal(srv.id, srv.name, srv.ip, srv.role);
  } else {
    errEl.textContent = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
    errEl.classList.remove('hidden');
  }
});

// ───────────────── SERVER DETAIL ─────────────────
// ───────────────── SERVER DETAIL (4 вкладки) ─────────────────
let _sdServerId = null;

function sdTab(tab) {
  ['overview','actions','stack','params'].forEach(t => {
    document.getElementById(`sd-pane-${t}`).classList.toggle('hidden', t !== tab);
    const btn = document.getElementById(`sd-tab-${t}`);
    if (t === tab) {
      btn.classList.add('text-brand-400','border-brand-500');
      btn.classList.remove('text-gray-500','border-transparent');
    } else {
      btn.classList.remove('text-brand-400','border-brand-500');
      btn.classList.add('text-gray-500','border-transparent');
    }
  });
  if (tab === 'params') _renderParamsTab();
}

function _renderParamsTab() {
  const server = serversData.find(s => s.id === _sdServerId);
  const el = document.getElementById('sd-params-content');
  if (!server || !el) return;

  const isEU = (server.role || '').toUpperCase() === 'EU';
  const badge = _getSetupBadgeMeta(server);

  // helper — строка параметра
  const row = (label, valueHtml, mono = false) =>
    `<div class="flex items-start justify-between py-1.5 border-b border-white/5 last:border-0">
      <span class="text-gray-500 text-xs flex-shrink-0 mr-3">${label}</span>
      <span class="${mono ? 'font-mono' : ''} text-xs text-gray-200 text-right break-all">${valueHtml}</span>
    </div>`;

  // ── SSH параметры ─────────────────────────────────────────────
  const portOk  = server.ssh_port_actual || server.ssh_port || 22;
  const userOk  = server.ssh_user_actual || server.ssh_user || 'root';

  const hasKey     = !!(server.ssh_private_key_enc || server.has_ssh_key);
  const hasPassEnc = !!(server.ssh_password_enc     || server.has_ssh_password);

  const keyHtml = hasKey
    ? '<span class="text-emerald-400">✅ сохранён в БД</span>'
    : '<span class="text-gray-600">не задан</span>';

  let passHtml;
  if (server.ssh_password) {
    passHtml = '<span class="text-yellow-400">⚠ открытый текст</span>';
  } else if (hasPassEnc) {
    passHtml = '<span class="text-emerald-400">✅ зашифрован</span>';
  } else if (hasKey) {
    passHtml = '<span class="text-gray-500">— вход по ключу</span>';
  } else {
    passHtml = '<span class="text-gray-600">не задан</span>';
  }

  // ── Security флаги ────────────────────────────────────────────
  const secIcon = (v) => {
    if (v === true)  return '<span class="text-emerald-400">✅</span>';
    if (v === false) return '<span class="text-red-400">❌</span>';
    return '<span class="text-gray-600">—</span>';
  };
  // Для пароль-логин: True = включён (плохо), False = выключен (хорошо)
  const passLoginHtml = server.sec_password_login === false
    ? '<span class="text-emerald-400">✅ отключён</span>'
    : server.sec_password_login === true
      ? '<span class="text-yellow-400">⚠ включён</span>'
      : '<span class="text-gray-600">—</span>';

  // ── Версии сервисов ───────────────────────────────────────────
  const ver = (installed, version, label) => {
    if (!installed && !version) return `<span class="text-gray-600">не установлен</span>`;
    if (version) return `<span class="text-gray-200 font-mono">${version}</span>`;
    return `<span class="text-gray-400">${label} установлен</span>`;
  };

  // ── Xray public key ───────────────────────────────────────────
  const xrayKey = server.xray_public_key
    ? `<span class="font-mono text-gray-400 break-all text-[10px]">${server.xray_public_key.slice(0,32)}…</span>`
    : '<span class="text-gray-600">—</span>';

  el.innerHTML = `
  <!-- 1. SSH-доступ -->
  <section class="mb-4">
    <div class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">SSH — доступ</div>
    <div class="bg-white/3 rounded-xl border border-white/6 px-3 py-1">
      ${row('Пользователь', userOk, true)}
      ${row('Порт', String(portOk), true)}
      ${row('SSH-ключ', keyHtml)}
      ${row('Пароль', passHtml)}
    </div>
  </section>

  <!-- 2. Безопасность -->
  <section class="mb-4">
    <div class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Безопасность</div>
    <div class="bg-white/3 rounded-xl border border-white/6 px-3 py-1">
      ${row('Fail2Ban',         secIcon(server.sec_fail2ban))}
      ${row('UFW',              secIcon(server.sec_ufw))}
      ${row('Вход по паролю',   passLoginHtml)}
      ${row('SSH-ключ задан',   secIcon(server.sec_ssh_key))}
    </div>
  </section>

  <!-- 3. Стек сервисов -->
  <section class="mb-4">
    <div class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Стек</div>
    <div class="bg-white/3 rounded-xl border border-white/6 px-3 py-1">
      ${row('Xray-core',   ver(server.xray_installed,        server.xray_version,   'Xray'))}
      ${row('AmneziaWG',   ver(server.awg_installed,         server.awg_version,    'AWG'))}
      ${row('NaiveProxy',  ver(server.naiveproxy_installed,  server.caddy_version,  'naive'))}
      ${row('WARP', ver(server.warp_installed, server.warp_version, 'WARP'))}
      ${row('Timezone', server.server_timezone || '—')}
    </div>
  </section>

  <!-- 4. Ключи протоколов -->
  <section class="mb-4">
    <div class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Ключи протоколов</div>
    <div class="bg-white/3 rounded-xl border border-white/6 px-3 py-1">
      ${row('Xray Reality pubkey', xrayKey)}
      ${row('AWG server pubkey', server.awg_server_public_key
        ? '<span class="font-mono text-gray-400 text-[10px]">' + server.awg_server_public_key.slice(0,24) + '…</span>'
        : '<span class="text-gray-600">—</span>')}
    </div>
  </section>

  <!-- 5. Статус настройки -->
  <section class="mb-4">
    <div class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Статус настройки</div>
    <div class="bg-white/3 rounded-xl border border-white/6 px-3 py-1">
      <div class="flex items-center justify-between py-1.5">
        <span class="text-gray-500 text-xs">Статус</span>
        <span style="font-size:0.65rem;font-weight:600;padding:1px 8px;border-radius:999px;
                     color:${badge.color};background:${badge.bg};border:1px solid ${badge.color}22;">
          ${badge.label}
        </span>
      </div>
      ${server.setup_error ? `
      <div class="py-1.5 border-t border-white/5">
        <span class="text-red-400 text-xs break-all">${_escHtml(server.setup_error)}</span>
      </div>` : ''}
    </div>
  </section>

  <!-- Кнопка перезапуска -->
  <button onclick="openServerSetupModal(${server.id}, '${_escHtml(server.name)}', '${server.ip}', '${server.role}')"
    class="w-full py-2 bg-brand-600/80 hover:bg-brand-500 rounded-xl text-xs font-medium text-white transition flex items-center justify-center gap-2">
    <i class="fas fa-rotate-right text-xs"></i> Перезапустить настройку
  </button>`;
}

async function showServerDetail(serverId) {
  _sdServerId = serverId;
  openModal('modal-server-detail');
  sdTab('overview');

  const server = serversData.find(s => s.id === serverId);
  if (!server) return;

  // Шапка
  document.getElementById('sd-flag').innerHTML = getFlag(server.country);
  document.getElementById('sd-title').textContent = server.name;
  document.getElementById('sd-meta').innerHTML = `
    <span id="sd-status-dot" class="status-dot ${server.status}"></span>
    <span id="sd-status-txt" style="font-size:0.72rem;font-weight:600;color:${server.status==='online'?'#4ade80':server.status==='offline'?'#f87171':'#6b7280'}">
      ${server.status==='online'?'Online':server.status==='offline'?'Offline':'Unknown'}
    </span>
    <span class="text-gray-700 text-xs">·</span>
    <span class="text-gray-500 text-xs">${server.role === 'EU' ? 'EU Exit' : 'RU Entry'}</span>
  `;

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

// ───────────────── SERVER SETTINGS — 4 TABS ─────────────────

function switchSettingsTab(tab) {
  const tabs = ['overview', 'actions', 'stack', 'security', 'params'];
  tabs.forEach(t => {
    document.getElementById(`stab-${t}`)?.classList.toggle('active', t === tab);
    document.getElementById(`stab-content-${t}`)?.classList.toggle('hidden', t !== tab);
  });
  // Безопасность: автозагрузка при переходе на вкладку
  if (tab === 'security') loadSecurityStatus();
}

function showServerSettings(serverId) {
  const server = serversData.find(s => s.id === serverId);
  window._currentSettingsServerId = serverId;
  if (!server) return;

  document.getElementById('settings-server-id').value = serverId;

  // Header
  document.getElementById('settings-server-title').textContent = server.name;
  document.getElementById('settings-server-meta').textContent =
    `${server.ip} · ${server.role === 'EU' ? 'EU Exit' : 'RU Entry'}`;
  const flagEl = document.getElementById('settings-server-flag');
  flagEl.innerHTML = getFlag(server.country);

  // ── TAB: Overview ──
  document.getElementById('sov-ip').textContent     = server.ip;
  document.getElementById('sov-role').textContent   = server.role === 'EU' ? 'EU Exit' : 'RU Entry';
  document.getElementById('sov-domain').textContent = server.domain || '—';
  // Country with flag + full name
  const cc = (server.country || '??').toLowerCase();
  const countryName = ISO_COUNTRY_NAMES[server.country] || server.country || '??';
  document.getElementById('sov-country').innerHTML =
    (server.country && server.country !== '??')
      ? `<img src="https://flagcdn.com/16x12/${cc}.png" alt="${countryName}" class="rounded-sm inline-block"> ${countryName}`
      : '??';
  // Reset sysinfo, then auto-load
  ['os','cpu','ram','disk'].forEach(k => document.getElementById(`sov-${k}`).textContent = '—');
  const hint = document.getElementById('sov-sysinfo-hint');
  if (hint) { hint.textContent = 'Загружаю...'; hint.classList.remove('hidden'); }
  loadServerInfoTab();

  // ── TAB: Stack ──
  _updateStackTab(server);

  // ── TAB: Params ──
  document.getElementById('settings-name').value         = server.name;
  document.getElementById('settings-ip').value           = server.ip || '';
  document.getElementById('settings-domain').value       = server.domain || '';
  // Роль и страна — readonly, показываем как текст
  document.getElementById('settings-role').value         = server.role === 'EU' ? 'EU Exit' : 'RU Entry';
  document.getElementById('settings-country').value      = server.country || '—';
  document.getElementById('settings-ssh-user').value     = server.ssh_user_actual || server.ssh_user || 'root';
  document.getElementById('settings-ssh-port').value     = server.ssh_port_actual || server.ssh_port || 22;
  // Sensitive fields — clear value AND show status in placeholder
  const pwdInput = document.getElementById('settings-ssh-password');
  pwdInput.value = '';
  pwdInput.type = 'password';
  delete pwdInput.dataset.loaded;  // сброс кэша при открытии другого сервера
  pwdInput.placeholder = server.ssh_password_enc
    ? '••••••••  (сохранён зашифровано)'
    : 'Введите новый пароль для изменения';
  const keyInput = document.getElementById('settings-ssh-key');
  keyInput.value = '';
  keyInput.placeholder = server.ssh_private_key_enc
    ? '-----BEGIN OPENSSH PRIVATE KEY-----\n(ключ сохранён, нажмите «Скопировать ключ»)'
    : 'Вставьте приватный ключ для изменения';
  // Дата добавления сервера
  const createdEl = document.getElementById('sov-created');
  if (createdEl) {
    if (server.created_at) {
      const d = new Date(server.created_at);
      createdEl.textContent = d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' });
    } else {
      createdEl.textContent = '—';
    }
  }

  // Security checkboxes — предзаполняем из sec_* полей БД (быстро, без SSH-запроса)
  // Свежие данные будут загружены при переходе на вкладку Security
  const _secDbMap = {
    'sec-fail2ban':       server.sec_fail2ban,       // null = unknown
    'sec-ufw':            server.sec_ufw,
    'sec-password-login': server.sec_password_login != null ? !server.sec_password_login : null,  // inverted: true=disabled=good
    'sec-root-login':     null,  // нет в БД, получим через SSH
  };
  Object.entries(_secDbMap).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (val !== null && val !== undefined) {
      el.checked  = !!val;
      el.disabled = false;  // разрешаем взаимодействие
    } else {
      el.checked  = false;
      el.disabled = true;   // неизвестно
    }
  });
  const secMsg = document.getElementById('sec-status-msg');
  if (server.sec_fail2ban !== null && server.sec_fail2ban !== undefined) {
    if (secMsg) { secMsg.textContent = 'ℹ️ Данные из БД (на момент настройки). Актуальные — нажмите Обновить'; secMsg.classList.remove('hidden'); secMsg.style.color = '#9ca3af'; }
  } else {
    if (secMsg) { secMsg.textContent = ''; secMsg.classList.add('hidden'); }
  }

  // ── Reset action msg ──
  const msg = document.getElementById('settings-action-msg');
  if (msg) msg.textContent = '';

  // Open modal on Overview tab
  switchSettingsTab('overview');
  openModal('modal-server-settings');
}

async function loadSecurityStatus() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  if (!serverId) return;

  const loading = document.getElementById('sec-loading');
  const refreshBtn = document.getElementById('sec-refresh-btn');
  if (loading) loading.classList.remove('hidden');
  if (refreshBtn) refreshBtn.disabled = true;

  try {
    const res = await api.getSecurityStatus(serverId);
    if (res.ok) {
      const s = res.data;
      // password_login и root_login инвертированы:
      // галочка = "запрещён" → checked когда val=false
      const map = {
        'sec-password-login': !s.password_login,
        'sec-root-login':     !s.root_login,
        'sec-fail2ban':       s.fail2ban,
        'sec-ufw':            s.ufw,
      };
      Object.entries(map).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) { el.checked = val; el.disabled = false; }
      });

      // Обновляем кэш serversData с реальными данными
      const cached = serversData.find(sv => sv.id === serverId);
      if (cached) {
        cached.sec_fail2ban       = s.fail2ban;
        cached.sec_ufw            = s.ufw;
        cached.sec_password_login = s.password_login;   // труе = enabled (bad)
        // root_login нет в БД, не кэшируем
      }

      const secMsg = document.getElementById('sec-status-msg');
      if (secMsg) { secMsg.textContent = '✓ Статус обновлён'; secMsg.classList.remove('hidden'); secMsg.style.color = '#4ade80'; }
    } else {
      const secMsg = document.getElementById('sec-status-msg');
      if (secMsg) { secMsg.textContent = 'Не удалось получить статус SSH'; secMsg.classList.remove('hidden'); secMsg.style.color = '#f87171'; }
    }
  } catch (e) {
    const secMsg = document.getElementById('sec-status-msg');
    if (secMsg) { secMsg.textContent = `Ошибка загрузки: ${e.message}`; secMsg.classList.remove('hidden'); secMsg.style.color = '#f87171'; }
  } finally {
    if (loading) loading.classList.add('hidden');
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

async function applySecSetting(setting, enabled) {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  if (!serverId) return;

  const secMsg = document.getElementById('sec-status-msg');
  if (secMsg) { secMsg.textContent = 'Применяю...'; secMsg.classList.remove('hidden'); secMsg.style.color = '#facc15'; }

  // Блокируем чекбокс на время запроса
  const cbMap = { password_login: 'sec-password-login', root_login: 'sec-root-login', fail2ban: 'sec-fail2ban', ufw: 'sec-ufw' };
  const cbEl = document.getElementById(cbMap[setting]);
  if (cbEl) cbEl.disabled = true;

  try {
    const res = await api.setSecuritySetting(serverId, setting, enabled);
    if (res.ok) {
      if (secMsg) { secMsg.textContent = '✓ ' + res.data.message; secMsg.style.color = '#4ade80'; }
    } else {
      if (secMsg) { secMsg.textContent = '✗ ' + (res.error || 'Ошибка'); secMsg.style.color = '#f87171'; }
      // Откатываем чекбокс
      if (cbEl) cbEl.checked = !enabled;
    }
  } catch (e) {
    if (secMsg) { secMsg.textContent = '✗ Ошибка запроса'; secMsg.style.color = '#f87171'; }
    if (cbEl) cbEl.checked = !enabled;
  } finally {
    if (cbEl) cbEl.disabled = false;
  }
}

function _updateStackTab(server) {
  const isEU = (server.role || '').toUpperCase() === 'EU';

  // WARP теперь устанавливается на все серверы (EU и RU)
  // EU серверы получают WARP как fallback для заблокированных ресурсов
  const warpRow = document.getElementById('stack-row-warp');
  if (warpRow) warpRow.style.display = ''; // показываем всегда

  const services = [
    { key: 'xray',  label: 'Xray-core',               installed: server.xray_installed,         version: server.xray_version   },
    { key: 'awg',   label: 'AmneziaWG',               installed: server.awg_installed,          version: server.awg_version    },
    { key: 'warp', label: 'WARP',        installed: server.warp_installed,         version: server.warp_version   },
    { key: 'naive', label: 'NaiveProxy (caddy-naive)', installed: server.naiveproxy_installed,  version: server.caddy_version  },
  ];
  // svcMap: key -> API service name (for install/uninstall), restartMap: key -> systemd unit
  const svcMap    = { xray: 'xray', awg: 'awg', warp: 'warp', naive: 'naiveproxy' };
  const restartMap = { xray: 'xray', awg: 'awg', warp: 'warp', naive: 'caddy-naive' };

  services.forEach(({ key, label, installed, version }) => {
    const dot    = document.getElementById(`stack-icon-${key}`);
    const status = document.getElementById(`stack-status-${key}`);
    const btns   = document.getElementById(`stack-btns-${key}`);
    const serverId = parseInt(document.getElementById('settings-server-id').value);

    if (dot) {
      dot.className = `w-2 h-2 rounded-full flex-shrink-0 ${installed ? 'bg-green-500' : 'bg-gray-600'}`;
    }
    if (status) {
      const verShort = version ? version.split(' ')[0] : null;
      status.textContent = installed
        ? (verShort ? `Установлен (${verShort})` : 'Установлен')
        : 'Не установлен';
    }
    if (btns) {
      if (installed) {
        // WARP получает специальный toggle enable/disable + кнопки restart/uninstall
        if (key === 'warp') {
          btns.innerHTML = `
            <button onclick="toggleWarpServer(${serverId}, true)"
              class="px-2 py-1 bg-green-600/20 hover:bg-green-600/40 border border-green-800 rounded-lg text-xs text-green-300 transition" title="Включить WARP">
              <i class="fas fa-play"></i>
            </button>
            <button onclick="toggleWarpServer(${serverId}, false)"
              class="px-2 py-1 bg-orange-600/20 hover:bg-orange-600/40 border border-orange-800 rounded-lg text-xs text-orange-300 transition" title="Выключить WARP">
              <i class="fas fa-stop"></i>
            </button>
            <button onclick="stackRestartService('${restartMap[key]}', ${serverId})"
              class="px-2 py-1 bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-800 rounded-lg text-xs text-yellow-300 transition" title="Рестарт">
              <i class="fas fa-rotate-right"></i>
            </button>
            <button onclick="stackUninstallService('${svcMap[key]}', '${label}', ${serverId})"
              class="px-2 py-1 bg-red-600/20 hover:bg-red-600/40 border border-red-800 rounded-lg text-xs text-red-300 transition" title="Удалить">
              <i class="fas fa-trash"></i>
            </button>`;
        } else {
          btns.innerHTML = `
            <button onclick="stackRestartService('${restartMap[key]}', ${serverId})"
              class="px-2 py-1 bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-800 rounded-lg text-xs text-yellow-300 transition" title="Рестарт">
              <i class="fas fa-rotate-right"></i>
            </button>
            <button onclick="stackUninstallService('${svcMap[key]}', '${label}', ${serverId})"
              class="px-2 py-1 bg-red-600/20 hover:bg-red-600/40 border border-red-800 rounded-lg text-xs text-red-300 transition" title="Удалить">
              <i class="fas fa-trash"></i>
            </button>`;
        }
      } else {
        btns.innerHTML = `
          <button onclick="stackInstallService('${svcMap[key]}', '${label}', ${serverId})"
            class="px-2 py-1 bg-brand-600/20 hover:bg-brand-600/40 border border-brand-700 rounded-lg text-xs text-brand-300 transition">
            <i class="fas fa-download mr-1"></i>Установить
          </button>`;
      }
    }
  });
}

async function loadServerInfoTab() {
  const serverId = document.getElementById('settings-server-id').value;
  const hint = document.getElementById('sov-sysinfo-hint');
  if (hint) hint.textContent = 'Загружаю...';

  const res = await api.serverInfo(serverId);
  if (!res.ok) {
    if (hint) { hint.textContent = `Ошибка: ${res.error}`; hint.classList.remove('hidden'); }
    return;
  }
  // Бэкенд возвращает { system_info: { os, cpu_cores, memory, disk, uptime } }
  const si = res.data.system_info || res.data;
  document.getElementById('sov-os').textContent     = si.os        || si.os_info    || '—';
  document.getElementById('sov-cpu').textContent    = si.cpu_cores || si.cpu_info   || '—';
  document.getElementById('sov-ram').textContent    = si.memory    || si.ram_info   || '—';
  document.getElementById('sov-disk').textContent   = si.disk      || si.disk_info  || '—';
  const uptimeEl = document.getElementById('sov-uptime');
  if (uptimeEl) uptimeEl.textContent = si.uptime || '—';
  if (hint) hint.classList.add('hidden');
}

// ── Actions tab helpers ──

/** Запуск полной повторной настройки сервера из вкладки Actions */
async function runFullResetup() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  const server = serversData.find(s => s.id === serverId);
  if (!server) return;
  if (!confirm(`Запустить полную повторную настройку сервера "${server.name}"?\n\nЭто займёт 5–15 минут.`)) return;

  closeModal('modal-server-settings');
  openServerSetupModal(serverId, server.name, server.ip, server.role);
  await api.request('POST', `/servers/${serverId}/setup/retry`);
  _startSetupPolling();
}

async function updateServerStatus() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  const btn    = document.getElementById('btn-update-status');
  const result = document.getElementById('action-ping-result');

  if (btn) { btn.innerHTML = '<span class="spinner" style="width:10px;height:10px;"></span> Проверяю...'; btn.disabled = true; }
  if (result) { result.textContent = 'Пинг...'; result.style.color = '#9ca3af'; result.classList.remove('hidden'); }

  // Шаг 1: пинг — быстро, показываем сразу
  const pingRes = await api.pingServer(serverId);

  if (btn) { btn.innerHTML = '<i class="fas fa-satellite-dish text-xs"></i> Обновить'; btn.disabled = false; }

  if (!pingRes.ok) {
    if (result) { result.textContent = `Ошибка: ${pingRes.error}`; result.style.color = '#f87171'; }
    return;
  }

  const { reachable, latency_ms } = pingRes.data;

  // Показываем пинг сразу
  let line = reachable ? '✓ Online' : '✗ Offline';
  if (reachable && latency_ms !== null) line += ` · ${latency_ms} ms`;
  if (result) {
    result.textContent = line;
    result.style.color = reachable ? '#4ade80' : '#f87171';
  }

  // Обновляем карточку — статус и пинг
  const dot  = document.getElementById(`status-dot-${serverId}`);
  const txt  = document.getElementById(`status-text-${serverId}`);
  const ping = document.getElementById(`ping-val-${serverId}`);
  if (dot) dot.className = `status-dot ${reachable ? 'online' : 'offline'}`;
  if (txt) { txt.style.color = reachable ? '#4ade80' : '#f87171'; txt.textContent = reachable ? 'Online' : 'Offline'; }
  if (ping) {
    if (latency_ms !== null) {
      ping.textContent = `${latency_ms} ms`;
      ping.style.color = latency_ms < 100 ? '#4ade80' : latency_ms < 300 ? '#facc15' : '#f87171';
      ping.classList.remove('hidden');
    } else if (!reachable) {
      ping.textContent = 'недоступен';
      ping.style.color = '#6b7280';
      ping.classList.remove('hidden');
    }
  }

  const srv = serversData.find(s => s.id === serverId);
  if (srv) srv.status = reachable ? 'online' : 'offline';
}

async function restartServicesAction() {
  const serverId = document.getElementById('settings-server-id').value;
  toast('Перезапуск сервисов...', 'info', 3000);
  const res = await api.restartServices(serverId);
  if (res.ok) toast(`✓ ${res.data.message}`, 'success', 5000);
  else toast(`Ошибка: ${res.error}`, 'error');
}

async function redeployConfigAction() {
  const serverId = document.getElementById('settings-server-id').value;
  toast('Redeploy конфигураций...', 'info', 3000);
  const res = await api.redeployServer(serverId);
  if (res.ok) toast(res.data.message, 'success');
  else toast(`Ошибка: ${res.error}`, 'error');
}

async function deleteServerFromSettings() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  const server = serversData.find(s => s.id === serverId);
  if (!confirm(`Удалить сервер "${server?.name}"?\n\nВсе подключения этого сервера также будут удалены.`)) return;
  const res = await api.deleteServer(serverId);
  if (res.ok || res.status === 204) {
    toast(`Сервер ${server?.name} удалён`, 'success');
    closeModal('modal-server-settings');
    loadServers();
  } else {
    toast(`Ошибка удаления: ${res.error}`, 'error');
  }
}

// ── Stack tab helpers ──

async function stackInstallService(svc, label, serverId) {
  const output = document.getElementById('stack-output');
  output.classList.remove('hidden');
  output.textContent = `Устанавливаю ${label}...`;

  const installData = {
    install_xray:       svc === 'xray',
    install_naiveproxy: svc === 'naiveproxy',
    install_awg:        svc === 'awg',
    install_warp:       svc === 'warp',
  };
  const res = await api.installStack(serverId, installData);
  if (res.ok) {
    const r = res.data.results?.[svc] || res.data.results?.[Object.keys(res.data.results||{})[0]];
    output.textContent = r ? `[${r.success?'OK':'ERR'}] ${r.message}` : 'Готово';
    toast(`${label} установлен`, 'success');
    // refresh servers and re-render stack tab
    await loadServers();
    const updated = serversData.find(s => s.id === serverId);
    if (updated) _updateStackTab(updated);
  } else {
    output.textContent = `Ошибка: ${res.error}`;
    toast(`Ошибка установки: ${res.error}`, 'error');
  }
}

async function stackUninstallService(svc, label, serverId) {
  if (!confirm(`Удалить ${label} с сервера?\n\nПодключения через этот сервис перестанут работать.`)) return;
  const output = document.getElementById('stack-output');
  output.classList.remove('hidden');
  output.textContent = `Удаляю ${label}...`;

  const data = {
    uninstall_xray:       svc === 'xray',
    uninstall_naiveproxy: svc === 'naiveproxy',
    uninstall_awg:        svc === 'awg',
    uninstall_warp:       svc === 'warp',
  };
  const res = await api.uninstallStack(serverId, data);
  if (res.ok) {
    output.textContent = res.data.message || 'Удалено';
    toast(`${label} удалён`, 'success');
    await loadServers();
    const updated = serversData.find(s => s.id === serverId);
    if (updated) _updateStackTab(updated);
  } else {
    output.textContent = `Ошибка: ${res.error}`;
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

async function stackRestartService(svc, serverId) {
  toast(`Перезапуск ${svc}...`, 'info', 3000);
  // Use specific service restart via SSH if available, fallback to restartServices
  const res = await api.post(`/api/v1/servers/${serverId}/restart-service`, { service: svc });
  if (res.ok) {
    toast(`✓ ${svc} перезапущен`, 'success', 4000);
  } else {
    // Fallback: restart all services
    const res2 = await api.restartServices(serverId);
    if (res2.ok) toast(`✓ Сервисы перезапущены`, 'success', 4000);
    else toast(`Ошибка: ${res2.error}`, 'error');
  }
}

async function destroyAllStack() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  const server = serversData.find(s => s.id === serverId);
  if (!confirm(`Снести весь VPN-стек на "${server?.name}"?\n\nВсе сервисы будут остановлены и удалены.`)) return;
  const output = document.getElementById('stack-output');
  output.classList.remove('hidden');
  output.textContent = 'Удаляю весь стек...';

  const res = await api.uninstallStack(serverId, {
    uninstall_xray: true, uninstall_naiveproxy: true,
    uninstall_awg: true,  uninstall_warp: true,
  });
  if (res.ok) {
    output.textContent = res.data.message || 'Готово';
    toast('Стек полностью удалён', 'success');
    await loadServers();
    const updated = serversData.find(s => s.id === serverId);
    if (updated) _updateStackTab(updated);
  } else {
    output.textContent = `Ошибка: ${res.error}`;
    toast(`Ошибка: ${res.error}`, 'error');
  }
}


async function toggleWarpServer(serverId, enabled) {
  const output = document.getElementById('stack-output');
  if (output) {
    output.classList.remove('hidden');
    output.textContent = enabled ? 'Включаю WARP...' : 'Выключаю WARP...';
  }

  const res = await api.post(`/api/v1/servers/${serverId}/warp/toggle`, { enabled });
  if (res.ok) {
    const msg = res.data.message || (enabled ? 'WARP включён' : 'WARP выключен');
    if (output) output.textContent = msg;
    toast(enabled ? '✓ WARP включён' : '✓ WARP выключен', 'success');
    // Обновляем live-статус
    setTimeout(() => loadWarpStatus(serverId), 1500);
  } else {
    if (output) output.textContent = `Ошибка: ${res.error}`;
    toast(`Ошибка WARP: ${res.error}`, 'error');
  }
}

async function loadWarpStatus(serverId) {
  const statusEl = document.getElementById('stack-status-warp');
  if (!statusEl) return;
  statusEl.textContent = 'Проверяю...';
  statusEl.style.color = '';

  const res = await api.get(`/api/v1/servers/${serverId}/warp/status`);
  if (res.ok) {
    const d = res.data;
    const dot = document.getElementById('stack-icon-warp');
    const state = d.state || (d.connected ? 'connected' : d.running ? 'running' : 'stopped');

    if (!d.installed) {
      statusEl.textContent = 'Не установлен';
      statusEl.style.color = '#9ca3af';
      if (dot) dot.className = 'w-2 h-2 rounded-full flex-shrink-0 bg-gray-600';
    } else if (state === 'needs_tos' || d.needs_registration) {
      statusEl.textContent = 'Требует регистрации ⚠';
      statusEl.style.color = '#f59e0b';
      if (dot) dot.className = 'w-2 h-2 rounded-full flex-shrink-0 bg-yellow-500';
      // Автоматически попытаться переподключить
      statusEl.title = d.status_text || 'Нажмите "Включить" для регистрации WARP';
    } else if (state === 'connected' || (d.running && d.connected)) {
      statusEl.textContent = 'Активен ✓';
      statusEl.style.color = '#4ade80';
      if (dot) dot.className = 'w-2 h-2 rounded-full flex-shrink-0 bg-green-500';
    } else if (d.running && !d.connected) {
      statusEl.textContent = 'Запущен (не подключён)';
      statusEl.style.color = '#fb923c';
      if (dot) dot.className = 'w-2 h-2 rounded-full flex-shrink-0 bg-orange-500';
    } else if (state === 'stopped' || !d.running) {
      statusEl.textContent = 'Остановлен';
      statusEl.style.color = '#9ca3af';
      if (dot) dot.className = 'w-2 h-2 rounded-full flex-shrink-0 bg-gray-600';
    }
    // Обновить версию если есть
    const verEl = document.getElementById('stack-ver-warp');
    if (verEl && d.version) verEl.textContent = d.version;
  } else {
    statusEl.textContent = 'Ошибка запроса';
    statusEl.style.color = '#ef4444';
  }
}

// ── Params tab helpers ──

async function saveServerParams() {
  const serverId = document.getElementById('settings-server-id').value;
  const payload = {
    name:     document.getElementById('settings-name').value.trim()    || undefined,
    ip:       document.getElementById('settings-ip').value.trim()      || undefined,
    domain:   document.getElementById('settings-domain').value.trim()  || undefined,
    // role и country — readonly, не отправляем
    ssh_user: document.getElementById('settings-ssh-user').value.trim() || undefined,
    ssh_port: parseInt(document.getElementById('settings-ssh-port').value) || undefined,
  };
  // Only send password/key if actually filled
  const pwd = document.getElementById('settings-ssh-password').value;
  if (pwd) payload.ssh_password = pwd;
  const key = document.getElementById('settings-ssh-key').value.trim();
  if (key) payload.ssh_key = key;

  const res = await api.updateServer(serverId, payload);
  if (res.ok) {
    toast('Параметры сохранены', 'success');
    // Clear sensitive fields after save
    document.getElementById('settings-ssh-password').value = '';
    document.getElementById('settings-ssh-key').value      = '';
    loadServers();
  } else {
    toast(`Ошибка: ${res.error}`, 'error');
  }
}

function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';
  btn.querySelector('i').className = `fas fa-eye${isHidden ? '-slash' : ''} text-xs`;
}

function toggleSshKeyVisibility(btn) {
  const ta = document.getElementById('settings-ssh-key');
  if (!ta) return;
  const isBlurred = ta.style.webkitTextSecurity === 'disc';
  ta.style.webkitTextSecurity = isBlurred ? '' : 'disc';
  btn.querySelector('i').className = `fas fa-eye${isBlurred ? '' : '-slash'} text-xs`;
}

// ── Legacy stubs (called from server-detail modal buttons) ──
async function restartServerServices(serverId) {
  toast('Перезапуск сервисов...', 'info', 3000);
  const res = await api.restartServices(serverId);
  if (res.ok) toast(`✓ ${res.data.message}`, 'success', 5000);
  else toast(`Ошибка: ${res.error}`, 'error');
}

async function redeployServerConfig(serverId) {
  toast('Redeploy конфигураций...', 'info', 3000);
  const res = await api.redeployServer(serverId);
  if (res.ok) toast(res.data.message, 'success');
  else toast(`Ошибка: ${res.error}`, 'error');
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

window.runFullResetup             = runFullResetup;
// Expose globally
window.selectRole                 = selectRole;
window.toggleServerAdvanced       = toggleServerAdvanced;
window.detectIpInfo               = detectIpInfo;
window.loadServers                = loadServers;
window.pingServer                 = pingServer;
window.loadConnStats              = loadConnStats;
window.checkAllServers            = checkAllServers;
window.showAddServerModal         = showAddServerModal;
window.showServerDetail           = showServerDetail;
window.showInstallModal           = showInstallModal;
window.confirmInstallStack        = confirmInstallStack;
window.showServerSettings         = showServerSettings;
window.loadSecurityStatus         = loadSecurityStatus;
window.applySecSetting            = applySecSetting;
window.switchSettingsTab          = switchSettingsTab;
window.loadServerInfoTab          = loadServerInfoTab;
window.updateServerStatus         = updateServerStatus;
window.restartServicesAction      = restartServicesAction;
window.redeployConfigAction       = redeployConfigAction;
window.deleteServerFromSettings   = deleteServerFromSettings;
window.stackInstallService        = stackInstallService;
window.stackUninstallService      = stackUninstallService;
window.stackRestartService        = stackRestartService;
window.toggleWarpServer           = toggleWarpServer;
window.loadWarpStatus             = loadWarpStatus;
window.destroyAllStack            = destroyAllStack;
window.saveServerParams           = saveServerParams;
window.togglePasswordVisibility   = togglePasswordVisibility;
window.toggleSshKeyVisibility     = toggleSshKeyVisibility;
// Legacy (still called from server-detail modal)
window.saveServerInfo             = saveServerParams;
window.confirmDeleteServer        = confirmDeleteServer;
window.restartServerServices      = restartServerServices;
window.redeployServerConfig       = redeployServerConfig;
window.handleSshKeyFile           = handleSshKeyFile;
window.handleSshKeyDrop           = handleSshKeyDrop;

// ───────────────── SERVER SETUP PROGRESS ─────────────────

let _setupServerId  = null;
let _setupPollTimer = null;
let _setupServer    = null; // полный объект сервера

const SETUP_STEP_MAP = { step1:1, step2:2, step3:3, step4:4, step5:5 };

// Новый порядок: 1-проверка, 2-стек, 3-безопасность, 4-сбор инфо, 5-финал
const SETUP_STEP_LABELS = {
  1: 'Проверка подключения',
  2: 'Установка стека',
  3: 'Настройка безопасности',
  4: 'Сбор параметров сервера',
  5: 'Финальная проверка',
};

// ── вспомогательные функции UI ──────────────────────────

function _escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _stpSetDot(n, state) {
  // state: 'pending' | 'running' | 'ok' | 'error' | 'warn'
  const dot  = document.getElementById(`setup-dot-${n}`);
  if (!dot) return;
  dot.className = `stp-dot stp-${state}`;
  const iconMap = {
    pending: 'fa-minus',
    running: 'fa-circle-notch stp-spin',
    ok:      'fa-check',
    error:   'fa-xmark',
    warn:    'fa-triangle-exclamation',
  };
  dot.innerHTML = `<i class="fas ${iconMap[state] || 'fa-minus'}"></i>`;
}

function _stpSetConn(n, done) {
  const c = document.getElementById(`setup-conn-${n}`);
  if (c) {
    c.className = 'stp-connector' + (done ? ' done' : '');
  }
}

function _stpSetProgress(pct) {
  const el = document.getElementById('setup-progress-fill');
  if (el) el.style.width = pct + '%';
}

function _stpSetStatusDot(state) {
  const d = document.getElementById('setup-status-dot');
  if (!d) return;
  const cfg = {
    running: { bg:'#7c3aed', sh:'rgba(124,58,237,0.25)' },
    ok:      { bg:'#16a34a', sh:'rgba(22,163,74,0.25)' },
    error:   { bg:'#dc2626', sh:'rgba(220,38,38,0.25)' },
    idle:    { bg:'#4b5563', sh:'rgba(75,85,99,0.2)' },
  };
  const c = cfg[state] || cfg.idle;
  d.style.background = c.bg;
  d.style.boxShadow  = `0 0 0 3px ${c.sh}`;
}

function _stpLogLineClass(line) {
  if (/❌|\berror\b|\bfail\b/i.test(line)) return 'err';
  if (/⚠|\bwarn/i.test(line)) return 'warn';
  if (/✅|\bok\b|success|done|installed|установлен|завершен|запущен|активен|изменён|сгенерир|патч|patched/i.test(line)) return 'ok';
  if (/⏳|ожидани|попытк|проверка порта/i.test(line)) return 'wait';
  if (/^    /.test(line)) return 'sub';
  return '';
}

function _stpFormatLine(raw) {
  // Экранируем HTML — emoji (✅ ⚠️ ✖ ⏳ 🔗 ℹ️) отображаются нативно браузером
  let line = _escHtml(raw);
  // ❌ → ✖ (лаконичнее)
  line = line.replace(/❌/g, '✖');
  return line;
}

function _stpShowLog(n, lines, autoOpen) {
  const el = document.getElementById(`setup-step-${n}-log`);
  if (!el) return;
  el.innerHTML = lines
    .map(l => `<div class="stp-log-line ${_stpLogLineClass(l)}">${_stpFormatLine(l)}</div>`)
    .join('');
  if (autoOpen) el.classList.remove('hidden');
}

function _stpShowBtn(id, visible) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = visible ? 'flex' : 'none';
}

// ── открытие модалки ─────────────────────────────────────

function openServerSetupModal(serverId, serverName, serverIp, serverRole) {
  // Проверяем что модал существует в DOM
  const modal = document.getElementById('modal-server-setup');
  if (!modal) {
    console.error('[Setup] modal-server-setup не найден в DOM!');
    toast('Ошибка: модал настройки не найден', 'error');
    return;
  }

  _setupServerId = serverId;
  _setupServer   = { id: serverId, name: serverName, ip: serverIp, role: serverRole };

  // Заголовок — безопасно с ?. 
  const titleEl    = document.getElementById('setup-modal-title');
  const subtitleEl = document.getElementById('setup-modal-subtitle');
  const nameEl     = document.getElementById('setup-server-name');
  const ipEl       = document.getElementById('setup-ip-tag');
  if (titleEl)    titleEl.textContent    = 'Настройка сервера';
  if (subtitleEl) subtitleEl.textContent = 'Шаги выполняются последовательно';
  if (nameEl)     nameEl.textContent     = serverName || '';
  if (ipEl)       ipEl.textContent       = serverIp   || '';

  const roleTag = document.getElementById('setup-role-tag');
  if (roleTag) {
    const isRU = (serverRole || '').toUpperCase() === 'RU';
    roleTag.textContent      = isRU ? 'RU' : 'EU';
    roleTag.style.background = isRU ? '#1e3b20' : '#1e3a5f';
    roleTag.style.color      = isRU ? '#86efac' : '#93c5fd';
  }

  // Сброс шагов
  for (let i = 1; i <= 5; i++) {
    _stpSetDot(i, 'pending');
    const timeEl = document.getElementById(`setup-time-${i}`);
    if (timeEl) timeEl.textContent = '';
    const log = document.getElementById(`setup-step-${i}-log`);
    if (log) { log.innerHTML = ''; log.classList.add('hidden'); }
  }
  for (let i = 1; i <= 4; i++) _stpSetConn(i, false);

  _stpSetProgress(0);
  _stpSetStatusDot('running');
  const errBlock = document.getElementById('setup-error-block');
  if (errBlock) errBlock.classList.add('hidden');
  const resBlock = document.getElementById('setup-result-block');
  if (resBlock) resBlock.classList.add('hidden');
  _stpShowBtn('setup-btn-retry',  false);
  _stpShowBtn('setup-btn-done',   false);
  _stpShowBtn('setup-btn-cancel', true);

  modal.classList.remove('hidden');
  console.log('[Setup] Modal opened for server', serverId, serverName);
  _startSetupPolling();
}

// ── поллинг статуса ──────────────────────────────────────

function _startSetupPolling() {
  clearInterval(_setupPollTimer);
  _pollSetupStatus();
  _setupPollTimer = setInterval(_pollSetupStatus, 2000);
}

async function _pollSetupStatus() {
  if (!_setupServerId) return;
  try {
    const res = await api.request('GET', `/servers/${_setupServerId}/setup/status`);
    if (!res.ok) return;
    _renderSetupProgress(res.data);
    if (res.data.setup_status === 'done' || res.data.setup_status === 'failed') {
      clearInterval(_setupPollTimer);
      _onSetupFinished(res.data);
    }
  } catch (e) {
    console.warn('Setup poll error:', e);
  }
}

// ── рендер прогресса ─────────────────────────────────────

function _renderSetupProgress(data) {
  const currentStep = SETUP_STEP_MAP[data.setup_step] || 0;
  const lines       = Array.isArray(data.log) ? data.log : [];

  // Разбиваем лог по шагам: строка "[N]..." начинает новый шаг
  const stepLogs = { 1:[], 2:[], 3:[], 4:[], 5:[] };
  let cur = 0;
  for (const line of lines) {
    const m = line.match(/^\[(\d)\]/);
    if (m) cur = parseInt(m[1]);
    if (cur >= 1 && cur <= 5) {
      // Убираем префикс "[N] " из строки для отображения
      stepLogs[cur].push(line.replace(/^\[\d\]\s*/, ''));
    }
  }

  // Прогресс-бар: (завершённые шаги / 5) × 100, текущий добавляет 50% своего веса
  const donePct  = Math.max(0, currentStep - 1) * 20;
  const inProgPct = currentStep > 0 ? 10 : 0;
  _stpSetProgress(Math.min(donePct + inProgPct, 100));

  for (let i = 1; i <= 5; i++) {
    if (i < currentStep) {
      // Шаг завершён — всегда зелёный (предупреждения ⚠️ не делают шаг красным)
      // Красным только если есть критическая ошибка ❌ (не ⚠️)
      const hasCritErr = stepLogs[i].some(l => /❌|✖/.test(l) && !/⚠/.test(l.slice(0,3)));
      _stpSetDot(i, hasCritErr ? 'error' : 'ok');
      if (i <= 4) _stpSetConn(i, true);  // линия всегда зелёная между завершёнными шагами
    } else if (i === currentStep) {
      _stpSetDot(i, 'running');
    }
    // pending — уже выставлен при открытии, не трогаем

    if (stepLogs[i].length > 0) {
      _stpShowLog(i, stepLogs[i], i === currentStep);
    }
  }

  // Подпись прогресса
  if (currentStep > 0) {
    const labels = ['','Проверка подключения','Установка стека',
                    'Настройка безопасности','Сбор параметров сервера','Финальная проверка'];
    document.getElementById('setup-modal-subtitle').textContent =
      `Шаг ${currentStep} из 5 · ${labels[currentStep]}...`;
  }
}

// ── завершение ────────────────────────────────────────────

async function _onSetupFinished(data) {
  const success = data.setup_status === 'done';
  _stpSetStatusDot(success ? 'ok' : 'error');
  _stpSetProgress(success ? 100 : undefined);

  document.getElementById('setup-modal-title').textContent = success
    ? 'Сервер настроен' : 'Настройка завершена с ошибкой';
  document.getElementById('setup-modal-subtitle').textContent = success
    ? 'Все критичные сервисы работают' : 'Один или несколько шагов не прошли';

  // Финальный статус: расставляем точки всех шагов
  const curStep = SETUP_STEP_MAP[data.setup_step] || 0;
  for (let si = 1; si <= 5; si++) {
    if (si < curStep) {
      _stpSetDot(si, 'ok');
      if (si <= 4) _stpSetConn(si, true);
    } else if (si === curStep) {
      _stpSetDot(si, success ? 'ok' : 'error');
      if (si <= 4) _stpSetConn(si, success);
    }
  }

  _stpShowBtn('setup-btn-cancel', false);
  if (data.setup_error) {
    const errEl = document.getElementById('setup-error-text');
    if (errEl) errEl.textContent = data.setup_error;
    document.getElementById('setup-error-block').classList.remove('hidden');
  }
  _stpShowBtn('setup-btn-retry', true);
  _stpShowBtn('setup-btn-done',  true);

  // Обновляем список серверов и перезагружаем свежие данные из API
  await loadServers();

  // Принудительно перезагружаем актуальные данные сервера (ssh_user, port, sec_* флаги)
  if (_setupServerId) {
    try {
      const freshRes = await api.request('GET', `/servers/${_setupServerId}`);
      if (freshRes.ok && freshRes.data) {
        const idx = serversData.findIndex(s => s.id === _setupServerId);
        if (idx !== -1) serversData[idx] = freshRes.data;
        else serversData.push(freshRes.data);
      }
    } catch (e) { console.warn('Fresh server reload failed:', e); }
  }

  // Показываем блок итоговых параметров (SSH-доступ после харденинга)
  const resultBlock = document.getElementById('setup-result-block');
  const resultContent = document.getElementById('setup-result-content');
  if (resultBlock && resultContent && _setupServerId) {
    const srv = serversData.find(s => s.id === _setupServerId);
    if (srv) {
      const portOk = srv.ssh_port_actual || srv.ssh_port || 22;
      const userOk = srv.ssh_user_actual || srv.ssh_user || 'root';
      const hasKey = !!(srv.ssh_private_key_enc || srv.has_ssh_key);
      const secRow = (label, ok, okText, badText) =>
        `<div class="flex justify-between items-center">
          <span class="text-gray-500">${label}</span>
          <span class="${ok ? 'text-emerald-400' : 'text-yellow-400'}">${ok ? okText : badText}</span>
        </div>`;
      resultContent.innerHTML = `
        ${secRow('Пользователь', true, `<span class="font-mono">${userOk}</span>`, '')}
        ${secRow('Порт SSH', true, `<span class="font-mono">${portOk}</span>`, '')}
        ${secRow('SSH-ключ', hasKey, '✅ сохранён', '⚠ не задан')}
        ${secRow('Fail2Ban', srv.sec_fail2ban === true, '✅ активен', '⚠ неактивен')}
        ${secRow('UFW', srv.sec_ufw === true, '✅ активен', '⚠ неактивен')}
        ${secRow('Вход по паролю', srv.sec_password_login === false, '✅ отключён', '⚠ включён')}
      `;
      resultBlock.classList.remove('hidden');
    }
  }
  // Обновляем setup-бейдж на карточке сервера
  if (_setupServerId) {
    const srv = serversData.find(s => s.id === _setupServerId);
    if (srv) {
      const badge = _getSetupBadgeMeta(srv);
      const badgeEl = document.getElementById(`setup-badge-${srv.id}`);
      if (badgeEl) {
        badgeEl.style.color      = badge.color;
        badgeEl.style.background = badge.bg;
        badgeEl.style.borderColor = badge.color + '33';
        badgeEl.textContent      = badge.label;
      }
      // Обновляем online/offline точку
      const sm  = _getServerStatusMeta(srv);
      const dot = document.getElementById(`status-dot-${srv.id}`);
      const txt = document.getElementById(`status-text-${srv.id}`);
      if (dot) dot.className  = `status-dot ${sm.dot}`;
      if (txt) { txt.style.color = sm.color; txt.textContent = sm.label; }
    }
  }

  // Если карточка сервера открыта для этого же сервера — обновляем все вкладки
  if (success && _setupServerId) {
    const settingsId = parseInt(document.getElementById('settings-server-id')?.value);
    const modal = document.getElementById('modal-server-settings');
    if (settingsId === _setupServerId && modal && !modal.classList.contains('hidden')) {
      _refreshServerCard(_setupServerId);
    }
  }
}

// ── действия кнопок ──────────────────────────────────────

function toggleSetupStep(num) {
  const log = document.getElementById(`setup-step-${num}-log`);
  if (log) log.classList.toggle('hidden');
}

async function retryServerSetup() {
  if (!_setupServerId) return;
  // Сброс UI до исходного состояния
  for (let i = 1; i <= 5; i++) {
    _stpSetDot(i, 'pending');
    document.getElementById(`setup-time-${i}`).textContent = '';
    const log = document.getElementById(`setup-step-${i}-log`);
    if (log) { log.innerHTML = ''; log.classList.add('hidden'); }
  }
  for (let i = 1; i <= 4; i++) _stpSetConn(i, false);
  _stpSetProgress(0);
  _stpSetStatusDot('running');
  document.getElementById('setup-modal-title').textContent    = 'Настройка сервера';
  document.getElementById('setup-modal-subtitle').textContent = 'Шаги выполняются последовательно';
  document.getElementById('setup-error-block').classList.add('hidden');
  _stpShowBtn('setup-btn-retry', false);
  _stpShowBtn('setup-btn-done',  false);
  _stpShowBtn('setup-btn-cancel', true);

  await api.request('POST', `/servers/${_setupServerId}/setup/retry`);
  _startSetupPolling();
}

async function cancelServerSetup() {
  if (!_setupServerId) return;
  if (!confirm('Отменить настройку и удалить сервер из списка?')) return;
  clearInterval(_setupPollTimer);
  await api.request('DELETE', `/servers/${_setupServerId}/setup/cancel`);
  closeServerSetup();
  loadServers();
  toast('Сервер удалён', 'info');
}

function closeServerSetup() {
  clearInterval(_setupPollTimer);
  _setupServerId = null;
  _setupServer   = null;
  const m = document.getElementById('modal-server-setup');
  if (m) m.classList.add('hidden');
  // Скрываем блок итоговых параметров для следующего открытия
  const rb = document.getElementById('setup-result-block');
  if (rb) rb.classList.add('hidden');
  loadServers();
}



async function loadSshPassword() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  if (!serverId) return;
  const pwdInput = document.getElementById('settings-ssh-password');
  const btn = document.getElementById('btn-show-ssh-password');
  const icon = btn ? btn.querySelector('i') : null;

  // Если уже загружен — просто переключаем видимость
  if (pwdInput && pwdInput.dataset.loaded === '1') {
    const isPass = pwdInput.type === 'password';
    pwdInput.type = isPass ? 'text' : 'password';
    if (icon) { icon.className = isPass ? 'fas fa-eye-slash text-xs' : 'fas fa-eye text-xs'; }
    return;
  }

  // Загружаем расшифрованный пароль с сервера
  if (btn) btn.disabled = true;
  try {
    const res = await api.request('GET', `/servers/${serverId}/ssh-password`);
    if (res.ok && res.data?.password) {
      if (pwdInput) {
        pwdInput.value = res.data.password;
        pwdInput.type = 'text';
        pwdInput.dataset.loaded = '1';
        if (icon) icon.className = 'fas fa-eye-slash text-xs';
      }
    } else {
      toast('Пароль не найден или не задан', 'warning');
    }
  } catch(e) {
    toast('Ошибка загрузки пароля', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function copyPrivateSshKey() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  if (!serverId) return;
  const btn = document.getElementById('btn-copy-ssh-key');
  const msg = document.getElementById('copy-key-msg');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner" style="width:10px;height:10px"></span> Загружаю...'; }
  try {
    const res = await api.request('GET', `/servers/${serverId}/ssh-key`);
    if (res.ok && res.data?.private_key) {
      await navigator.clipboard.writeText(res.data.private_key);
      if (msg) { msg.textContent = '✓ Ключ скопирован в буфер обмена'; msg.style.color = '#4ade80'; msg.classList.remove('hidden'); }
      // Также вставляем в поле для наглядности
      const keyInput = document.getElementById('settings-ssh-key');
      if (keyInput) keyInput.value = res.data.private_key;
    } else {
      if (msg) { msg.textContent = '✗ Ключ не найден'; msg.style.color = '#f87171'; msg.classList.remove('hidden'); }
    }
  } catch (e) {
    if (msg) { msg.textContent = `✗ Ошибка: ${e.message}`; msg.style.color = '#f87171'; msg.classList.remove('hidden'); }
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-copy text-xs"></i> Скопировать приватный ключ'; }
    setTimeout(() => { if (msg) msg.classList.add('hidden'); }, 5000);
  }
}

window.openServerSetupModal = openServerSetupModal;
async function _refreshServerCard(serverId) {
  if (!serverId) return;
  // Перезагружаем свежие данные сервера из API
  try {
    const freshRes = await api.request('GET', `/servers/${serverId}`);
    if (freshRes.ok && freshRes.data) {
      const idx = serversData.findIndex(s => s.id === serverId);
      if (idx !== -1) serversData[idx] = freshRes.data;
      else serversData.push(freshRes.data);
    }
  } catch(e) { console.warn('_refreshServerCard reload failed:', e); }

  const srv = serversData.find(s => s.id === serverId);
  if (!srv) return;

  // Обновляем Params tab
  const userEl = document.getElementById('settings-ssh-user');
  const portEl = document.getElementById('settings-ssh-port');
  if (userEl) userEl.value = srv.ssh_user_actual || srv.ssh_user || 'root';
  if (portEl) portEl.value = srv.ssh_port_actual || srv.ssh_port || 22;

  // Пароль: если есть зашифрованный — показываем маску
  const pwdInput = document.getElementById('settings-ssh-password');
  if (pwdInput) {
    pwdInput.value = '';
    pwdInput.placeholder = srv.ssh_password_enc
      ? '••••••••  (сохранён зашифровано)'
      : 'Введите новый пароль для изменения';
  }

  // Ключ: обновляем placeholder кнопки
  const keyInput = document.getElementById('settings-ssh-key');
  if (keyInput) {
    keyInput.value = '';
    keyInput.placeholder = (srv.ssh_private_key_enc || srv.has_ssh_key)
      ? '-----BEGIN OPENSSH PRIVATE KEY-----\n(ключ сохранён, нажмите «Скопировать ключ»)'
      : 'Вставьте приватный ключ для изменения';
  }

  // Security tab: обновляем чекбоксы из sec_* полей
  const secMap = {
    'sec-fail2ban':       srv.sec_fail2ban,
    'sec-ufw':            srv.sec_ufw,
    'sec-password-login': srv.sec_password_login != null ? !srv.sec_password_login : null,
    'sec-root-login':     null,
  };
  Object.entries(secMap).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (val !== null && val !== undefined) {
      el.checked = !!val;
      el.disabled = false;
    }
  });

  // System info tab: перезагружаем через API
  loadServerInfoTab();
}

window._refreshServerCard   = _refreshServerCard;
window.toggleSetupStep      = toggleSetupStep;
window.retryServerSetup     = retryServerSetup;
window.cancelServerSetup    = cancelServerSetup;
window.closeServerSetup     = closeServerSetup;
window.closeServerSetupModal = closeServerSetup;
window.startServerSetup     = startServerSetup;


// ── startServerSetup: вызывается кнопкой "Запустить" в Actions-табе настроек ──
function startServerSetup() {
  // _currentServerId устанавливается в showServerSettings
  const sid = window._currentSettingsServerId;
  if (!sid) { toast('Не удалось определить сервер', 'error'); return; }
  const srv = serversData.find(s => s.id === sid);
  if (!srv) { toast('Сервер не найден', 'error'); return; }
  closeModal('modal-server-settings');
  openServerSetupModal(sid, srv.name, srv.ip, srv.role);
}

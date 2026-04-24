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
      const res = await api.pingServer(server.id);
      if (!res.ok) continue;
      const { reachable, latency_ms } = res.data;
      const newStatus = reachable ? 'online' : 'offline';

      const dot  = document.getElementById(`status-dot-${server.id}`);
      const txt  = document.getElementById(`status-text-${server.id}`);
      const ping = document.getElementById(`ping-val-${server.id}`);

      if (dot) dot.className = `status-dot ${newStatus}`;
      if (txt) {
        txt.className = reachable ? 'text-green-400 text-xs font-medium' : 'text-red-400 text-xs font-medium';
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

  openModal('modal-add-server');
}

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

document.getElementById('add-server-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const errEl = document.getElementById('add-server-error');
  errEl.classList.add('hidden');

  const role = form.querySelector('[name=role]:checked')?.value;
  if (!role) {
    errEl.textContent = 'Выберите роль сервера';
    errEl.classList.remove('hidden');
    return;
  }

  // Собираем данные в зависимости от роли
  const data = {
    name:     form.querySelector('[name=name]').value.trim(),
    ip:       form.querySelector('[name=ip]').value.trim(),
    country:  document.getElementById('add-server-country').value || '??',
    role,
    ssh_port: 22,
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
    toast(`Сервер ${res.data.name} добавлен`, 'success');
    loadServers();
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
  document.getElementById('settings-ssh-user').value     = server.ssh_user || 'root';
  document.getElementById('settings-ssh-port').value     = server.ssh_port || 22;
  // Sensitive fields — clear value AND placeholder
  const pwdInput = document.getElementById('settings-ssh-password');
  pwdInput.value = '';
  pwdInput.placeholder = 'Введите новый пароль для изменения';
  const keyInput = document.getElementById('settings-ssh-key');
  keyInput.value = '';
  keyInput.placeholder = 'Вставьте приватный ключ для изменения';
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

  // Security checkboxes — сбрасываем, загрузка произойдёт при переходе на вкладку security
  ['sec-password-login','sec-root-login','sec-fail2ban','sec-ufw'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.checked = false; el.disabled = true; }
  });
  const secMsg = document.getElementById('sec-status-msg');
  if (secMsg) { secMsg.textContent = ''; secMsg.classList.add('hidden'); }

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
      const map = {
        'sec-password-login': s.password_login,
        'sec-root-login':     s.root_login,
        'sec-fail2ban':       s.fail2ban,
        'sec-ufw':            s.ufw,
      };
      Object.entries(map).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) { el.checked = val; el.disabled = false; }
      });
      const secMsg = document.getElementById('sec-status-msg');
      if (secMsg) { secMsg.textContent = '✓ Статус загружен'; secMsg.classList.remove('hidden'); secMsg.style.color = '#4ade80'; }
    } else {
      const secMsg = document.getElementById('sec-status-msg');
      if (secMsg) { secMsg.textContent = 'Не удалось загрузить статус'; secMsg.classList.remove('hidden'); secMsg.style.color = '#f87171'; }
    }
  } catch (e) {
    const secMsg = document.getElementById('sec-status-msg');
    if (secMsg) { secMsg.textContent = 'Ошибка загрузки'; secMsg.classList.remove('hidden'); secMsg.style.color = '#f87171'; }
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
  const services = [
    { key: 'xray',  label: 'Xray-core',   installed: server.xray_installed },
    { key: 'awg',   label: 'AmneziaWG',   installed: server.awg_installed },
    { key: 'warp',  label: 'WARP',        installed: server.warp_installed },
    { key: 'naive', label: 'NaiveProxy',  installed: server.naiveproxy_installed },
  ];
  const svcMap = { xray: 'xray', awg: 'awg', warp: 'warp', naive: 'naiveproxy' };

  services.forEach(({ key, label, installed }) => {
    const dot    = document.getElementById(`stack-icon-${key}`);
    const status = document.getElementById(`stack-status-${key}`);
    const btns   = document.getElementById(`stack-btns-${key}`);
    const serverId = parseInt(document.getElementById('settings-server-id').value);

    if (dot) {
      dot.className = `w-2 h-2 rounded-full flex-shrink-0 ${installed ? 'bg-green-500' : 'bg-gray-600'}`;
    }
    if (status) {
      status.textContent = installed ? 'Установлен' : 'Не установлен';
    }
    if (btns) {
      if (installed) {
        btns.innerHTML = `
          <button onclick="stackRestartService('${svcMap[key]}', ${serverId})"
            class="px-2 py-1 bg-yellow-600/20 hover:bg-yellow-600/40 border border-yellow-800 rounded-lg text-xs text-yellow-300 transition" title="Рестарт">
            <i class="fas fa-rotate-right"></i>
          </button>
          <button onclick="stackUninstallService('${svcMap[key]}', '${label}', ${serverId})"
            class="px-2 py-1 bg-red-600/20 hover:bg-red-600/40 border border-red-800 rounded-lg text-xs text-red-300 transition" title="Удалить">
            <i class="fas fa-trash"></i>
          </button>`;
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
  // Бэкенд возвращает { system_info: { os, cpu_cores, memory, uptime } }
  const si = res.data.system_info || res.data;
  document.getElementById('sov-os').textContent   = si.os        || si.os_info    || '—';
  document.getElementById('sov-cpu').textContent  = si.cpu_cores || si.cpu_info   || '—';
  document.getElementById('sov-ram').textContent  = si.memory    || si.ram_info   || '—';
  document.getElementById('sov-disk').textContent = si.disk      || si.disk_info  || si.uptime || '—';
  if (hint) hint.classList.add('hidden');
}

// ── Actions tab helpers ──

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
  toast('Перезапуск сервиса...', 'info', 3000);
  const res = await api.restartServices(serverId);
  if (res.ok) toast(`✓ ${res.data.message}`, 'success', 4000);
  else toast(`Ошибка: ${res.error}`, 'error');
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

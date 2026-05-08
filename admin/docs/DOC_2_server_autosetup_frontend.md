# Автонастройка серверов — Frontend (UI + модалка логов)

## Обзор

Модалка автонастройки открывается сразу после добавления сервера (или вручную через Actions-таб).
Фронтенд опрашивает `/api/v1/servers/{id}/setup/status` каждые **2 секунды** и рендерит прогресс в реальном времени.

---

## Файлы

| Файл | Роль |
|------|------|
| `frontend/web_admin/index.html` | HTML-разметка модалки (`#modal-server-setup`) |
| `frontend/web_admin/js/servers.js` | Вся JS-логика: открытие, поллинг, рендер, кнопки |
| `frontend/web_admin/css/app.css` | CSS классы `.stp-*` для модалки |

---

## HTML-разметка модалки (`index.html`, строки 1350–1467)

```html
<!-- SETUP PROGRESS MODAL -->
<div id="modal-server-setup"
     class="hidden fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-[60] p-4"
     style="pointer-events:auto;">
  <div class="bg-[#0f1117] border border-white/8 rounded-2xl shadow-2xl w-full max-w-[520px] overflow-hidden"
       onclick="event.stopPropagation()">

    <!-- Заголовок -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-white/6">
      <div class="flex items-center gap-3 min-w-0">
        <!-- Пульсирующая точка статуса (фиолетовый → зелёный/красный по завершении) -->
        <span id="setup-status-dot" style="
          width:9px; height:9px; border-radius:50%; flex-shrink:0;
          background:#7c3aed; box-shadow:0 0 0 3px rgba(124,58,237,.25);
          transition:background .4s, box-shadow .4s; display:inline-block;"></span>
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <span id="setup-modal-title" class="text-sm font-semibold text-white">Настройка сервера</span>
            <!-- Бейдж EU/RU — синий для EU, зелёный для RU -->
            <span id="setup-role-tag"
                  class="text-[10px] font-bold px-2 py-0.5 rounded-md"
                  style="background:#1e3a5f; color:#93c5fd"></span>
          </div>
          <p id="setup-modal-subtitle"
             class="text-[11px] text-gray-500 mt-0.5 truncate">Шаги выполняются последовательно</p>
        </div>
      </div>
      <!-- Имя сервера + IP справа -->
      <div class="flex items-center gap-2 flex-shrink-0 ml-3">
        <span id="setup-server-name" class="text-xs font-medium text-gray-300 hidden sm:block"></span>
        <span id="setup-ip-tag" class="font-mono text-[10px] text-gray-500 bg-white/5 px-2 py-0.5 rounded-md"></span>
      </div>
    </div>

    <!-- Прогресс-бар (тонкая линия под заголовком) -->
    <div class="h-[2px] bg-white/5">
      <div id="setup-progress-fill" class="h-full rounded-full transition-all duration-700"
           style="width:0%; background:linear-gradient(90deg,#6d28d9,#7c3aed,#8b5cf6)"></div>
    </div>

    <!-- Timeline шагов (5 точек + 4 соединительные линии) -->
    <div class="px-6 pt-5 pb-3">
      <div class="flex items-center">

        <div class="flex flex-col items-center">
          <div class="stp-dot stp-pending" id="setup-dot-1"></div>
          <span class="text-[9px] text-gray-600 mt-1.5 whitespace-nowrap">Связь</span>
        </div>
        <div class="stp-connector flex-1" id="setup-conn-1"></div>

        <div class="flex flex-col items-center">
          <div class="stp-dot stp-pending" id="setup-dot-2"></div>
          <span class="text-[9px] text-gray-600 mt-1.5 whitespace-nowrap">Стек</span>
        </div>
        <div class="stp-connector flex-1" id="setup-conn-2"></div>

        <div class="flex flex-col items-center">
          <div class="stp-dot stp-pending" id="setup-dot-3"></div>
          <span class="text-[9px] text-gray-600 mt-1.5 whitespace-nowrap">Безоп.</span>
        </div>
        <div class="stp-connector flex-1" id="setup-conn-3"></div>

        <div class="flex flex-col items-center">
          <div class="stp-dot stp-pending" id="setup-dot-4"></div>
          <span class="text-[9px] text-gray-600 mt-1.5 whitespace-nowrap">Параметры</span>
        </div>
        <div class="stp-connector flex-1" id="setup-conn-4"></div>

        <div class="flex flex-col items-center">
          <div class="stp-dot stp-pending" id="setup-dot-5"></div>
          <span class="text-[9px] text-gray-600 mt-1.5 whitespace-nowrap">Проверка</span>
        </div>

      </div>
    </div>

    <!-- Accordion-логи по шагам (прокручиваемая область) -->
    <div class="px-6 space-y-1 max-h-56 overflow-y-auto pb-1 scrollbar-thin">
      <div id="setup-step-1-log" class="hidden stp-log-block"></div>
      <div id="setup-step-2-log" class="hidden stp-log-block"></div>
      <div id="setup-step-3-log" class="hidden stp-log-block"></div>
      <div id="setup-step-4-log" class="hidden stp-log-block"></div>
      <div id="setup-step-5-log" class="hidden stp-log-block"></div>
    </div>

    <!-- Скрытые элементы тайминга (совместимость с JS) -->
    <div class="hidden">
      <span id="setup-time-1"></span><span id="setup-time-2"></span>
      <span id="setup-time-3"></span><span id="setup-time-4"></span>
      <span id="setup-time-5"></span>
    </div>

    <!-- Итоговые параметры доступа (показывается после done) -->
    <div id="setup-result-block" class="hidden mx-6 mb-2 rounded-xl border border-white/6 bg-white/3 overflow-hidden">
      <div class="px-4 py-2.5 border-b border-white/6">
        <span class="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
          Сохранённые параметры доступа
        </span>
      </div>
      <div id="setup-result-content" class="px-4 py-3 space-y-1.5 text-xs"></div>
    </div>

    <!-- Блок критической ошибки (показывается при failed) -->
    <div id="setup-error-block"
         class="hidden mx-6 mb-2 px-4 py-3 bg-red-950/50 border border-red-800/60 rounded-xl">
      <div class="flex items-start gap-2">
        <i class="fas fa-triangle-exclamation text-red-400 text-xs mt-0.5 flex-shrink-0"></i>
        <span id="setup-error-text" class="text-xs text-red-300 break-all"></span>
      </div>
    </div>

    <!-- Кнопки управления -->
    <div class="px-6 pb-5 pt-2 flex gap-2">
      <!-- Отмена (видна во время выполнения) -->
      <button id="setup-btn-cancel" onclick="cancelServerSetup()"
        class="py-2.5 px-5 rounded-xl text-sm font-medium transition flex items-center justify-center gap-2 h-10">
        <i class="fas fa-xmark text-xs"></i> Отмена
      </button>
      <!-- Повторить (видна после failed) -->
      <button id="setup-btn-retry" onclick="retryServerSetup()"
        style="display:none"
        class="flex-1 py-2.5 bg-amber-700/80 hover:bg-amber-600 rounded-xl text-sm font-medium text-white transition flex items-center justify-center gap-2">
        <i class="fas fa-rotate-right text-xs"></i> Повторить
      </button>
      <!-- Закрыть (видна после done/failed) -->
      <button id="setup-btn-done" onclick="closeServerSetup()"
        style="display:none"
        class="flex-1 py-2.5 bg-green-700/80 hover:bg-green-600 rounded-xl text-sm font-medium text-white transition flex items-center justify-center gap-2">
        <i class="fas fa-check text-xs"></i> Закрыть
      </button>
    </div>

  </div>
</div>
```

---

## CSS стили (`app.css`, строки 488–560)

```css
/* ── Setup Progress Modal ─────────────────────────────── */

/* Точки-шаги на timeline */
.stp-dot {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; flex-shrink: 0;
  border: 2px solid #374151;
  background: #111827;
  color: #6b7280;
  transition: all 0.3s ease;
  position: relative; z-index: 1;
}
/* Состояния точек */
.stp-dot.stp-pending { border-color: #374151; color: #4b5563; }
.stp-dot.stp-running { border-color: #7c3aed; color: #a78bfa; background: #1e1040;
  box-shadow: 0 0 0 3px rgba(124,58,237,0.2); }
.stp-dot.stp-ok      { border-color: #16a34a; color: #4ade80; background: #052e16; }
.stp-dot.stp-error   { border-color: #dc2626; color: #f87171; background: #2a0a0a; }
.stp-dot.stp-warn    { border-color: #d97706; color: #fbbf24; background: #1c1206; }

/* Анимация спиннера для running */
.stp-spin { animation: stp-rotate 1s linear infinite; }
@keyframes stp-rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Соединительные линии между точками */
.stp-connector {
  flex: 1; height: 2px; background: #1f2937;
  transition: background 0.4s ease;
  margin: 0 2px;
}
.stp-connector.done { background: #16a34a; }  /* зелёная после завершения шага */

/* Блок лога (моноширинный, тёмный фон) */
.stp-log-block {
  background: #030712;
  border: 1px solid #1f2937;
  border-radius: 8px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11.5px;
  line-height: 1.7;
  max-height: 260px;
  overflow-y: auto;
}

/* Строки лога */
.stp-log-line {
  color: #8b95a6;
  display: flex; align-items: baseline; gap: 6px;
  padding: 1px 0;
}
.stp-log-line.ok   { color: #4ade80; }  /* ✅ зелёный */
.stp-log-line.err  { color: #f87171; }  /* ❌ красный */
.stp-log-line.warn { color: #fbbf24; }  /* ⚠️ жёлтый */
.stp-log-line.wait { color: #818cf8; }  /* ⏳ фиолетовый */
.stp-log-line.sub  { color: #6b7280; padding-left: 18px; font-size: 11px; } /* отступ для sub-строк */

/* Кнопка Отмена */
#setup-btn-cancel {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(239,68,68,0.3);
  color: #f87171; height: 40px; min-height: 40px; box-sizing: border-box;
}
#setup-btn-cancel:hover {
  background: rgba(239,68,68,0.12);
  border-color: rgba(239,68,68,0.5);
  color: #fca5a5;
}

/* Пульсирующая анимация для точек ⏳ */
@keyframes stp-pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.4;transform:scale(0.7)} }
.stp-spin-dot { animation: stp-pulse 1.2s ease-in-out infinite; }
```

---

## JavaScript (`servers.js`, строки 1479–1999)

### Константы и состояние

```javascript
let _setupServerId  = null;   // ID сервера, для которого открыта модалка
let _setupPollTimer = null;   // setInterval handle
let _setupServer    = null;   // { id, name, ip, role }

// Маппинг step1..step5 -> номер 1..5
const SETUP_STEP_MAP = { step1:1, step2:2, step3:3, step4:4, step5:5 };

const SETUP_STEP_LABELS = {
  1: 'Проверка подключения',
  2: 'Установка стека',
  3: 'Настройка безопасности',
  4: 'Сбор параметров сервера',
  5: 'Финальная проверка',
};
```

---

### Вспомогательные UI-функции

```javascript
// Экранирование HTML (emoji отображаются нативно)
function _escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Установить состояние точки: 'pending' | 'running' | 'ok' | 'error' | 'warn'
function _stpSetDot(n, state) {
  const dot = document.getElementById(`setup-dot-${n}`);
  if (!dot) return;
  dot.className = `stp-dot stp-${state}`;
  const iconMap = {
    pending: 'fa-minus',
    running: 'fa-circle-notch stp-spin',  // вращающийся спиннер
    ok:      'fa-check',
    error:   'fa-xmark',
    warn:    'fa-triangle-exclamation',
  };
  dot.innerHTML = `<i class="fas ${iconMap[state] || 'fa-minus'}"></i>`;
}

// Закрасить соединительную линию между шагами
function _stpSetConn(n, done) {
  const c = document.getElementById(`setup-conn-${n}`);
  if (c) c.className = 'stp-connector' + (done ? ' done' : '');
}

// Установить ширину прогресс-бара (0–100%)
function _stpSetProgress(pct) {
  const el = document.getElementById('setup-progress-fill');
  if (el) el.style.width = pct + '%';
}

// Цвет статусной точки в заголовке
function _stpSetStatusDot(state) {
  const d = document.getElementById('setup-status-dot');
  if (!d) return;
  const cfg = {
    running: { bg:'#7c3aed', sh:'rgba(124,58,237,0.25)' },  // фиолетовый
    ok:      { bg:'#16a34a', sh:'rgba(22,163,74,0.25)' },   // зелёный
    error:   { bg:'#dc2626', sh:'rgba(220,38,38,0.25)' },   // красный
    idle:    { bg:'#4b5563', sh:'rgba(75,85,99,0.2)' },     // серый
  };
  const c = cfg[state] || cfg.idle;
  d.style.background = c.bg;
  d.style.boxShadow  = `0 0 0 3px ${c.sh}`;
}

// Определить CSS-класс строки лога по содержимому
function _stpLogLineClass(line) {
  if (/❌|\berror\b|\bfail\b/i.test(line)) return 'err';
  if (/⚠|\bwarn/i.test(line))             return 'warn';
  if (/✅|\bok\b|success|done|installed|установлен|завершен|запущен|активен|
       изменён|сгенерир|патч|patched/i.test(line)) return 'ok';
  if (/⏳|ожидани|попытк|проверка порта/i.test(line)) return 'wait';
  if (/^    /.test(line)) return 'sub';  // строки с отступом — sub-строки
  return '';
}

// Форматировать строку лога (экранировать HTML, заменить ❌ на ✖)
function _stpFormatLine(raw) {
  let line = _escHtml(raw);
  line = line.replace(/❌/g, '✖');
  return line;
}

// Отрисовать строки лога в блоке шага N
function _stpShowLog(n, lines, autoOpen) {
  const el = document.getElementById(`setup-step-${n}-log`);
  if (!el) return;
  el.innerHTML = lines
    .map(l => `<div class="stp-log-line ${_stpLogLineClass(l)}">${_stpFormatLine(l)}</div>`)
    .join('');
  if (autoOpen) el.classList.remove('hidden');
}

// Показать/скрыть кнопку по id
function _stpShowBtn(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? 'flex' : 'none';
}
```

---

### Открытие модалки

```javascript
function openServerSetupModal(serverId, serverName, serverIp, serverRole) {
  const modal = document.getElementById('modal-server-setup');
  if (!modal) { toast('Ошибка: модал настройки не найден', 'error'); return; }

  _setupServerId = serverId;
  _setupServer   = { id: serverId, name: serverName, ip: serverIp, role: serverRole };

  // Заголовок
  document.getElementById('setup-modal-title').textContent    = 'Настройка сервера';
  document.getElementById('setup-modal-subtitle').textContent = 'Шаги выполняются последовательно';
  document.getElementById('setup-server-name').textContent    = serverName || '';
  document.getElementById('setup-ip-tag').textContent         = serverIp   || '';

  // Бейдж роли: RU (тёмно-зелёный) или EU (тёмно-синий)
  const roleTag = document.getElementById('setup-role-tag');
  if (roleTag) {
    const isRU = (serverRole || '').toUpperCase() === 'RU';
    roleTag.textContent      = isRU ? 'RU' : 'EU';
    roleTag.style.background = isRU ? '#1e3b20' : '#1e3a5f';
    roleTag.style.color      = isRU ? '#86efac' : '#93c5fd';
  }

  // Сброс всех шагов в pending
  for (let i = 1; i <= 5; i++) {
    _stpSetDot(i, 'pending');
    const log = document.getElementById(`setup-step-${i}-log`);
    if (log) { log.innerHTML = ''; log.classList.add('hidden'); }
  }
  for (let i = 1; i <= 4; i++) _stpSetConn(i, false);

  _stpSetProgress(0);
  _stpSetStatusDot('running');
  document.getElementById('setup-error-block').classList.add('hidden');
  document.getElementById('setup-result-block').classList.add('hidden');
  _stpShowBtn('setup-btn-retry',  false);
  _stpShowBtn('setup-btn-done',   false);
  _stpShowBtn('setup-btn-cancel', true);

  modal.classList.remove('hidden');
  _startSetupPolling();
}
```

---

### Поллинг статуса (каждые 2 секунды)

```javascript
function _startSetupPolling() {
  clearInterval(_setupPollTimer);
  _pollSetupStatus();  // сразу
  _setupPollTimer = setInterval(_pollSetupStatus, 2000);
}

async function _pollSetupStatus() {
  if (!_setupServerId) return;
  try {
    const res = await api.request('GET', `/servers/${_setupServerId}/setup/status`);
    if (!res.ok) return;
    _renderSetupProgress(res.data);
    // Останавливаем поллинг при завершении
    if (res.data.setup_status === 'done' || res.data.setup_status === 'failed') {
      clearInterval(_setupPollTimer);
      _onSetupFinished(res.data);
    }
  } catch (e) {
    console.warn('Setup poll error:', e);
  }
}
```

---

### Рендер прогресса

```javascript
function _renderSetupProgress(data) {
  const currentStep = SETUP_STEP_MAP[data.setup_step] || 0;
  const lines       = Array.isArray(data.log) ? data.log : [];

  // Разбиваем лог по шагам: строка "[N] текст" начинает шаг N
  const stepLogs = { 1:[], 2:[], 3:[], 4:[], 5:[] };
  let cur = 0;
  for (const line of lines) {
    const m = line.match(/^\[(\d)\]/);
    if (m) cur = parseInt(m[1]);
    if (cur >= 1 && cur <= 5) {
      stepLogs[cur].push(line.replace(/^\[\d\]\s*/, ''));  // убираем префикс "[N] "
    }
  }

  // Прогресс-бар: каждый завершённый шаг = 20%, текущий +10%
  const donePct   = Math.max(0, currentStep - 1) * 20;
  const inProgPct = currentStep > 0 ? 10 : 0;
  _stpSetProgress(Math.min(donePct + inProgPct, 100));

  // Состояние точек
  for (let i = 1; i <= 5; i++) {
    if (i < currentStep) {
      // Шаг завершён: красный только если есть ❌ (не ⚠️)
      const hasCritErr = stepLogs[i].some(l => /❌|✖/.test(l) && !/⚠/.test(l.slice(0,3)));
      _stpSetDot(i, hasCritErr ? 'error' : 'ok');
      if (i <= 4) _stpSetConn(i, true);
    } else if (i === currentStep) {
      _stpSetDot(i, 'running');  // текущий — спиннер
    }
    // pending — уже выставлен при открытии, не трогаем

    if (stepLogs[i].length > 0) {
      _stpShowLog(i, stepLogs[i], i === currentStep);  // autoOpen только текущего
    }
  }

  // Подпись под заголовком
  if (currentStep > 0) {
    const labels = ['','Проверка подключения','Установка стека',
                    'Настройка безопасности','Сбор параметров сервера','Финальная проверка'];
    document.getElementById('setup-modal-subtitle').textContent =
      `Шаг ${currentStep} из 5 · ${labels[currentStep]}...`;
  }
}
```

---

### Завершение (done / failed)

```javascript
async function _onSetupFinished(data) {
  const success = data.setup_status === 'done';

  // Статусная точка заголовка
  _stpSetStatusDot(success ? 'ok' : 'error');
  if (success) _stpSetProgress(100);

  // Заголовок
  document.getElementById('setup-modal-title').textContent = success
    ? 'Сервер настроен' : 'Настройка завершена с ошибкой';
  document.getElementById('setup-modal-subtitle').textContent = success
    ? 'Все критичные сервисы работают' : 'Один или несколько шагов не прошли';

  // Финальные точки шагов
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

  // Кнопки
  _stpShowBtn('setup-btn-cancel', false);
  _stpShowBtn('setup-btn-retry', true);
  _stpShowBtn('setup-btn-done',  true);

  // Блок ошибки
  if (data.setup_error) {
    document.getElementById('setup-error-text').textContent = data.setup_error;
    document.getElementById('setup-error-block').classList.remove('hidden');
  }

  // Обновляем список серверов и получаем свежие данные
  await loadServers();
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

  // Показываем итоговые параметры доступа (SSH user, port, ключ, security)
  const resultBlock   = document.getElementById('setup-result-block');
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
        ${secRow('Порт SSH',     true, `<span class="font-mono">${portOk}</span>`, '')}
        ${secRow('SSH-ключ',     hasKey,                 '✅ сохранён',  '⚠ не задан')}
        ${secRow('Fail2Ban',     srv.sec_fail2ban===true,'✅ активен',   '⚠ неактивен')}
        ${secRow('UFW',          srv.sec_ufw===true,     '✅ активен',   '⚠ неактивен')}
        ${secRow('Вход по паролю', srv.sec_password_login===false, '✅ отключён', '⚠ включён')}
      `;
      resultBlock.classList.remove('hidden');
    }
  }

  // Обновляем бейдж на карточке сервера
  if (_setupServerId) {
    const srv = serversData.find(s => s.id === _setupServerId);
    if (srv) {
      const badge   = _getSetupBadgeMeta(srv);
      const badgeEl = document.getElementById(`setup-badge-${srv.id}`);
      if (badgeEl) {
        badgeEl.style.color       = badge.color;
        badgeEl.style.background  = badge.bg;
        badgeEl.style.borderColor = badge.color + '33';
        badgeEl.textContent       = badge.label;
      }
    }
  }

  // Если открыта карточка этого же сервера — обновляем вкладки
  if (success && _setupServerId) {
    const settingsId = parseInt(document.getElementById('settings-server-id')?.value);
    const settingsModal = document.getElementById('modal-server-settings');
    if (settingsId === _setupServerId && settingsModal && !settingsModal.classList.contains('hidden')) {
      _refreshServerCard(_setupServerId);
    }
  }
}
```

---

### Кнопки управления

```javascript
// Переключение видимости лога шага (клик по заголовку шага)
function toggleSetupStep(num) {
  const log = document.getElementById(`setup-step-${num}-log`);
  if (log) log.classList.toggle('hidden');
}

// Повторить настройку: сброс UI + POST /setup/retry
async function retryServerSetup() {
  if (!_setupServerId) return;
  // Сброс UI
  for (let i = 1; i <= 5; i++) {
    _stpSetDot(i, 'pending');
    const log = document.getElementById(`setup-step-${i}-log`);
    if (log) { log.innerHTML = ''; log.classList.add('hidden'); }
  }
  for (let i = 1; i <= 4; i++) _stpSetConn(i, false);
  _stpSetProgress(0);
  _stpSetStatusDot('running');
  document.getElementById('setup-modal-title').textContent    = 'Настройка сервера';
  document.getElementById('setup-modal-subtitle').textContent = 'Шаги выполняются последовательно';
  document.getElementById('setup-error-block').classList.add('hidden');
  _stpShowBtn('setup-btn-retry',  false);
  _stpShowBtn('setup-btn-done',   false);
  _stpShowBtn('setup-btn-cancel', true);

  await api.request('POST', `/servers/${_setupServerId}/setup/retry`);
  _startSetupPolling();
}

// Отмена: удаляет сервер из БД
async function cancelServerSetup() {
  if (!_setupServerId) return;
  if (!confirm('Отменить настройку и удалить сервер из списка?')) return;
  clearInterval(_setupPollTimer);
  await api.request('DELETE', `/servers/${_setupServerId}/setup/cancel`);
  closeServerSetup();
  loadServers();
  toast('Сервер удалён', 'info');
}

// Закрыть модалку
function closeServerSetup() {
  clearInterval(_setupPollTimer);
  _setupServerId = null;
  _setupServer   = null;
  document.getElementById('modal-server-setup').classList.add('hidden');
  document.getElementById('setup-result-block').classList.add('hidden');
  loadServers();
}

// Запуск из Actions-таба карточки сервера
function startServerSetup() {
  const sid = window._currentSettingsServerId;
  if (!sid) { toast('Не удалось определить сервер', 'error'); return; }
  const srv = serversData.find(s => s.id === sid);
  if (!srv) { toast('Сервер не найден', 'error'); return; }
  closeModal('modal-server-settings');
  openServerSetupModal(sid, srv.name, srv.ip, srv.role);
}
```

---

### Обновление карточки сервера после настройки

```javascript
async function _refreshServerCard(serverId) {
  // Перезагружаем данные из API
  const freshRes = await api.request('GET', `/servers/${serverId}`);
  if (freshRes.ok && freshRes.data) {
    const idx = serversData.findIndex(s => s.id === serverId);
    if (idx !== -1) serversData[idx] = freshRes.data;
  }

  const srv = serversData.find(s => s.id === serverId);
  if (!srv) return;

  // Params tab: SSH user и port (берём actual если есть)
  document.getElementById('settings-ssh-user').value =
    srv.ssh_user_actual || srv.ssh_user || 'root';
  document.getElementById('settings-ssh-port').value =
    srv.ssh_port_actual || srv.ssh_port || 22;

  // Password: очищаем поле, показываем placeholder
  const pwdInput = document.getElementById('settings-ssh-password');
  if (pwdInput) {
    pwdInput.value = '';
    delete pwdInput.dataset.loaded;   // сброс кеша — следующий клик глаза перезагрузит
    pwdInput.type = 'password';
    pwdInput.placeholder = srv.ssh_password_enc
      ? '••••••••  (сохранён зашифровано)'
      : 'Введите новый пароль для изменения';
  }

  // SSH ключ: placeholder
  const keyInput = document.getElementById('settings-ssh-key');
  if (keyInput) {
    keyInput.value = '';
    keyInput.placeholder = (srv.ssh_private_key_enc || srv.has_ssh_key)
      ? '-----BEGIN OPENSSH PRIVATE KEY-----\n(ключ сохранён, нажмите «Скопировать ключ»)'
      : 'Вставьте приватный ключ для изменения';
  }

  // Security tab: чекбоксы из sec_* полей
  const checks = {
    'sec-fail2ban':       srv.sec_fail2ban,
    'sec-ufw':            srv.sec_ufw,
    'sec-password-login': srv.sec_password_login != null ? !srv.sec_password_login : null,
  };
  Object.entries(checks).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el && val !== null && val !== undefined) {
      el.checked = !!val;
      el.disabled = false;
    }
  });

  loadServerInfoTab();  // обновляем System info
}
```

---

### Кнопка "показать пароль" (глаз)

```javascript
async function loadSshPassword() {
  const serverId = parseInt(document.getElementById('settings-server-id').value);
  const pwdInput = document.getElementById('settings-ssh-password');
  const btn  = document.getElementById('btn-show-ssh-password');
  const icon = btn ? btn.querySelector('i') : null;

  // Если уже загружен — просто переключаем видимость
  if (pwdInput && pwdInput.dataset.loaded === '1') {
    const isPass = pwdInput.type === 'password';
    pwdInput.type = isPass ? 'text' : 'password';
    if (icon) icon.className = isPass ? 'fas fa-eye-slash text-xs' : 'fas fa-eye text-xs';
    return;
  }

  // Загружаем с бэкенда (GET /servers/{id}/ssh-password)
  if (btn) btn.disabled = true;
  try {
    const res = await api.request('GET', `/servers/${serverId}/ssh-password`);
    if (res.ok && res.data?.password) {
      pwdInput.value = res.data.password;
      pwdInput.type  = 'text';
      pwdInput.dataset.loaded = '1';
      if (icon) icon.className = 'fas fa-eye-slash text-xs';
    } else {
      toast('Пароль не найден или не задан', 'warning');
    }
  } catch(e) {
    toast('Ошибка загрузки пароля', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}
```

---

## Поток данных: от клика до отображения лога

```
Пользователь нажимает "Добавить сервер"
    ↓
POST /api/v1/servers/{id}/setup
    ↓ (background task)
run_server_setup(server_id) — пишет в server.setup_log, setup_step, setup_status
    ↓
openServerSetupModal(id, name, ip, role)  ← вызывается сразу после POST
    ↓
_startSetupPolling()  ← setInterval 2000ms
    ↓ каждые 2 сек
GET /api/v1/servers/{id}/setup/status
    → { setup_step, setup_status, setup_error, log: [...строки...] }
    ↓
_renderSetupProgress(data)
    ├── Разбивает лог по шагам ([1]...[5])
    ├── Обновляет точки timeline (_stpSetDot)
    ├── Обновляет прогресс-бар (_stpSetProgress)
    └── Рендерит строки лога (_stpShowLog) с цветами ok/err/warn/wait/sub
    ↓ при status === 'done' | 'failed'
clearInterval + _onSetupFinished(data)
    ├── Меняет заголовок и статусную точку
    ├── Показывает блок итоговых параметров (ssh user, port, ключ, security)
    ├── Показывает блок ошибки (при failed)
    ├── Показывает кнопки Повторить / Закрыть
    └── Обновляет карточку сервера в списке
```

---

## Цвета строк лога

| Паттерн в строке | CSS-класс | Цвет |
|-----------------|-----------|------|
| `❌`, `error`, `fail` | `.err` | `#f87171` (красный) |
| `⚠`, `warn` | `.warn` | `#fbbf24` (жёлтый) |
| `✅`, `ok`, `установлен`, `запущен` | `.ok` | `#4ade80` (зелёный) |
| `⏳`, `ожидани`, `попытк` | `.wait` | `#818cf8` (фиолетовый) |
| Строка начинается с 4 пробелов | `.sub` | `#6b7280` (серый, отступ) |
| Остальные | — | `#8b95a6` (серо-голубой) |

---

## Состояния точек timeline

| `stp-*` класс | Иконка FA | Цвет рамки | Когда |
|--------------|-----------|------------|-------|
| `stp-pending` | `fa-minus` | серый | до начала шага |
| `stp-running` | `fa-circle-notch stp-spin` | фиолетовый | текущий шаг |
| `stp-ok` | `fa-check` | зелёный | шаг завершён успешно |
| `stp-error` | `fa-xmark` | красный | критическая ошибка в шаге |
| `stp-warn` | `fa-triangle-exclamation` | жёлтый | (резерв, не используется) |

/**
 * Users tab — CRUD, edit panel per card, TOTP re-bind.
 * Visible only to Creator and Главный Админ.
 */

const ROLE_LABELS = {
  creator:    { text: 'Creator',        cls: 'bg-purple-900/50 text-purple-300 border-purple-700' },
  head_admin: { text: 'Главный Админ',  cls: 'bg-blue-900/50 text-blue-300 border-blue-700' },
  admin:      { text: 'Админ',          cls: 'bg-gray-800 text-gray-300 border-gray-600' },
};

function roleBadge(role) {
  const r = ROLE_LABELS[role] || { text: role, cls: 'bg-gray-800 text-gray-400 border-gray-600' };
  return `<span class="px-2 py-0.5 rounded text-xs font-medium border ${r.cls}">${r.text}</span>`;
}

// Track which card's edit panel is open
let _openEditId = null;

// ─── Load & render ────────────────────────────────────────────────────────────

async function loadUsers() {
  const grid  = document.getElementById('users-list');
  const empty = document.getElementById('users-empty');
  if (!grid) return;

  grid.innerHTML = '<div class="col-span-full text-center py-8 text-gray-500"><i class="fas fa-spinner fa-spin mr-2"></i>Загрузка...</div>';

  const res = await api.getUsers();
  if (!res.ok) {
    grid.innerHTML = `<div class="col-span-full text-center py-8 text-red-400"><i class="fas fa-circle-exclamation mr-2"></i>${escapeHtml(res.error)}</div>`;
    return;
  }

  const users = res.data || [];
  if (users.length === 0) {
    grid.innerHTML = '';
    empty?.classList.remove('hidden');
    return;
  }
  empty?.classList.add('hidden');

  const currentUser = api.getUser();
  const myRole = currentUser?.role;

  grid.innerHTML = users.map(u => renderUserCard(u, currentUser, myRole)).join('');
}

function renderUserCard(u, currentUser, myRole) {
  const isMe = currentUser && u.username === currentUser.username;
  // Can edit if: actor can manage AND target is not creator (unless actor is creator)
  const canEdit = !isMe && !(u.role === 'creator');

  const createdAt = u.created_at || '—';

  return `
  <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden ${!u.is_active ? 'opacity-60' : ''}">
    <!-- Card header -->
    <div class="p-4 flex items-center justify-between gap-2">
      <div class="flex items-center gap-3 min-w-0">
        <div class="w-9 h-9 rounded-lg flex-shrink-0 flex items-center justify-center
          ${u.role === 'creator' ? 'bg-purple-700' : u.role === 'head_admin' ? 'bg-blue-700' : 'bg-gray-700'}">
          <i class="fas ${u.role === 'creator' ? 'fa-crown' : 'fa-user-shield'} text-white text-sm"></i>
        </div>
        <div class="min-w-0">
          <div class="font-semibold text-white text-sm truncate flex items-center gap-1.5">
            ${escapeHtml(u.username)}
            ${isMe ? '<span class="text-xs text-brand-400">(вы)</span>' : ''}
          </div>
          <div class="text-xs text-gray-500">${createdAt}</div>
        </div>
      </div>
      ${canEdit ? `
      <button onclick="toggleEditPanel(${u.id})"
        class="flex-shrink-0 px-2.5 py-1.5 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs transition flex items-center gap-1.5"
        id="edit-btn-${u.id}">
        <i class="fas fa-pen text-xs"></i>
        <span>Изменить</span>
      </button>` : ''}
    </div>

    <!-- Badges row -->
    <div class="px-4 pb-3 flex items-center gap-2 flex-wrap">
      ${roleBadge(u.role)}
      <span class="px-2 py-0.5 rounded text-xs border ${u.is_active
        ? 'bg-green-900/30 text-green-400 border-green-800'
        : 'bg-red-900/30 text-red-400 border-red-800'}">
        ${u.is_active ? 'Активен' : 'Отключён'}
      </span>
      <span class="px-2 py-0.5 rounded text-xs border ${u.totp_enabled
        ? 'bg-emerald-900/30 text-emerald-400 border-emerald-800'
        : 'bg-yellow-900/30 text-yellow-400 border-yellow-800'}">
        <i class="fas fa-shield-halved text-xs mr-1"></i>${u.totp_enabled ? '2FA ✓' : '2FA —'}
      </span>
    </div>

    <!-- Edit panel (collapsed by default) -->
    ${canEdit ? `
    <div id="edit-panel-${u.id}" class="hidden border-t border-gray-800 bg-gray-950/50">
      ${renderEditPanel(u)}
    </div>` : ''}
  </div>`;
}

function renderEditPanel(u) {
  return `
  <div class="p-4 space-y-3">

    <!-- Change login -->
    <div>
      <label class="text-xs text-gray-500 uppercase tracking-wide">Логин</label>
      <div class="flex gap-2 mt-1">
        <input id="ep-username-${u.id}" type="text" value="${escapeHtml(u.username)}"
          class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500 transition">
        <button onclick="saveUsername(${u.id})"
          class="px-3 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs text-white transition whitespace-nowrap">
          Сохранить
        </button>
      </div>
    </div>

    <!-- Change password -->
    <div>
      <label class="text-xs text-gray-500 uppercase tracking-wide">Новый пароль</label>
      <div class="flex gap-2 mt-1">
        <input id="ep-password-${u.id}" type="password" placeholder="Новый пароль"
          class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500 transition">
        <button onclick="savePassword(${u.id})"
          class="px-3 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs text-white transition whitespace-nowrap">
          Сохранить
        </button>
      </div>
    </div>

    <div class="border-t border-gray-800 pt-3 flex flex-wrap gap-2">

      <!-- Enable/Disable -->
      <button onclick="doToggleUser(${u.id}, ${u.is_active})"
        class="flex-1 min-w-0 py-2 text-xs rounded-lg border transition
          ${u.is_active
            ? 'bg-red-900/20 border-red-800 text-red-400 hover:bg-red-900/40'
            : 'bg-green-900/20 border-green-800 text-green-400 hover:bg-green-900/40'}">
        <i class="fas ${u.is_active ? 'fa-ban' : 'fa-check'} mr-1"></i>
        ${u.is_active ? 'Отключить' : 'Включить'}
      </button>

      <!-- Rebind TOTP -->
      <button onclick="doRebindTotp(${u.id}, '${escapeHtml(u.username)}')"
        class="flex-1 min-w-0 py-2 text-xs rounded-lg border bg-yellow-900/20 border-yellow-800 text-yellow-400 hover:bg-yellow-900/40 transition">
        <i class="fas fa-rotate mr-1"></i>Сброс 2FA
      </button>

      <!-- Delete -->
      <button onclick="doDeleteUser(${u.id}, '${escapeHtml(u.username)}')"
        class="py-2 px-3 text-xs rounded-lg border bg-gray-800 border-gray-700 text-gray-400 hover:text-red-400 hover:border-red-800 transition">
        <i class="fas fa-trash"></i>
      </button>

    </div>

    <!-- Inline error -->
    <div id="ep-error-${u.id}" class="hidden p-2 bg-red-900/40 border border-red-800 rounded-lg text-red-300 text-xs"></div>
  </div>`;
}

// ─── Toggle edit panel ────────────────────────────────────────────────────────

function toggleEditPanel(userId) {
  const panel = document.getElementById(`edit-panel-${userId}`);
  const btn   = document.getElementById(`edit-btn-${userId}`);
  if (!panel) return;

  const isOpen = !panel.classList.contains('hidden');

  // Close previously open panel
  if (_openEditId && _openEditId !== userId) {
    document.getElementById(`edit-panel-${_openEditId}`)?.classList.add('hidden');
    const prevBtn = document.getElementById(`edit-btn-${_openEditId}`);
    if (prevBtn) prevBtn.querySelector('span').textContent = 'Изменить';
  }

  if (isOpen) {
    panel.classList.add('hidden');
    btn.querySelector('span').textContent = 'Изменить';
    _openEditId = null;
  } else {
    panel.classList.remove('hidden');
    btn.querySelector('span').textContent = 'Свернуть';
    _openEditId = userId;
  }
}

// ─── Edit actions ─────────────────────────────────────────────────────────────

function showEpError(userId, msg) {
  const el = document.getElementById(`ep-error-${userId}`);
  if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

function clearEpError(userId) {
  document.getElementById(`ep-error-${userId}`)?.classList.add('hidden');
}

async function saveUsername(userId) {
  clearEpError(userId);
  const val = document.getElementById(`ep-username-${userId}`)?.value.trim();
  if (!val) { showEpError(userId, 'Логин не может быть пустым'); return; }

  const res = await api.updateUser(userId, { username: val });
  if (res.ok) {
    showToast('Логин изменён', 'success');
    loadUsers();
  } else {
    showEpError(userId, res.error);
  }
}

async function savePassword(userId) {
  clearEpError(userId);
  const val = document.getElementById(`ep-password-${userId}`)?.value;
  if (!val || val.length < 6) { showEpError(userId, 'Пароль слишком короткий (мин. 6 символов)'); return; }

  const res = await api.setUserPassword(userId, val);
  if (res.ok) {
    showToast('Пароль изменён', 'success');
    document.getElementById(`ep-password-${userId}`).value = '';
  } else {
    showEpError(userId, res.error);
  }
}

async function doToggleUser(userId, currentlyActive) {
  const res = await api.toggleUser(userId, !currentlyActive);
  if (res.ok) {
    showToast(currentlyActive ? 'Пользователь отключён' : 'Пользователь активирован', 'success');
    _openEditId = null;
    loadUsers();
  } else {
    showEpError(userId, res.error);
  }
}

async function doRebindTotp(userId, username) {
  if (!confirm(`Сбросить 2FA для «${username}»?\n\nСтарый код будет аннулирован немедленно.\nНовый QR нужно будет передать пользователю лично.`)) return;

  const res = await api.rebindUserTotp(userId);
  if (res.ok) {
    showTotpOneTimeModal(res.data.totp_qr, res.data.totp_secret, username, 'Новый TOTP — ' + username);
    _openEditId = null;
    loadUsers();
  } else {
    showEpError(userId, res.error);
  }
}

async function doDeleteUser(userId, username) {
  if (!confirm(`Удалить пользователя «${username}»?\nДействие необратимо.`)) return;

  const res = await api.deleteUser(userId);
  if (res.ok || res.status === 204) {
    showToast('Пользователь удалён', 'success');
    _openEditId = null;
    loadUsers();
  } else {
    showEpError(userId, res.error);
  }
}

// ─── Create user modal ────────────────────────────────────────────────────────

function showCreateUserModal() {
  const currentUser = api.getUser();
  const canCreateHead = currentUser?.role === 'creator';

  document.getElementById('create-user-modal-body').innerHTML = `
    <form id="create-user-form" class="p-6 space-y-4">
      <div>
        <label class="form-label">Роль</label>
        <select name="role" class="form-input">
          ${canCreateHead ? '<option value="head_admin">Главный Админ</option>' : ''}
          <option value="admin" ${canCreateHead ? '' : 'selected'}>Админ</option>
        </select>
      </div>
      <div>
        <label class="form-label">Логин</label>
        <input name="username" type="text" class="form-input" placeholder="operator1" required autocomplete="off">
      </div>
      <div>
        <label class="form-label">Пароль</label>
        <input name="password" type="password" class="form-input" placeholder="Временный пароль" required autocomplete="new-password">
      </div>
      <div class="p-3 bg-gray-800/60 border border-gray-700 rounded-lg text-xs text-gray-400 flex items-start gap-2">
        <i class="fas fa-circle-info text-brand-400 mt-0.5 flex-shrink-0"></i>
        <span>После создания система сгенерирует QR аутентификатора. Передайте его пользователю лично по защищённому каналу.</span>
      </div>
      <div id="create-user-error" class="hidden p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-300 text-sm"></div>
      <div class="flex gap-3 pt-2">
        <button type="button" onclick="closeModal('modal-create-user')"
          class="flex-1 py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm font-medium transition">
          Отмена
        </button>
        <button type="submit"
          class="flex-1 py-2.5 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-semibold text-white transition flex items-center justify-center gap-2">
          <i class="fas fa-user-plus text-xs"></i>Создать
        </button>
      </div>
    </form>`;

  document.getElementById('create-user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const errEl = document.getElementById('create-user-error');
    const btn = e.target.querySelector('[type=submit]');
    errEl.classList.add('hidden');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    const res = await api.createUser({
      username: fd.get('username').trim(),
      password: fd.get('password'),
      role: fd.get('role'),
    });

    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-user-plus text-xs"></i>Создать';

    if (res.ok) {
      closeModal('modal-create-user');
      showTotpOneTimeModal(
        res.data.totp_qr,
        res.data.totp_secret,
        res.data.user.username,
        'TOTP для ' + res.data.user.username
      );
      loadUsers();
    } else {
      errEl.textContent = res.error;
      errEl.classList.remove('hidden');
    }
  });

  document.getElementById('modal-create-user').classList.remove('hidden');
}

// ─── One-time TOTP show modal ─────────────────────────────────────────────────

function showTotpOneTimeModal(qrDataUri, secret, username, title = 'TOTP аутентификатор') {
  document.getElementById('totp-once-title').textContent = title;
  document.getElementById('totp-once-user').textContent = username;
  document.getElementById('totp-once-qr').src = qrDataUri;
  document.getElementById('totp-once-secret').textContent = secret;
  document.getElementById('modal-totp-once').classList.remove('hidden');
}

function copyTotpSecret() {
  const secret = document.getElementById('totp-once-secret').textContent;
  navigator.clipboard.writeText(secret).then(() => showToast('Ключ скопирован', 'success'));
}

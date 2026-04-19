/**
 * Users tab — CRUD, edit via modal, TOTP re-bind.
 * Visible only to Creator and Главный Админ.
 */

const ROLE_LABELS = {
  creator:    { text: 'Creator',       cls: 'bg-purple-900/50 text-purple-300 border-purple-700' },
  head_admin: { text: 'Гл. Админ',    cls: 'bg-blue-900/50 text-blue-300 border-blue-700' },
  admin:      { text: 'Админ',        cls: 'bg-gray-800 text-gray-300 border-gray-600' },
};

function roleBadge(role) {
  const r = ROLE_LABELS[role] || { text: role, cls: 'bg-gray-800 text-gray-400 border-gray-600' };
  return `<span class="px-2 py-0.5 rounded text-xs font-medium border ${r.cls}">${r.text}</span>`;
}

function fmtDate(val) {
  if (!val) return '—';
  // Already formatted as DD.MM.YYYY (created_at from backend)
  if (typeof val === 'string' && /^\d{2}\.\d{2}\.\d{4}$/.test(val)) return val;
  // ISO datetime string or Date object
  try {
    const d = new Date(val);
    if (isNaN(d.getTime())) return '—';
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yyyy = d.getFullYear();
    return `${dd}.${mm}.${yyyy}`;
  } catch { return '—'; }
}

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
  grid.innerHTML = users.map(u => renderUserCard(u, currentUser)).join('');
}

function renderUserCard(u, currentUser) {
  const isMe   = currentUser && u.username === currentUser.username;
  const canEdit = !isMe && u.role !== 'creator';

  // Status green only if user has actually logged in at least once
  const reallyActive = u.is_active && !!u.last_login;
  // 2FA green as soon as totp_enabled=true (admin confirmed the code works)
  const twoFaOk = !!u.totp_enabled;

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
          <div class="text-xs text-gray-500">
            ${u.last_login ? 'Вход: ' + fmtDate(u.last_login) : u.created_at ? 'Создан: ' + fmtDate(u.created_at) : '—'}
          </div>
        </div>
      </div>
      ${canEdit ? `
      <button onclick="showEditUserModal(${u.id})"
        class="flex-shrink-0 px-2.5 py-1.5 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs transition flex items-center gap-1.5">
        <i class="fas fa-pen text-xs"></i>
        <span>Изменить</span>
      </button>` : ''}
    </div>

    <!-- Badges row -->
    <div class="px-4 pb-4 flex items-center gap-2 flex-wrap">
      ${roleBadge(u.role)}
      <span class="px-2 py-0.5 rounded text-xs border ${reallyActive
        ? 'bg-green-900/30 text-green-400 border-green-800'
        : u.is_active
          ? 'bg-yellow-900/30 text-yellow-500 border-yellow-800'
          : 'bg-red-900/30 text-red-400 border-red-800'}">
        ${reallyActive ? '● Активен' : u.is_active ? '◌ Ожидает входа' : '● Отключён'}
      </span>
      <span class="px-2 py-0.5 rounded text-xs border ${twoFaOk
        ? 'bg-emerald-900/30 text-emerald-400 border-emerald-800'
        : 'bg-yellow-900/30 text-yellow-500 border-yellow-800'}">
        <i class="fas fa-shield-halved text-xs mr-1"></i>${twoFaOk ? '2FA ✓' : '2FA ожидает'}
      </span>
    </div>
  </div>`;
}

// ─── Edit user modal ──────────────────────────────────────────────────────────

async function showEditUserModal(userId) {
  // Fetch fresh user data
  const res = await api.request('GET', `/users/${userId}`);
  if (!res.ok) { showToast(res.error || 'Ошибка загрузки', 'error'); return; }
  const u = res.data;

  document.getElementById('edit-user-modal-title').textContent = `Изменить: ${u.username}`;

  document.getElementById('edit-user-modal-body').innerHTML = `
    <!-- Change login -->
    <div>
      <label class="form-label">Логин</label>
      <div class="flex gap-2">
        <input id="eu-username" type="text" value="${escapeHtml(u.username)}"
          class="flex-1 form-input" autocomplete="off">
        <button onclick="euSaveUsername(${u.id})"
          class="px-3 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs text-white transition whitespace-nowrap">
          Сохранить
        </button>
      </div>
    </div>

    <!-- Change password -->
    <div>
      <label class="form-label">Новый пароль</label>
      <div class="flex gap-2">
        <input id="eu-password" type="password" placeholder="Мин. 6 символов"
          class="flex-1 form-input" autocomplete="new-password">
        <button onclick="euSavePassword(${u.id})"
          class="px-3 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs text-white transition whitespace-nowrap">
          Сохранить
        </button>
      </div>
    </div>

    <!-- Divider -->
    <div class="border-t border-gray-800 pt-3">
      <p class="text-xs text-gray-500 mb-3 uppercase tracking-wide">Действия</p>
      <div class="grid grid-cols-2 gap-2">

        <!-- Enable/Disable -->
        <button onclick="euToggle(${u.id}, ${u.is_active})"
          class="py-2.5 px-3 text-sm rounded-lg border transition flex items-center justify-center gap-2
            ${u.is_active
              ? 'bg-red-900/20 border-red-800 text-red-400 hover:bg-red-900/40'
              : 'bg-green-900/20 border-green-800 text-green-400 hover:bg-green-900/40'}">
          <i class="fas ${u.is_active ? 'fa-ban' : 'fa-check'} text-xs"></i>
          ${u.is_active ? 'Отключить' : 'Включить'}
        </button>

        <!-- Rebind TOTP -->
        <button onclick="euRebindTotp(${u.id}, '${escapeHtml(u.username)}')"
          class="py-2.5 px-3 text-sm rounded-lg border bg-yellow-900/20 border-yellow-800 text-yellow-400 hover:bg-yellow-900/40 transition flex items-center justify-center gap-2">
          <i class="fas fa-rotate text-xs"></i>Сброс 2FA
        </button>

        <!-- Delete -->
        <button onclick="euDelete(${u.id}, '${escapeHtml(u.username)}')"
          class="col-span-2 py-2.5 px-3 text-sm rounded-lg border bg-gray-800 border-gray-700 text-gray-400 hover:text-red-400 hover:border-red-800 transition flex items-center justify-center gap-2">
          <i class="fas fa-trash text-xs"></i>Удалить пользователя
        </button>
      </div>
    </div>

    <!-- Inline error -->
    <div id="eu-error" class="hidden p-2 bg-red-900/40 border border-red-800 rounded-lg text-red-300 text-xs"></div>
  `;

  document.getElementById('modal-edit-user').classList.remove('hidden');
}

function euShowError(msg) {
  const el = document.getElementById('eu-error');
  if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

function euHideError() {
  document.getElementById('eu-error')?.classList.add('hidden');
}

async function euSaveUsername(userId) {
  euHideError();
  const val = document.getElementById('eu-username')?.value.trim();
  if (!val) { euShowError('Логин не может быть пустым'); return; }

  const res = await api.updateUser(userId, { username: val });
  if (res.ok) {
    showToast('Логин изменён', 'success');
    closeModal('modal-edit-user');
    loadUsers();
  } else {
    euShowError(res.error);
  }
}

async function euSavePassword(userId) {
  euHideError();
  const val = document.getElementById('eu-password')?.value;
  if (!val || val.length < 6) { euShowError('Пароль слишком короткий (мин. 6 символов)'); return; }

  const res = await api.setUserPassword(userId, val);
  if (res.ok) {
    showToast('Пароль изменён', 'success');
    document.getElementById('eu-password').value = '';
  } else {
    euShowError(res.error);
  }
}

async function euToggle(userId, currentlyActive) {
  const res = await api.toggleUser(userId, !currentlyActive);
  if (res.ok) {
    showToast(currentlyActive ? 'Пользователь отключён' : 'Пользователь активирован', 'success');
    closeModal('modal-edit-user');
    loadUsers();
  } else {
    euShowError(res.error);
  }
}

async function euRebindTotp(userId, username) {
  if (!confirm(`Сбросить 2FA для «${username}»?\n\nСтарый код будет аннулирован немедленно.\nНовый QR нужно передать пользователю лично.`)) return;

  const res = await api.rebindUserTotp(userId);
  if (res.ok) {
    closeModal('modal-edit-user');
    showTotpOneTimeModal(res.data.totp_qr, res.data.totp_secret, username, 'Новый TOTP — ' + username, userId);
    loadUsers();
  } else {
    euShowError(res.error);
  }
}

async function euDelete(userId, username) {
  if (!confirm(`Удалить пользователя «${username}»?\nДействие необратимо.`)) return;

  const res = await api.deleteUser(userId);
  if (res.ok || res.status === 204) {
    showToast('Пользователь удалён', 'success');
    closeModal('modal-edit-user');
    loadUsers();
  } else {
    euShowError(res.error);
  }
}

// ─── Create user modal ────────────────────────────────────────────────────────

function showCreateUserModal() {
  const currentUser  = api.getUser();
  const canCreateHead = currentUser?.role === 'creator';

  document.getElementById('create-user-modal-body').innerHTML = `
    <form id="create-user-form" class="p-6 space-y-4">
      <div>
        <label class="form-label">Роль</label>
        <div class="custom-select-wrap">
          <select name="role" class="form-input custom-select">
            ${canCreateHead ? '<option value="head_admin">Главный Админ</option>' : ''}
            <option value="admin" ${canCreateHead ? '' : 'selected'}>Админ</option>
          </select>
        </div>
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
        <span>После создания система сгенерирует QR аутентификатора. Передайте его пользователю лично.</span>
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
    const fd    = new FormData(e.target);
    const errEl = document.getElementById('create-user-error');
    const btn   = e.target.querySelector('[type=submit]');
    errEl.classList.add('hidden');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    const res = await api.createUser({
      username: fd.get('username').trim(),
      password: fd.get('password'),
      role:     fd.get('role'),
    });

    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-user-plus text-xs"></i>Создать';

    if (res.ok) {
      closeModal('modal-create-user');
      showTotpOneTimeModal(
        res.data.totp_qr,
        res.data.totp_secret,
        res.data.user.username,
        'TOTP для ' + res.data.user.username,
        res.data.user.id
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

let _totpOnceUserId = null; // user ID whose TOTP is being confirmed

function showTotpOneTimeModal(qrDataUri, secret, username, title = 'TOTP аутентификатор', userId = null) {
  _totpOnceUserId = userId;

  document.getElementById('totp-once-title').innerHTML =
    `<i class="fas fa-qrcode text-brand-400 mr-1"></i>${escapeHtml(title)}`;
  document.getElementById('totp-once-user').textContent = username;
  document.getElementById('totp-once-qr').src = qrDataUri;
  document.getElementById('totp-once-secret').textContent = secret;
  document.getElementById('totp-once-code').value = '';
  document.getElementById('totp-once-error').classList.add('hidden');

  const btn = document.getElementById('totp-once-confirm-btn');
  btn.innerHTML = '<i class="fas fa-check"></i> Подтвердить';
  btn.disabled = false;

  document.getElementById('modal-totp-once').classList.remove('hidden');
  setTimeout(() => document.getElementById('totp-once-code').focus(), 200);
}

// Auto-submit on 6 digits
document.getElementById('totp-once-code')?.addEventListener('input', (e) => {
  const val = e.target.value.replace(/\D/g, '');
  e.target.value = val;
  if (val.length === 6) confirmTotpOnce();
});

async function confirmTotpOnce() {
  const code = document.getElementById('totp-once-code').value.trim();
  const errEl = document.getElementById('totp-once-error');
  const errTxt = document.getElementById('totp-once-error-text');
  const btn = document.getElementById('totp-once-confirm-btn');

  errEl.classList.add('hidden');

  if (!code || code.length < 6) {
    errTxt.textContent = 'Введите 6-значный код';
    errEl.classList.remove('hidden');
    return;
  }

  if (!_totpOnceUserId) {
    // No user to confirm for (e.g. rebind with no confirm needed) — just close
    closeModal('modal-totp-once');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

  const res = await api.confirmUserTotp(_totpOnceUserId, code);

  btn.disabled = false;
  btn.innerHTML = '<i class="fas fa-check"></i> Подтвердить';

  if (res.ok) {
    closeModal('modal-totp-once');
    _totpOnceUserId = null;
    showToast('Аутентификатор подтверждён ✓', 'success');
    loadUsers();
  } else {
    errTxt.textContent = res.error || 'Неверный код';
    errEl.classList.remove('hidden');
    document.getElementById('totp-once-code').value = '';
    document.getElementById('totp-once-code').focus();
  }
}

function copyTotpSecret() {
  const secret = document.getElementById('totp-once-secret').textContent;
  navigator.clipboard.writeText(secret).then(() => showToast('Ключ скопирован', 'success'));
}

// Expose globally
window.showCreateUserModal   = showCreateUserModal;
window.showEditUserModal     = showEditUserModal;
window.euSaveUsername        = euSaveUsername;
window.euSavePassword        = euSavePassword;
window.euToggle              = euToggle;
window.euRebindTotp          = euRebindTotp;
window.euDelete              = euDelete;
window.showTotpOneTimeModal  = showTotpOneTimeModal;
window.confirmTotpOnce       = confirmTotpOnce;
window.copyTotpSecret        = copyTotpSecret;

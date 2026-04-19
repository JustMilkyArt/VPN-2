/**
 * Users tab — CRUD, enable/disable, TOTP re-bind.
 * Visible only to Creator and Главный админ.
 */

const ROLE_LABELS = {
  creator:    { text: 'Creator',       cls: 'bg-purple-900/50 text-purple-300 border-purple-700' },
  head_admin: { text: 'Главный Админ', cls: 'bg-blue-900/50 text-blue-300 border-blue-700' },
  admin:      { text: 'Админ',         cls: 'bg-gray-800 text-gray-300 border-gray-600' },
};

function roleBadge(role) {
  const r = ROLE_LABELS[role] || { text: role, cls: 'bg-gray-800 text-gray-400' };
  return `<span class="px-2 py-0.5 rounded text-xs font-medium border ${r.cls}">${r.text}</span>`;
}

// ─── Load & render ────────────────────────────────────────────────────────────

async function loadUsers() {
  const grid = document.getElementById('users-list');
  const empty = document.getElementById('users-empty');
  if (!grid) return;

  grid.innerHTML = '<div class="col-span-full text-center py-8 text-gray-500"><i class="fas fa-spinner fa-spin mr-2"></i>Загрузка...</div>';

  const res = await api.getUsers();
  if (!res.ok) {
    grid.innerHTML = `<div class="col-span-full text-center py-8 text-red-400"><i class="fas fa-circle-exclamation mr-2"></i>${res.error}</div>`;
    return;
  }

  const users = res.data || [];
  if (users.length === 0) {
    grid.innerHTML = '';
    empty && empty.classList.remove('hidden');
    return;
  }

  empty && empty.classList.add('hidden');

  const currentUser = api.getUser();

  grid.innerHTML = users.map(u => {
    const isMe = currentUser && u.username === currentUser.username;
    const canToggle = !isMe && u.role !== 'creator';
    const canDelete = !isMe && u.role !== 'creator';
    const canRebind = u.role !== 'creator' || (currentUser && currentUser.role === 'creator');

    return `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 ${!u.is_active ? 'opacity-60' : ''}">
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 min-w-0">
          <div class="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0
            ${u.role === 'creator' ? 'bg-purple-700' : u.role === 'head_admin' ? 'bg-blue-700' : 'bg-gray-700'}">
            <i class="fas ${u.role === 'creator' ? 'fa-crown' : 'fa-user-shield'} text-white text-sm"></i>
          </div>
          <div class="min-w-0">
            <div class="font-semibold text-white text-sm truncate">${escapeHtml(u.username)}</div>
            <div class="text-xs text-gray-500">${u.created_at ? u.created_at.slice(0, 10) : '—'}</div>
          </div>
        </div>
        ${isMe ? '<span class="text-xs text-brand-400 flex-shrink-0">Вы</span>' : ''}
      </div>

      <div class="flex items-center gap-2 flex-wrap">
        ${roleBadge(u.role)}
        <span class="px-2 py-0.5 rounded text-xs border ${u.is_active ? 'bg-green-900/30 text-green-400 border-green-800' : 'bg-red-900/30 text-red-400 border-red-800'}">
          ${u.is_active ? 'Активен' : 'Отключён'}
        </span>
        <span class="px-2 py-0.5 rounded text-xs border ${u.totp_enabled ? 'bg-emerald-900/30 text-emerald-400 border-emerald-800' : 'bg-yellow-900/30 text-yellow-400 border-yellow-800'}">
          <i class="fas fa-shield-halved text-xs mr-1"></i>${u.totp_enabled ? '2FA ✓' : '2FA —'}
        </span>
      </div>

      <div class="flex gap-2 mt-auto flex-wrap">
        ${canToggle ? `
        <button onclick="toggleUser(${u.id}, ${u.is_active})"
          class="flex-1 min-w-0 py-1.5 text-xs rounded-lg border transition
            ${u.is_active ? 'bg-red-900/20 border-red-800 text-red-400 hover:bg-red-900/40' : 'bg-green-900/20 border-green-800 text-green-400 hover:bg-green-900/40'}">
          <i class="fas ${u.is_active ? 'fa-ban' : 'fa-check'} mr-1"></i>${u.is_active ? 'Отключить' : 'Включить'}
        </button>
        ` : ''}
        ${canRebind ? `
        <button onclick="rebindUserTotp(${u.id}, '${escapeHtml(u.username)}')"
          class="flex-1 min-w-0 py-1.5 text-xs rounded-lg border bg-yellow-900/20 border-yellow-800 text-yellow-400 hover:bg-yellow-900/40 transition">
          <i class="fas fa-rotate mr-1"></i>Сброс 2FA
        </button>
        ` : ''}
        ${canDelete ? `
        <button onclick="deleteUser(${u.id}, '${escapeHtml(u.username)}')"
          class="py-1.5 px-3 text-xs rounded-lg border bg-gray-800 border-gray-700 text-gray-400 hover:text-red-400 hover:border-red-800 transition">
          <i class="fas fa-trash"></i>
        </button>
        ` : ''}
      </div>
    </div>`;
  }).join('');
}

// ─── Actions ──────────────────────────────────────────────────────────────────

async function toggleUser(id, currentlyActive) {
  const res = await api.toggleUser(id, !currentlyActive);
  if (res.ok) {
    showToast(currentlyActive ? 'Пользователь отключён' : 'Пользователь активирован', 'success');
    loadUsers();
  } else {
    showToast(res.error, 'error');
  }
}

async function deleteUser(id, username) {
  if (!confirm(`Удалить пользователя «${username}»? Действие необратимо.`)) return;
  const res = await api.deleteUser(id);
  if (res.ok || res.status === 204) {
    showToast('Пользователь удалён', 'success');
    loadUsers();
  } else {
    showToast(res.error, 'error');
  }
}

async function rebindUserTotp(id, username) {
  if (!confirm(`Сбросить 2FA для «${username}»? Старый TOTP будет немедленно аннулирован.`)) return;
  const res = await api.rebindUserTotp(id);
  if (res.ok) {
    showTotpOneTimeModal(res.data.totp_qr, res.data.totp_secret, username, 'Новый TOTP для ' + username);
    loadUsers();
  } else {
    showToast(res.error, 'error');
  }
}

// ─── Create user modal ────────────────────────────────────────────────────────

function showCreateUserModal() {
  const currentUser = api.getUser();
  const canCreateHead = currentUser && currentUser.role === 'creator';

  document.getElementById('create-user-modal-body').innerHTML = `
    <form id="create-user-form" class="p-6 space-y-4">
      <div>
        <label class="form-label">Роль</label>
        <select name="role" class="form-input">
          ${canCreateHead ? '<option value="head_admin">Главный Админ</option>' : ''}
          <option value="admin" selected>Админ</option>
        </select>
      </div>
      <div>
        <label class="form-label">Логин</label>
        <input name="username" type="text" class="form-input" placeholder="operator1" required>
      </div>
      <div>
        <label class="form-label">Временный пароль</label>
        <input name="password" type="password" class="form-input" placeholder="Пользователь должен сменить при входе" required>
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
        res.data.totp_qr, res.data.totp_secret,
        res.data.user.username,
        'TOTP для нового пользователя'
      );
      loadUsers();
    } else {
      errEl.textContent = res.error;
      errEl.classList.remove('hidden');
    }
  });

  document.getElementById('modal-create-user').classList.remove('hidden');
}

// ─── One-time TOTP show modal ──────────────────────────────────────────────────

function showTotpOneTimeModal(qrDataUri, secret, username, title = 'Привязка аутентификатора') {
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

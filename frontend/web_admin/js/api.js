/**
 * API Client for VPN Admin Backend
 * All security logic lives on the backend; frontend only transports data.
 */

const API_BASE = window.location.protocol + '//' + window.location.host + '/api/v1';

const api = {
  _token: null,

  getToken() {
    return this._token || localStorage.getItem('vpn_admin_token');
  },

  setToken(token) {
    this._token = token;
    localStorage.setItem('vpn_admin_token', token);
  },

  clearToken() {
    this._token = null;
    localStorage.removeItem('vpn_admin_token');
    localStorage.removeItem('vpn_admin_user');
  },

  saveUser(userObj) {
    localStorage.setItem('vpn_admin_user', JSON.stringify(userObj));
  },

  getUser() {
    try { return JSON.parse(localStorage.getItem('vpn_admin_user') || 'null'); } catch { return null; }
  },

  headers() {
    const token = this.getToken();
    const h = { 'Content-Type': 'application/json' };
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  },

  async request(method, path, data = null, opts = {}) {
    const config = {
      method,
      url: API_BASE + path,
      headers: this.headers(),
      ...(data !== null && { data }),
      timeout: opts.timeout || 60000,
    };

    try {
      const res = await axios(config);
      return { ok: true, data: res.data, status: res.status };
    } catch (err) {
      if (err.response?.status === 401) {
        const isAuthEndpoint = path.startsWith('/auth/');
        if (!isAuthEndpoint) {
          this.clearToken();
          if (window.showLogin) window.showLogin();
        }
      }
      const detail = err.response?.data?.detail || err.message || 'Request failed';
      return { ok: false, error: detail, status: err.response?.status };
    }
  },

  // ─── Auth ──────────────────────────────────────────────────────────────────

  // Step 1: username + password → phase=totp + temp_token
  async loginStep1(username, password) {
    return this.request('POST', '/auth/login', { username, password });
  },

  // Step 2: temp_token + totp_code → access_token
  async loginStep2(tempToken, totpCode) {
    return this.request('POST', '/auth/totp-verify', {
      temp_token: tempToken,
      totp_code: totpCode,
    });
  },

  async me() {
    return this.request('GET', '/auth/me');
  },

  async logoutServer() {
    // Tell backend to invalidate the session (best-effort, ignore errors)
    try { await this.request('POST', '/auth/logout'); } catch {}
  },

  async changeCreds(newUsername, newPassword, confirmPassword, totpCode) {
    return this.request('POST', '/auth/change-creds', {
      new_username: newUsername,
      new_password: newPassword,
      confirm_password: confirmPassword,
      totp_code: totpCode,
    });
  },

  // ─── Users ─────────────────────────────────────────────────────────────────
  async getUsers() {
    return this.request('GET', '/users/');
  },

  async createUser(data) {
    return this.request('POST', '/users/', data, { timeout: 30000 });
  },

  async updateUser(id, data) {
    return this.request('PUT', `/users/${id}`, data);
  },

  async setUserPassword(id, newPassword) {
    return this.request('POST', `/users/${id}/set-password`, { new_password: newPassword });
  },

  async deleteUser(id) {
    return this.request('DELETE', `/users/${id}`);
  },

  async toggleUser(id, active) {
    return this.request('POST', `/users/${id}/toggle`, { active });
  },

  async rebindUserTotp(id) {
    return this.request('POST', `/users/${id}/rebind-totp`);
  },

  async confirmUserTotp(id, totpCode) {
    return this.request('POST', `/users/${id}/confirm-totp`, { totp_code: totpCode });
  },

  // ─── Servers ───────────────────────────────────────────────────────────────
  async getServers() {
    return this.request('GET', '/servers/');
  },
  async createServer(data) {
    return this.request('POST', '/servers/', data);
  },
  async updateServer(id, data) {
    return this.request('PUT', `/servers/${id}`, data);
  },
  async deleteServer(id) {
    return this.request('DELETE', `/servers/${id}`);
  },
  async pingServer(id) {
    return this.request('POST', `/servers/${id}/ping`, null, { timeout: 30000 });
  },
  async checkAllServers() {
    return this.request('POST', '/servers/check-all-status', null, { timeout: 60000 });
  },
  async serverInfo(id) {
    return this.request('GET', `/servers/${id}/info`);
  },
  async installStack(id, data) {
    return this.request('POST', `/servers/${id}/install`, data, { timeout: 300000 });
  },
  async restartServices(id) {
    return this.request('POST', `/servers/${id}/restart`, null, { timeout: 60000 });
  },
  async redeployServer(id) {
    return this.request('POST', `/servers/${id}/redeploy`, null, { timeout: 120000 });
  },

  // ─── Connections ───────────────────────────────────────────────────────────
  async getConnectionsGrouped() {
    return this.request('GET', '/connections/grouped');
  },
  async getConnections() {
    return this.request('GET', '/connections/');
  },
  async createConnection(data) {
    return this.request('POST', '/connections/', data, { timeout: 120000 });
  },
  async deleteConnection(id) {
    return this.request('DELETE', `/connections/${id}`);
  },
  async toggleConnection(id, active) {
    return this.request('POST', `/connections/${id}/toggle?active=${active}`);
  },
  async getClientConfig(id) {
    return this.request('GET', `/connections/${id}/client-config`);
  },
};

window.api = api;

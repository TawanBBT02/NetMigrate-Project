/*
 * NetMigrate shared frontend helpers: theme toggle, fetch wrappers, and the
 * global error banner. Loaded by templates/base.html on every page.
 *
 * `netmigrate-theme` is the ONLY localStorage key used anywhere in this app
 * (CLAUDE.md section 12). Nothing else -- not draft form state, not table
 * filters -- goes in browser storage; that data belongs on the server so a
 * second tab or a second session sees the same thing.
 */

const NetMigrate = (() => {
  const THEME_KEY = 'netmigrate-theme';

  function initTheme() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const isDark = document.documentElement.classList.toggle('dark');
      try {
        localStorage.setItem(THEME_KEY, isDark ? 'dark' : 'light');
      } catch (e) {
        // Private browsing or storage disabled: theme just won't persist
        // across reloads. Not worth surfacing to the user.
      }
    });
  }

  function initErrorBanner() {
    const closeBtn = document.getElementById('error-banner-close');
    if (closeBtn) closeBtn.addEventListener('click', clearError);
  }

  // Config text is rendered with this, never with innerHTML directly --
  // spec section 5: "A configuration file containing <script> must not
  // execute."
  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function showError(message) {
    const banner = document.getElementById('error-banner');
    const text = document.getElementById('error-banner-message');
    if (!banner || !text) {
      window.alert(message);
      return;
    }
    text.textContent = message;
    banner.classList.remove('hidden');
  }

  function clearError() {
    const banner = document.getElementById('error-banner');
    if (banner) banner.classList.add('hidden');
  }

  // Every endpoint returns {"error": "<message>"} on failure (spec section
  // 3). Non-JSON responses (the ZIP download, the export attachment) are
  // handled by callers directly, not through this helper.
  async function readBody(res) {
    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) return null;
    return res.json().catch(() => null);
  }

  async function apiFetch(path, options = {}) {
    clearError();
    let res;
    try {
      res = await fetch(path, options);
    } catch (err) {
      showError('Network error: could not reach the server.');
      throw err;
    }
    const body = await readBody(res);
    if (!res.ok) {
      const message = (body && body.error) ? body.error : `Request failed (${res.status})`;
      showError(message);
      throw new Error(message);
    }
    return body;
  }

  function apiGet(path) {
    return apiFetch(path);
  }

  function apiPost(path, data) {
    return apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  function apiPut(path, data) {
    return apiFetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  function apiDelete(path) {
    return apiFetch(path, { method: 'DELETE' });
  }

  // For multipart/form-data (batch upload): pass a FormData instance and
  // let the browser set the Content-Type boundary itself.
  function apiUpload(path, formData) {
    return apiFetch(path, { method: 'POST', body: formData });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initErrorBanner();
  });

  return {
    apiGet,
    apiPost,
    apiPut,
    apiDelete,
    apiUpload,
    escapeHtml,
    showError,
    clearError,
  };
})();

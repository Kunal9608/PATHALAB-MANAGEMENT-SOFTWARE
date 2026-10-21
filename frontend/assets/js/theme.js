/**
 * AKRITI — Theme Manager
 * Persists light/dark preference; applies data-theme="dark" to <html>.
 *
 * FIX: shell.js injects the topbar HTML AFTER theme.js init(), so the
 * [data-theme-toggle] button didn't exist yet when init() ran.
 * Solution: expose Theme.bindButtons() so shell.js calls it after render.
 */

// Apply theme and block page flashing IMMEDIATELY (before DOMContentLoaded)
(function () {
  const path = window.location.pathname;
  const isProtected = path.includes('/admin/') || path.includes('/staff/') || path.includes('/profile');
  const isErrorPage = path === '/404' || path === '/404.html' || path === '/offline' || path === '/offline.html' ||
                      (document.title && (document.title.includes('404') || document.title.includes('Offline')));
  if (isProtected && !isErrorPage) {
    const style = document.createElement('style');
    style.id = 'page-blocking-style';
    style.innerHTML = 'body { display: none !important; }';
    document.documentElement.appendChild(style);
  }
  const saved = localStorage.getItem('akriti-theme');
  if (saved === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
})();

const Theme = (() => {
  const KEY  = 'akriti-theme';
  const DARK = 'dark';
  const LIGHT = 'light';

  const ICON_MOON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>`;
  const ICON_SUN  = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

  function current() {
    return localStorage.getItem(KEY) || LIGHT;
  }

  function apply(theme) {
    if (theme === DARK) {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem(KEY, theme);
    // Sync all toggle button icons
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      if (btn.classList.contains('toggle')) {
        if (theme === DARK) {
          btn.classList.add('on');
        } else {
          btn.classList.remove('on');
        }
      } else {
        btn.innerHTML = theme === DARK ? ICON_SUN : ICON_MOON;
      }
      btn.setAttribute('aria-label', theme === DARK ? 'Switch to light mode' : 'Switch to dark mode');
    });
    // Dispatch custom event for charts or components that need to live-update
    window.dispatchEvent(new CustomEvent('akriti-theme-change', { detail: { theme } }));
  }

  function toggle() {
    apply(current() === DARK ? LIGHT : DARK);
  }

  /**
   * Call this after any dynamic HTML injection that adds [data-theme-toggle] buttons.
   * Clones buttons to remove stale listeners, then re-attaches a single click handler.
   */
  function bindButtons() {
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      const fresh = btn.cloneNode(true);
      btn.parentNode.replaceChild(fresh, btn);
      fresh.addEventListener('click', toggle);
    });
    // Sync icon to current state immediately after binding
    apply(current());
  }

  // Initial bind on DOMContentLoaded (for any static [data-theme-toggle] in HTML)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindButtons);
  } else {
    bindButtons();
  }

  return { toggle, current, apply, bindButtons };
})();

window.Theme = Theme;

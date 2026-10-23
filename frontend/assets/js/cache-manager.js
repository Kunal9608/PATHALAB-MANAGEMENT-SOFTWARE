/**
 * AKRITI — Smart Cache Manager (IndexedDB)
 * Implements persistent caching for instant SWR (Stale-While-Revalidate) rendering.
 */
const CacheManager = (() => {
  const DB_NAME = 'akriti-cache';
  const DB_VER = 1;
  const STORE = 'data';
  let db = null;

  function openDB() {
    return new Promise((resolve, reject) => {
      if (db) return resolve(db);
      const req = indexedDB.open(DB_NAME, DB_VER);
      req.onupgradeneeded = e => {
        const d = e.target.result;
        if (!d.objectStoreNames.contains(STORE)) {
          d.createObjectStore(STORE, { keyPath: 'key' });
        }
      };
      req.onsuccess = e => { db = e.target.result; resolve(db); };
      req.onerror = e => reject(e.target.error);
    });
  }

  async function get(key) {
    try {
      const d = await openDB();
      return new Promise((resolve, reject) => {
        const req = d.transaction(STORE, 'readonly').objectStore(STORE).get(key);
        req.onsuccess = e => resolve(e.target.result?.value || null);
        req.onerror = e => reject(e.target.error);
      });
    } catch {
      return null;
    }
  }

  async function set(key, value) {
    try {
      const d = await openDB();
      return new Promise((resolve, reject) => {
        const tx = d.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put({ key, value, timestamp: Date.now() });
        tx.oncomplete = resolve;
        tx.onerror = e => reject(e.target.error);
      });
    } catch {
      return null;
    }
  }

  async function invalidate(pattern) {
    try {
      const d = await openDB();
      return new Promise((resolve, reject) => {
        const tx = d.transaction(STORE, 'readwrite');
        const store = tx.objectStore(STORE);
        const req = store.getAllKeys();
        req.onsuccess = e => {
          const keys = e.target.result;
          const regex = typeof pattern === 'string' ? new RegExp(pattern) : pattern;
          keys.forEach(k => {
            if (regex.test(k)) {
              store.delete(k);
            }
          });
        };
        tx.oncomplete = resolve;
        tx.onerror = e => reject(e.target.error);
      });
    } catch {
      return null;
    }
  }

  function getCurrentUserId() {
    if (typeof window !== 'undefined') {
      if (window._me && window._me.id) return String(window._me.id);
      try {
        const u = JSON.parse(localStorage.getItem('akriti_current_user') || '{}');
        return u.id ? String(u.id) : null;
      } catch (_) {}
    }
    return null;
  }

  function buildKey(method = 'GET', path = '', body = null, userId = null) {
    const m = (method || 'GET').toUpperCase();
    const uid = userId || getCurrentUserId() || 'public';
    const bodyStr = body ? (typeof body === 'string' ? body : JSON.stringify(body)) : '';
    return `${uid}:${m}:${path}:${bodyStr}`;
  }

  // Preload endpoints silently in the background using canonical request key
  function prefetch(endpoints) {
    endpoints.forEach(async (path) => {
      try {
        const res = await fetch(path, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          const canonicalKey = buildKey('GET', path);
          await set(canonicalKey, data);
        }
      } catch (err) {
        console.warn('Prefetch failed for:', path);
      }
    });
  }

  return { get, set, invalidate, prefetch, buildKey, getCurrentUserId };
})();

if (typeof window !== 'undefined') {
  window.CacheManager = CacheManager;
}

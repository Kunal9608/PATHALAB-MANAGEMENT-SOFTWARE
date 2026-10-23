/**
 * AKRITI — Offline Queue (IndexedDB + auto-sync)
 * SRS §5.11 — FR-11.1, FR-11.2
 *
 * While offline: Add Patient + Attendance actions are queued with their
 * original Idempotency-Key so the backend's idempotency replay prevents
 * duplicates on sync even if the connection drops mid-replay.
 */

const OfflineQueue = (() => {
  const DB_NAME  = 'akriti-offline';
  const DB_VER   = 1;
  const STORE    = 'queue';
  let db = null;
  let onlineBanner = null;
  let syncInProgress = false;

  // ── IndexedDB setup ───────────────────────────────────────────────────────
  function openDB() {
    return new Promise((resolve, reject) => {
      if (db) return resolve(db);
      const req = indexedDB.open(DB_NAME, DB_VER);
      req.onupgradeneeded = e => {
        const d = e.target.result;
        if (!d.objectStoreNames.contains(STORE)) {
          const store = d.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
          store.createIndex('timestamp', 'timestamp');
        }
      };
      req.onsuccess = e => { db = e.target.result; resolve(db); };
      req.onerror   = e => reject(e.target.error);
    });
  }

  function getCurrentUserId() {
    if (window._me && window._me.id) return String(window._me.id);
    try {
      const u = JSON.parse(localStorage.getItem('akriti_current_user') || '{}');
      return u.id ? String(u.id) : null;
    } catch (_) {
      return null;
    }
  }

  function generateTempRefId() {
    const d = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const rand = Math.random().toString(36).substring(2, 8).toUpperCase();
    return `TMP-${d}-${rand}`;
  }

  async function enqueue(endpoint, method, payload, idempotencyKey, tempRefId = null) {
    const d = await openDB();
    const refId = tempRefId || generateTempRefId();
    payload.temp_ref_id = refId;
    const currentUserId = getCurrentUserId();

    // Ensure offline patient registrations target the durable offline endpoint
    if ((endpoint === '/api/v1/patients' || !endpoint) && method === 'POST') {
      endpoint = '/api/v1/offline-patients';
    }

    return new Promise((resolve, reject) => {
      const tx = d.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).add({
        endpoint,
        method,
        payload,
        idempotencyKey,
        tempRefId: refId,
        ownerId: currentUserId,
        status: 'PENDING',
        retryCount: 0,
        lastAttempt: null,
        failureReason: null,
        timestamp: Date.now(),
      });
      tx.oncomplete = () => resolve(refId);
      tx.onerror    = e => reject(e.target.error);
    });
  }

  async function updateItem(item) {
    const d = await openDB();
    return new Promise((resolve, reject) => {
      const tx = d.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(item);
      tx.oncomplete = resolve;
      tx.onerror = e => reject(e.target.error);
    });
  }

  async function getAll(filterUser = false) {
    const d = await openDB();
    const userId = getCurrentUserId();
    return new Promise((resolve, reject) => {
      const req = d.transaction(STORE, 'readonly').objectStore(STORE).getAll();
      req.onsuccess = e => {
        let items = e.target.result || [];
        if (filterUser && userId) {
          items = items.filter(it => !it.ownerId || String(it.ownerId) === String(userId));
        }
        resolve(items);
      };
      req.onerror   = e => reject(e.target.error);
    });
  }

  async function remove(id) {
    const d = await openDB();
    return new Promise((resolve, reject) => {
      const tx = d.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(id);
      tx.oncomplete = resolve;
      tx.onerror    = e => reject(e.target.error);
    });
  }

  // ── Connectivity detection ────────────────────────────────────────────────
  async function isOnline() {
    if (!navigator.onLine) return false;
    try {
      const res = await fetch('/health', { method: 'GET', cache: 'no-store' });
      return res.ok;
    } catch {
      return false;
    }
  }

  const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('akriti-network-status') : null;
  let hideTimeout = null;

  function broadcastState(state, count = 0, message = '') {
    if (channel) {
      channel.postMessage({ state, count, message });
    }
  }

  function updateBanner(state, count = 0, customMsg = '') {
    if (!onlineBanner) onlineBanner = document.querySelector('.offline-banner');
    if (!onlineBanner) return;

    if (hideTimeout) {
      clearTimeout(hideTimeout);
      hideTimeout = null;
    }

    const isAddPatient = window.location.pathname.includes('add-patient');
    onlineBanner.classList.remove('state-offline', 'state-syncing', 'state-success');

    if (state === 'offline') {
      onlineBanner.classList.add('state-offline');
      onlineBanner.textContent = customMsg || (isAddPatient
        ? '🟡 Offline: Saving draft locally...'
        : (count > 0 ? `🟡 Offline — ${count} action${count > 1 ? 's' : ''} queued` : '🟡 Offline — Changes will sync when connection is restored'));
      onlineBanner.classList.add('show');
    } else if (state === 'syncing') {
      onlineBanner.classList.add('state-syncing');
      onlineBanner.textContent = customMsg || `🔄 Syncing changes...`;
      onlineBanner.classList.add('show');
    } else if (state === 'success') {
      onlineBanner.classList.add('state-success');
      onlineBanner.textContent = customMsg || '🟢 Connected — All pending changes have been synchronized.';
      onlineBanner.classList.add('show');

      hideTimeout = setTimeout(() => {
        onlineBanner.classList.remove('show');
        broadcastState('dismiss');
      }, 3000);
    } else if (state === 'conflict') {
      onlineBanner.classList.add('state-offline'); // keep it visible and red/yellow
      onlineBanner.textContent = customMsg || `⚠️ Sync Paused — Conflict Detected`;
      onlineBanner.classList.add('show');
    } else if (state === 'hide') {
      onlineBanner.classList.remove('show');
    }
  }

  if (channel) {
    channel.onmessage = (event) => {
      const { state, count, message, conflictData } = event.data;
      if (state === 'dismiss') {
        if (onlineBanner) onlineBanner.classList.remove('show');
      } else if (state === 'conflict') {
        updateBanner(state, count, message);
        // Dispatch custom event so the UI can show the modal
        window.dispatchEvent(new CustomEvent('offline-sync-conflict', { detail: conflictData }));
      } else {
        updateBanner(state, count, message);
      }
    };
  }

  // ── Sync ──────────────────────────────────────────────────────────────────
  async function flush() {
    if (syncInProgress) return;
    const online = await isOnline();
    if (!online) return;

    const items = await getAll(false);
    if (!items.length) {
      if (onlineBanner && onlineBanner.classList.contains('show')) {
        updateBanner('success');
        broadcastState('success');
      } else {
        updateBanner('hide');
        broadcastState('hide');
      }
      return;
    }

    syncInProgress = true;
    let synced = 0;
    let failed = 0;

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      // Do not re-hammer permanent validation/conflict failures more than once every 30 seconds
      if (item.status === 'FAILED' && item.lastAttempt && (Date.now() - item.lastAttempt < 30000)) {
        failed++;
        continue;
      }

      let targetEndpoint = item.endpoint;
      if ((targetEndpoint === '/api/v1/patients' || !targetEndpoint) && item.method === 'POST') {
        targetEndpoint = '/api/v1/offline-patients';
      }

      const progressMsg = `🔄 Syncing changes (${i + 1}/${items.length})...`;
      updateBanner('syncing', items.length - i, progressMsg);
      broadcastState('syncing', items.length - i, progressMsg);

      try {
        const headers = {
          'Content-Type': 'application/json',
          'Idempotency-Key': item.idempotencyKey,
        };
        if (item.tempRefId) {
          headers['X-Temp-Ref-ID'] = item.tempRefId;
        }

        const res = await fetch(targetEndpoint, {
          method: item.method,
          credentials: 'include',
          headers,
          body: JSON.stringify(item.payload),
        });

        if (res.ok) {
          const resData = await res.json().catch(() => ({}));
          if (resData && resData.status === 'FAILED') {
            item.status = 'FAILED';
            item.failureReason = resData.failure_reason || 'Synchronization rejected';
            item.retryCount = (item.retryCount || 0) + 1;
            item.lastAttempt = Date.now();
            await updateItem(item);
            failed++;
          } else {
            await remove(item.id);
            synced++;
          }
        } else if (res.status === 409) {
          const errData = await res.json().catch(() => ({}));
          const existingPatient = (errData.detail && typeof errData.detail === 'object') ? errData.detail.existing_patient : null;
          item.status = existingPatient ? 'CONFLICT' : 'FAILED';
          item.existingPatient = existingPatient;
          item.failureReason = (typeof errData.detail === 'string' ? errData.detail : (errData.detail?.message || 'Duplicate patient detected'));
          item.retryCount = (item.retryCount || 0) + 1;
          item.lastAttempt = Date.now();
          await updateItem(item);
          failed++;

          if (existingPatient) {
            updateBanner('conflict', items.length - i, "⚠️ Sync issue — Duplicate detected.");
            if (channel) {
              channel.postMessage({
                state: 'conflict',
                count: items.length - i,
                message: "Sync conflict",
                conflictData: { itemId: item.id, payload: item.payload, existingPatient }
              });
            } else {
              window.dispatchEvent(new CustomEvent('offline-sync-conflict', { 
                detail: { itemId: item.id, payload: item.payload, existingPatient } 
              }));
            }
          }
        } else {
          const errData = await res.json().catch(() => ({}));
          item.status = 'FAILED';
          item.failureReason = (typeof errData.detail === 'string' ? errData.detail : (errData.detail?.message || 'Server rejected registration'));
          item.retryCount = (item.retryCount || 0) + 1;
          item.lastAttempt = Date.now();
          await updateItem(item);
          failed++;
        }
      } catch (networkErr) {
        item.status = 'FAILED';
        item.failureReason = 'Network or backend unavailable';
        item.retryCount = (item.retryCount || 0) + 1;
        item.lastAttempt = Date.now();
        await updateItem(item).catch(() => {});
        failed++;
      }
    }

    syncInProgress = false;

    if (synced > 0 && typeof window.Toast !== 'undefined') {
      window.Toast.show(`${synced} offline action${synced > 1 ? 's' : ''} synced successfully`, 'success');
    }

    if (failed === 0) {
      updateBanner('success', 0, "🟢 Connected — All pending changes have been synchronized.");
      broadcastState('success', 0, "🟢 Connected — All pending changes have been synchronized.");
    } else {
      const msg = `🟢 Connected — Sync completed. ${synced} synced, ${failed} failed.`;
      updateBanner('offline', failed, msg);
      broadcastState('offline', failed, msg);
    }
  }

  async function syncSingleItem(item) {
    try {
      let targetEndpoint = item.endpoint;
      if ((targetEndpoint === '/api/v1/patients' || !targetEndpoint) && item.method === 'POST') {
        targetEndpoint = '/api/v1/offline-patients';
      }
      const headers = {
        'Content-Type': 'application/json',
        'Idempotency-Key': item.idempotencyKey,
      };
      if (item.tempRefId) {
        headers['X-Temp-Ref-ID'] = item.tempRefId;
      }

      const res = await fetch(targetEndpoint, {
        method: item.method,
        credentials: 'include',
        headers,
        body: JSON.stringify(item.payload),
      });

      if (res.ok) {
        const resData = await res.json().catch(() => ({}));
        if (resData && resData.status === 'FAILED') {
          item.status = 'FAILED';
          item.failureReason = resData.failure_reason || 'Synchronization rejected';
          item.retryCount = (item.retryCount || 0) + 1;
          item.lastAttempt = Date.now();
          await updateItem(item);
          return { success: false, status: 'FAILED', reason: item.failureReason };
        } else {
          await remove(item.id);
          return {
            success: true,
            status: 'SUCCESS',
            patient_code: resData.patient_code || resData.permanent_patient_code,
            patient_id: resData.id || resData.patient_id,
          };
        }
      } else if (res.status === 409) {
        const errData = await res.json().catch(() => ({}));
        const existingPatient = (errData.detail && typeof errData.detail === 'object') ? errData.detail.existing_patient : null;
        item.status = existingPatient ? 'CONFLICT' : 'FAILED';
        item.existingPatient = existingPatient;
        item.failureReason = (typeof errData.detail === 'string' ? errData.detail : (errData.detail?.message || 'Duplicate patient detected'));
        item.retryCount = (item.retryCount || 0) + 1;
        item.lastAttempt = Date.now();
        await updateItem(item);
        return { success: false, status: item.status, existingPatient, reason: item.failureReason };
      } else {
        const errData = await res.json().catch(() => ({}));
        item.status = 'FAILED';
        item.failureReason = (typeof errData.detail === 'string' ? errData.detail : (errData.detail?.message || 'Server rejected registration'));
        item.retryCount = (item.retryCount || 0) + 1;
        item.lastAttempt = Date.now();
        await updateItem(item);
        return { success: false, status: 'FAILED', reason: item.failureReason };
      }
    } catch (networkErr) {
      item.status = 'FAILED';
      item.failureReason = 'Network or backend unavailable';
      item.retryCount = (item.retryCount || 0) + 1;
      item.lastAttempt = Date.now();
      await updateItem(item).catch(() => {});
      return { success: false, status: 'FAILED', reason: item.failureReason };
    }
  }

  async function retryItem(itemId) {
    const items = await getAll(false);
    const item = items.find(i => i.id === itemId);
    if (!item) {
      return { success: false, reason: 'Record not found in local offline storage.' };
    }
    return await syncSingleItem(item);
  }

  async function retryAll() {
    const items = await getAll(false);
    const failedItems = items.filter(i => i.status === 'FAILED' || i.status === 'PENDING' || i.status === 'CONFLICT');
    let succeeded = 0;
    let failed = 0;
    const results = [];

    for (const item of failedItems) {
      const res = await syncSingleItem(item);
      results.push({ item, res });
      if (res.success) succeeded++;
      else failed++;
    }

    return { succeeded, failed, total: failedItems.length, results };
  }

  async function resolveConflict(itemId, resolution) {
    const items = await getAll(false);
    const item = items.find(i => i.id === itemId);
    if (!item) {
      flush();
      return;
    }

    if (resolution === 'discard') {
      await remove(itemId);
    } else if (resolution === 'force') {
      item.payload.force_duplicate = true;
      item.idempotencyKey = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : ('idem-' + Date.now() + '-' + Math.random().toString(36).slice(2));
      item.status = 'PENDING';
      await updateItem(item);
      await syncSingleItem(item);
    }

    flush();
  }

  // ── Init: connectivity listeners ──────────────────────────────────────────
  async function init() {
    onlineBanner = document.querySelector('.offline-banner');

    const check = async () => {
      const online = await isOnline();
      const items = await getAll();
      if (!online) {
        updateBanner('offline', items.length);
        broadcastState('offline', items.length);
      } else {
        await flush();
      }
    };

    window.addEventListener('online',  () => flush());
    window.addEventListener('offline', () => check());

    // Initial check
    check();

    // Periodic ping every 30s
    setInterval(check, 30_000);
  }

  function stop() {
    syncInProgress = false;
    if (onlineBanner) {
      onlineBanner.classList.remove('show');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return { enqueue, flush, getAll, isOnline, resolveConflict, remove, retryItem, retryAll, stop };
})();

window.OfflineQueue = OfflineQueue;


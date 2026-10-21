/**
 * AKRITI — API Client
 * Wraps fetch with:
 *  - credentials: 'include' (httpOnly cookies)
 *  - Idempotency-Key on mutating requests (UUID v4)
 *  - Silent 401 → token refresh → retry once
 *  - Structured error handling → Toast
 *
 * Usage:
 *   const data = await API.get('/api/v1/patients');
 *   const result = await API.post('/api/v1/patients', payload);
 *   const result = await API.patch('/api/v1/patients/123', payload);
 *   const result = await API.delete('/api/v1/patients/123');
 */

const API = (() => {
  let refreshPromise = null;

  function uuidv4() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  async function refreshToken() {
    const res = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) throw new Error('Session expired');
    return res.ok;
  }

  function isLoginPage() {
    const path = window.location.pathname.replace(/\/$/, "");
    return path === "" || path === "/index.html" || path === "/index" || path.endsWith("/index.html") || path.endsWith("/index");
  }

  async function clearLocalAuthState({ skipLogoutCall = false } = {}) {
    localStorage.removeItem('akriti_current_user');
    localStorage.removeItem('akriti_tests_cache');
    if (window.CacheManager) {
      try {
        await window.CacheManager.invalidate('.*');
      } catch (e) {
        console.error("CacheManager invalidation failed:", e);
      }
    }
    if (!skipLogoutCall) {
      try {
        await fetch('/api/v1/auth/logout', {
          method: 'POST',
          credentials: 'include'
        });
      } catch (e) {
        console.error("Logout request failed:", e);
      }
    }
    document.cookie = "access_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=strict";
    document.cookie = "refresh_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=strict";
  }

  const activeRequests = new Map();
  const failureCounters = new Map(); // key -> { count, resetAt }

  async function _doNetworkFetch(method, path, body, options, requestKey, endpointKey, cachedData) {
    if (cachedData && activeRequests.has(requestKey)) {
      return activeRequests.get(requestKey);
    }

    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };

    const mutating = ['POST', 'PATCH', 'PUT', 'DELETE'].includes(method.toUpperCase());
    if (mutating && !options.skipIdempotency) {
      headers['Idempotency-Key'] = options.idempotencyKey || uuidv4();
    }

    const init = {
      method: method.toUpperCase(),
      credentials: 'include',
      headers,
    };

    if (body !== null) {
      init.body = JSON.stringify(body);
    }

    const reqPromise = (async () => {
      let res;
      try {
        res = await fetch(path, init);
      } catch (err) {
        let errorMsg = 'Network connection failed';
        let category = 'NETWORK_ERROR';

        if (err.name === 'AbortError') {
          errorMsg = 'Request timed out or was aborted';
          category = 'TIMEOUT';
        } else if (navigator.onLine === false) {
          errorMsg = 'No internet connection. Please check your network.';
          category = 'OFFLINE';
        } else {
          errorMsg = 'Laboratory server is unreachable. Please check connection.';
          category = 'SERVER_UNREACHABLE';
        }

        if (!options.silent && typeof window.Toast !== 'undefined') {
          window.Toast.show(errorMsg, 'error');
        }

        const netErr = new Error(errorMsg);
        netErr.category = category;
        netErr.originalError = err;
        throw netErr;
      }

      // 401 → try refresh once
      if (res.status === 401) {
        if (isLoginPage()) {
          await clearLocalAuthState({ skipLogoutCall: true });
          throw new Error('Unauthorized (on login page)');
        }

        if (options._retry) {
          await clearLocalAuthState();
          if (!isLoginPage()) {
            window.location.href = '/index.html';
          }
          throw new Error('Unauthorized');
        }

        if (!refreshPromise) {
          refreshPromise = (async () => {
            try {
              await refreshToken();
            } finally {
              refreshPromise = null;
            }
          })();
        }

        try {
          await refreshPromise;
        } catch (err) {
          await clearLocalAuthState();
          if (!isLoginPage()) {
            window.location.href = '/index.html';
          }
          throw err;
        }

        return _doNetworkFetch(method, path, body, { ...options, _retry: true }, requestKey, endpointKey, cachedData);
      }

      if (!res.ok) {
        let failState = failureCounters.get(endpointKey) || { count: 0, resetAt: 0 };
        failState.count++;
        if (failState.count >= 5) {
          failState.resetAt = Date.now() + 120000;
        }
        failureCounters.set(endpointKey, failState);

        let errData = {};
        try { errData = await res.json(); } catch (_) {}
        
        let msg = errData?.detail || errData?.message || errData?.error?.message;
        if (!msg) {
          if (res.status === 403) msg = 'Access denied: You do not have permission for this action.';
          else if (res.status === 404) msg = 'The requested diagnostic resource was not found.';
          else if (res.status === 429) msg = 'Too many requests. Please slow down and try again.';
          else if (res.status >= 500) msg = 'Laboratory server error. Please try again shortly.';
          else msg = `Request failed with status ${res.status}`;
        } else if (typeof msg === 'object' && msg !== null) {
          if (Array.isArray(msg)) {
            msg = msg.map(e => e.msg || e.message || JSON.stringify(e)).join(', ');
          } else {
            msg = msg.message || msg.detail || JSON.stringify(msg);
          }
        }

        if (!options.silent && typeof window.Toast !== 'undefined') {
          window.Toast.show(msg, 'error');
        }

        const err = new Error(msg);
        err.status = res.status;
        err.data = errData;
        err.category = res.status >= 500 ? 'SERVER_ERROR' : (res.status === 404 ? 'NOT_FOUND' : 'CLIENT_ERROR');
        throw err;
      }

      failureCounters.delete(endpointKey);

      if (res.status === 204) return null;

      const freshData = await res.json();

      if (!mutating && window.CacheManager && options.cache !== false) {
          if (cachedData) {
              if (JSON.stringify(freshData) !== JSON.stringify(cachedData)) {
                  await window.CacheManager.set(requestKey, freshData);
                  window.dispatchEvent(new CustomEvent(`cache-updated:${path.split('?')[0]}`, { detail: { data: freshData, path } }));
              }
          } else {
              await window.CacheManager.set(requestKey, freshData);
          }
      }

      return freshData;
    })();

    if (cachedData) {
        activeRequests.set(requestKey, reqPromise);
        reqPromise.catch(() => {}).finally(() => activeRequests.delete(requestKey));
    }

    return reqPromise;
  }

  async function request(method, path, body = null, options = {}) {
    const mutating = ['POST', 'PATCH', 'PUT', 'DELETE'].includes(method.toUpperCase());
    const endpointKey = `${method.toUpperCase()}:${path}`;
    const requestKey = `${endpointKey}:${body ? JSON.stringify(body) : ''}`;
    
    const failState = failureCounters.get(endpointKey);
    if (failState && failState.resetAt > Date.now()) {
      const remainingSeconds = Math.ceil((failState.resetAt - Date.now()) / 1000);
      if (!options.silent && typeof window.Toast !== 'undefined') {
        window.Toast.show(`Too many failed attempts. Please try again in ${remainingSeconds}s`, "error");
      }
      return new Promise(() => {});
    }

    if (mutating && window.CacheManager && !options.skipCache) {
       window.CacheManager.invalidate(path.split('?')[0]);
    }

    if (activeRequests.has(requestKey)) {
        if (mutating && !options.allowConcurrent) {
            console.warn("Blocked duplicate concurrent mutation:", requestKey);
            return new Promise(() => {});
        } else if (!mutating) {
            return activeRequests.get(requestKey);
        }
    }

    if (!mutating && window.CacheManager && options.cache !== false) {
       const cached = await window.CacheManager.get(requestKey);
       if (cached) {
           if (options.skipBackgroundRefresh) {
               return cached;
           }
           _doNetworkFetch(method, path, body, options, requestKey, endpointKey, cached);
           return cached;
       }
    }

    const promise = _doNetworkFetch(method, path, body, options, requestKey, endpointKey, null);
    activeRequests.set(requestKey, promise);
    try {
        return await promise;
    } finally {
        activeRequests.delete(requestKey);
    }
  }

    return {
      get:    (path, opts)         => request('GET',    path, null, opts),
      post:   (path, body, opts)   => request('POST',   path, body, opts),
      patch:  (path, body, opts)   => request('PATCH',  path, body, opts),
      put:    (path, body, opts)   => request('PUT',    path, body, opts),
      delete: (path, opts)         => request('DELETE', path, null, opts),
      // Raw request with full control
      raw:    (method, path, body, opts) => request(method, path, body, opts),
      uuidv4,
      clearLocalAuthState,
    };
  })();

window.API = API;

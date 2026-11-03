/**
 * Unit test for offline-queue.js data privacy, session binding, and logout purge (HIGH-03).
 */
const assert = require('assert');
const fs = require('fs');

// Mock browser environment for Node.js test execution
global.window = {
  addEventListener: () => {},
};
global.document = {
  readyState: 'complete',
  querySelector: () => null,
  addEventListener: () => {},
};
global.localStorage = {
  store: {},
  getItem(k) { return this.store[k] || null; },
  setItem(k, v) { this.store[k] = String(v); },
  removeItem(k) { delete this.store[k]; },
  clear() { this.store = {}; }
};

// Mock IndexedDB in-memory
class MockIDB {
  constructor() {
    this.records = [];
    this.autoId = 1;
  }
  open(name, ver) {
    const self = this;
    const req = {
      onsuccess: null,
      onerror: null,
      result: {
        objectStoreNames: { contains: () => true },
        transaction(storeName, mode) {
          const tx = {
            oncomplete: null,
            onerror: null,
            objectStore() {
              return {
                add(item) {
                  const saved = { ...item, id: self.autoId++ };
                  self.records.push(saved);
                  setTimeout(() => { if (tx.oncomplete) tx.oncomplete(); }, 1);
                  return saved;
                },
                put(item) {
                  const idx = self.records.findIndex(r => r.id === item.id);
                  if (idx >= 0) self.records[idx] = { ...item };
                  else self.records.push(item);
                  setTimeout(() => { if (tx.oncomplete) tx.oncomplete(); }, 1);
                },
                delete(id) {
                  self.records = self.records.filter(r => r.id !== id);
                  setTimeout(() => { if (tx.oncomplete) tx.oncomplete(); }, 1);
                },
                clear() {
                  self.records = [];
                  setTimeout(() => { if (tx.oncomplete) tx.oncomplete(); }, 1);
                },
                getAll() {
                  const r = { onsuccess: null, result: [...self.records] };
                  setTimeout(() => { if (r.onsuccess) r.onsuccess({ target: r }); }, 1);
                  return r;
                },
                openCursor() {
                  const r = { onsuccess: null };
                  let i = 0;
                  function step() {
                    if (i < self.records.length) {
                      const cur = {
                        value: self.records[i],
                        delete() {
                          self.records.splice(i, 1);
                          i--;
                        },
                        continue() {
                          i++;
                          step();
                        }
                      };
                      if (r.onsuccess) r.onsuccess({ target: { result: cur } });
                    } else {
                      if (r.onsuccess) r.onsuccess({ target: { result: null } });
                      setTimeout(() => { if (tx.oncomplete) tx.oncomplete(); }, 1);
                    }
                  }
                  setTimeout(step, 1);
                  return r;
                }
              };
            }
          };
          return tx;
        }
      }
    };
    setTimeout(() => {
      if (req.onsuccess) req.onsuccess({ target: req });
    }, 1);
    return req;
  }
}

global.indexedDB = new MockIDB();
global.BroadcastChannel = class { postMessage() {} };
global.navigator = { onLine: true };
global.fetch = async () => ({ ok: true, json: async () => ({}) });

// Load offline-queue.js
const code = fs.readFileSync('frontend/assets/js/offline-queue.js', 'utf-8');
eval(code);
const OfflineQueue = global.window.OfflineQueue;

async function runTests() {
  console.log("Running OfflineQueue privacy & purge tests...");

  // Test 1: Enqueue without user session should throw
  localStorage.clear();
  window._me = null;
  let threw = false;
  try {
    await OfflineQueue.enqueue('/api/v1/patients', 'POST', { name: 'Alice' }, 'key-1');
  } catch (err) {
    threw = true;
    assert(err.message.includes("active authenticated user session is required"), `Unexpected message: ${err.message}`);
  }
  assert(threw, "Expected enqueue without user session to throw error");
  console.log("  [PASS] Enqueue rejected when unauthenticated");

  // Test 2: Enqueue with user session sets ownerId
  localStorage.setItem('akriti_current_user', JSON.stringify({ id: 42, name: 'Staff User' }));
  const refId = await OfflineQueue.enqueue('/api/v1/patients', 'POST', { name: 'Alice' }, 'key-2');
  assert(refId.startsWith('TMP-'), "Expected valid temp ref id");

  const items = await OfflineQueue.getAll(true);
  assert.strictEqual(items.length, 1);
  assert.strictEqual(items[0].ownerId, "42");
  assert.strictEqual(items[0].payload.name, "Alice");
  console.log("  [PASS] Enqueue attaches correct ownerId");

  // Test 3: Unauthenticated getAll() returns empty array
  localStorage.clear();
  window._me = null;
  const loggedOutItems = await OfflineQueue.getAll(true);
  assert.strictEqual(loggedOutItems.length, 0, "Unauthenticated user must not see any patient records");
  console.log("  [PASS] Unauthenticated getAll() strictly hides patient records");

  // Test 4: Different user does not see first user's items
  localStorage.setItem('akriti_current_user', JSON.stringify({ id: 99, name: 'Other User' }));
  const otherUserItems = await OfflineQueue.getAll(true);
  assert.strictEqual(otherUserItems.length, 0, "Other user must not see user 42's records");
  console.log("  [PASS] Cross-user isolation verified");

  // Test 5: Logout clear() purges all records
  await OfflineQueue.clear();
  // Check under user 42 again
  localStorage.setItem('akriti_current_user', JSON.stringify({ id: 42, name: 'Staff User' }));
  const clearedItems = await OfflineQueue.getAll(true);
  assert.strictEqual(clearedItems.length, 0, "Queue must be empty after clear()");
  console.log("  [PASS] OfflineQueue.clear() purges records from IndexedDB");

  console.log("ALL OFFLINE QUEUE PRIVACY TESTS PASSED SUCCESSFULLY!");
  process.exit(0);
}

runTests().catch(err => {
  console.error("Test failed:", err);
  process.exit(1);
});

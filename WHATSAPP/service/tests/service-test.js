/**
 * Automated Test Suite for PathLab WhatsApp Microservice
 * Validates Configuration, Authentication Middleware, JID Formatting, and Health API.
 */
const assert = require('assert');
const http = require('http');

console.log('--- Running WhatsApp Microservice Automated Test Suite ---');

let passedTests = 0;
let totalTests = 0;

function runTest(name, fn) {
  totalTests++;
  try {
    fn();
    passedTests++;
    console.log(`  [PASS] ${name}`);
  } catch (err) {
    console.error(`  [FAIL] ${name}:`, err.message);
    process.exitCode = 1;
  }
}

async function runAsyncTest(name, fn) {
  totalTests++;
  try {
    await fn();
    passedTests++;
    console.log(`  [PASS] ${name}`);
  } catch (err) {
    console.error(`  [FAIL] ${name}:`, err.message);
    process.exitCode = 1;
  }
}

// ── 1. Configuration & Production Token Validation ──────────────────────────
const { validateConfig } = require('../src/config');

runTest('validateConfig rejects empty token in production', () => {
  const oldEnv = process.env.ENVIRONMENT;
  try {
    process.env.ENVIRONMENT = 'production';
    assert.throws(() => {
      validateConfig({ enabled: true, serviceToken: '' });
    }, /WHATSAPP_SERVICE_TOKEN must be configured/);
  } finally {
    process.env.ENVIRONMENT = oldEnv;
  }
});

runTest('validateConfig rejects insecure default placeholder in production', () => {
  const oldEnv = process.env.ENVIRONMENT;
  try {
    process.env.ENVIRONMENT = 'production';
    assert.throws(() => {
      validateConfig({
        enabled: true,
        serviceToken: 'pathlab_wa_sec_token_9f83a21b47c0e6'
      });
    }, /insecure/i);
  } finally {
    process.env.ENVIRONMENT = oldEnv;
  }
});

runTest('validateConfig rejects short token (<16 chars) in production', () => {
  const oldEnv = process.env.ENVIRONMENT;
  try {
    process.env.ENVIRONMENT = 'production';
    assert.throws(() => {
      validateConfig({
        enabled: true,
        serviceToken: 'short_token_123'
      });
    }, /minimum 16 chars/);
  } finally {
    process.env.ENVIRONMENT = oldEnv;
  }
});

runTest('validateConfig accepts strong high-entropy token in production', () => {
  const oldEnv = process.env.ENVIRONMENT;
  try {
    process.env.ENVIRONMENT = 'production';
    assert.doesNotThrow(() => {
      validateConfig({
        enabled: true,
        serviceToken: 'super_secure_production_secret_token_123456789'
      });
    });
  } finally {
    process.env.ENVIRONMENT = oldEnv;
  }
});

// ── 2. Auth Middleware Verification ─────────────────────────────────────────
const authMiddleware = require('../src/auth-middleware');
const config = require('../src/config');

runTest('authMiddleware permits /health without Authorization header', () => {
  let nextCalled = false;
  const req = { path: '/health', headers: {} };
  const res = {};
  authMiddleware(req, res, () => { nextCalled = true; });
  assert.strictEqual(nextCalled, true);
});

runTest('authMiddleware returns 401 when Authorization header is missing', () => {
  let statusCode = 0;
  let responseData = null;
  const req = { path: '/status', headers: {} };
  const res = {
    status(code) {
      statusCode = code;
      return this;
    },
    json(data) {
      responseData = data;
    }
  };
  authMiddleware(req, res, () => {
    assert.fail('next() should not be called');
  });
  assert.strictEqual(statusCode, 401);
  assert.strictEqual(responseData.success, false);
  assert.match(responseData.error, /Unauthorized/);
});

runTest('authMiddleware returns 403 when Authorization token is invalid', () => {
  let statusCode = 0;
  let responseData = null;
  const originalToken = config.serviceToken;
  config.serviceToken = 'correct_test_secret_token_12345';
  try {
    const req = {
      path: '/status',
      headers: { authorization: 'Bearer wrong_token_value_67890' }
    };
    const res = {
      status(code) {
        statusCode = code;
        return this;
      },
      json(data) {
        responseData = data;
      }
    };
    authMiddleware(req, res, () => {
      assert.fail('next() should not be called');
    });
    assert.strictEqual(statusCode, 403);
    assert.strictEqual(responseData.success, false);
    assert.match(responseData.error, /Forbidden/);
  } finally {
    config.serviceToken = originalToken;
  }
});

runTest('authMiddleware calls next() when valid Bearer token provided', () => {
  let nextCalled = false;
  const originalToken = config.serviceToken;
  const testToken = 'valid_secret_test_token_99999';
  config.serviceToken = testToken;
  try {
    const req = {
      path: '/status',
      headers: { authorization: `Bearer ${testToken}` }
    };
    const res = {};
    authMiddleware(req, res, () => {
      nextCalled = true;
    });
    assert.strictEqual(nextCalled, true);
  } finally {
    config.serviceToken = originalToken;
  }
});

// ── 3. Recipient JID Formatting Verification ────────────────────────────────
runTest('Recipient JID sanitizes and prepends India country code', () => {
  // Extract formatRecipientJid function
  let formatJid;
  const fs = require('fs');
  const path = require('path');
  const msgServiceCode = fs.readFileSync(path.join(__dirname, '../src/message-service.js'), 'utf8');
  const match = msgServiceCode.match(/function formatRecipientJid[\s\S]*?return `\${digits}@s\.whatsapp\.net`;\s*}/);
  assert(match, 'formatRecipientJid must be defined');
  eval(match[0]); // Defines formatRecipientJid

  // 10 digits -> prepends 91
  assert.strictEqual(formatRecipientJid('9876543210'), '919876543210@s.whatsapp.net');
  assert.strictEqual(formatRecipientJid('+91 98765-43210'), '919876543210@s.whatsapp.net');
  assert.strictEqual(formatRecipientJid('919876543210'), '919876543210@s.whatsapp.net');

  // Empty or invalid input
  assert.strictEqual(formatRecipientJid(''), null);
  assert.strictEqual(formatRecipientJid(null), null);
  assert.strictEqual(formatRecipientJid('abc-def'), null);
});

// ── 4. Live Health Check HTTP Server Endpoint ───────────────────────────────
async function runServerSuite() {
  const { app } = require('../src/server');

  await runAsyncTest('Express /health endpoint returns HTTP 200 and healthy JSON', async () => {
    const testServer = http.createServer(app);
    await new Promise((resolve) => testServer.listen(0, '127.0.0.1', resolve));
    const port = testServer.address().port;

    try {
      const response = await new Promise((resolve, reject) => {
        http.get(`http://127.0.0.1:${port}/health`, (res) => {
          let body = '';
          res.on('data', chunk => { body += chunk; });
          res.on('end', () => resolve({ statusCode: res.statusCode, body: JSON.parse(body) }));
        }).on('error', reject);
      });

      assert.strictEqual(response.statusCode, 200);
      assert.strictEqual(response.body.status, 'healthy');
      assert.strictEqual(response.body.service, 'pathlab-whatsapp-service');
      assert(response.body.timestamp);
    } finally {
      await new Promise(resolve => testServer.close(resolve));
    }
  });

  console.log(`\nWhatsApp Test Summary: ${passedTests}/${totalTests} tests passed.\n`);
  if (process.exitCode) {
    process.exit(1);
  }
}

runServerSuite();

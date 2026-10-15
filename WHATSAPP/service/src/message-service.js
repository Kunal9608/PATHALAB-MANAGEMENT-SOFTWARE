/**
 * WhatsApp Message Service
 * Handles recipient JID formatting, text and document dispatch,
 * in-memory idempotency deduplication, and timeout enforcement.
 */
const connectionManager = require('./connection-manager');
const config = require('./config');

// In-memory idempotency cache: key -> { timestamp, result }
const idempotencyCache = new Map();
const IDEMPOTENCY_TTL_MS = 10 * 60 * 1000; // 10 minutes

function cleanIdempotencyCache() {
  const now = Date.now();
  for (const [key, val] of idempotencyCache.entries()) {
    if (now - val.timestamp > IDEMPOTENCY_TTL_MS) {
      idempotencyCache.delete(key);
    }
  }
}
setInterval(cleanIdempotencyCache, 60 * 1000);

function formatRecipientJid(recipient) {
  if (!recipient) return null;
  let digits = String(recipient).replace(/\D/g, '');
  if (!digits) return null;
  // If 10 digits, assume India (+91)
  if (digits.length === 10) {
    digits = '91' + digits;
  }
  return `${digits}@s.whatsapp.net`;
}

async function withTimeout(promise, ms, operationName = 'Operation') {
  let timeoutHandle;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutHandle = setTimeout(() => {
      reject(new Error(`${operationName} timed out after ${ms / 1000} seconds`));
    }, ms);
  });
  try {
    const res = await Promise.race([promise, timeoutPromise]);
    clearTimeout(timeoutHandle);
    return res;
  } catch (err) {
    clearTimeout(timeoutHandle);
    throw err;
  }
}

class MessageService {
  async sendText(to, text, idempotencyKey = null) {
    if (idempotencyKey && idempotencyCache.has(idempotencyKey)) {
      const cached = idempotencyCache.get(idempotencyKey);
      return { ...cached.result, isDuplicate: true };
    }

    const sock = connectionManager.getSocket();
    if (!sock || connectionManager.status !== 'connected') {
      throw new Error('WhatsApp service is disconnected. Please connect via Admin Settings.');
    }

    const jid = formatRecipientJid(to);
    if (!jid) {
      throw new Error(`Invalid destination phone number: "${to}"`);
    }

    const sendPromise = sock.sendMessage(jid, { text });
    const response = await withTimeout(sendPromise, config.messageTimeoutMs, 'WhatsApp text send');

    const result = {
      success: true,
      messageId: response?.key?.id || null,
      to: jid.split('@')[0],
      timestamp: new Date().toISOString()
    };

    if (idempotencyKey) {
      idempotencyCache.set(idempotencyKey, { timestamp: Date.now(), result });
    }

    return result;
  }

  async sendDocument(to, buffer, fileName, caption = '', mimetype = 'application/pdf', idempotencyKey = null) {
    if (idempotencyKey && idempotencyCache.has(idempotencyKey)) {
      const cached = idempotencyCache.get(idempotencyKey);
      return { ...cached.result, isDuplicate: true };
    }

    const sock = connectionManager.getSocket();
    if (!sock || connectionManager.status !== 'connected') {
      throw new Error('WhatsApp service is disconnected. Please connect via Admin Settings.');
    }

    const jid = formatRecipientJid(to);
    if (!jid) {
      throw new Error(`Invalid destination phone number: "${to}"`);
    }

    const docBuffer = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer, 'base64');

    const sendPromise = sock.sendMessage(jid, {
      document: docBuffer,
      mimetype: mimetype || 'application/pdf',
      fileName: fileName || 'document.pdf',
      caption: caption || ''
    });

    const response = await withTimeout(sendPromise, config.messageTimeoutMs * 2, 'WhatsApp document send');

    const result = {
      success: true,
      messageId: response?.key?.id || null,
      to: jid.split('@')[0],
      fileName: fileName,
      timestamp: new Date().toISOString()
    };

    if (idempotencyKey) {
      idempotencyCache.set(idempotencyKey, { timestamp: Date.now(), result });
    }

    return result;
  }
}

module.exports = new MessageService();

/**
 * PathLab OS — Internal WhatsApp Service Entrypoint
 * Listens on configured port (default 3001), restricted to internal requests.
 */
const express = require('express');
const cors = require('cors');
const config = require('./config');
const internalAuth = require('./auth-middleware');
const connectionManager = require('./connection-manager');
const messageService = require('./message-service');

const app = express();

// Body parsers with safe size limits (5MB maximum)
app.use(express.json({ limit: '5mb' }));
app.use(express.urlencoded({ extended: true, limit: '5mb' }));

// Strict CORS configuration
app.use(cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (e.g. server-to-server HTTP calls from FastAPI)
    if (!origin) return callback(null, true);
    try {
      const originUrl = new URL(origin).origin;
      const isAllowed = config.allowedOrigins.some(ao => {
        try {
          return new URL(ao).origin === originUrl;
        } catch {
          return ao === originUrl;
        }
      });
      if (isAllowed) {
        return callback(null, true);
      }
      return callback(new Error('CORS origin denied'), false);
    } catch {
      return callback(new Error('Malformed CORS origin'), false);
    }
  },
  credentials: true
}));

// Apply authentication middleware to all routes except /health
app.use(internalAuth);

// ── Health Endpoint ─────────────────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'pathlab-whatsapp-service',
    timestamp: new Date().toISOString()
  });
});

// ── Status Endpoint ─────────────────────────────────────────────────────────
app.get('/status', (req, res) => {
  res.json({
    success: true,
    data: connectionManager.getStatus()
  });
});

// ── Connect Endpoint (Admin-triggered) ───────────────────────────────────────
app.post('/connect', async (req, res) => {
  try {
    const result = await connectionManager.connect();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// ── QR Code Endpoint ─────────────────────────────────────────────────────────
app.get('/qr', (req, res) => {
  const qrState = connectionManager.getQr();
  res.json({
    success: true,
    data: qrState
  });
});

// ── Disconnect Endpoint ─────────────────────────────────────────────────────
app.post('/disconnect', async (req, res) => {
  try {
    const result = await connectionManager.disconnect();
    res.json(result);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// ── Message Dispatch Endpoint ───────────────────────────────────────────────
app.post('/messages/send', async (req, res) => {
  const { to, text, type, document, fileName, caption, mimetype, idempotencyKey } = req.body;

  if (!to) {
    return res.status(400).json({ success: false, error: 'Destination number "to" is required' });
  }

  try {
    let result;
    if (type === 'document' || document) {
      if (!document) {
        return res.status(400).json({ success: false, error: 'Document base64 content is required' });
      }
      result = await messageService.sendDocument(
        to,
        document,
        fileName || 'report.pdf',
        caption || '',
        mimetype || 'application/pdf',
        idempotencyKey
      );
    } else {
      if (!text) {
        return res.status(400).json({ success: false, error: 'Message "text" is required' });
      }
      result = await messageService.sendText(to, text, idempotencyKey);
    }

    res.json({ success: true, data: result });
  } catch (err) {
    console.error(`[WhatsApp Send Error]: ${err.message}`);
    res.status(500).json({
      success: false,
      error: err.message
    });
  }
});

// Start Express Server
const server = app.listen(config.port, config.host, async () => {
  console.log(`[WhatsApp Service] Running on http://${config.host}:${config.port}`);
  // Auto-restore connection if session exists
  await connectionManager.initialize(true);
});

// Graceful shutdown
const shutdown = async () => {
  console.log('[WhatsApp Service] Shutting down gracefully...');
  server.close(async () => {
    try {
      const sock = connectionManager.getSocket();
      if (sock) sock.end(undefined);
    } catch {}
    process.exit(0);
  });
};

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// Prevent unhandled Baileys / socket errors from crashing the Node.js process
process.on('uncaughtException', (err) => {
  console.error('[WhatsApp Uncaught Exception]:', err.message || err);
});

process.on('unhandledRejection', (reason) => {
  console.error('[WhatsApp Unhandled Rejection]:', reason);
});

module.exports = { app, server };

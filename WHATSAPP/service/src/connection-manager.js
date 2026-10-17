/**
 * WhatsApp Connection Manager
 * Wraps @whiskeysockets/baileys multi-device socket connection,
 * persists session files, tracks connection state, and manages QR lifecycle.
 */
const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');
const pino = require('pino');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');

const config = require('./config');

const logger = pino({ level: 'silent' }); // Silent pino logger to avoid credential / raw token leakage

class ConnectionManager {
  constructor() {
    this.sock = null;
    this.status = 'disconnected'; // 'disconnected' | 'connecting' | 'qr_ready' | 'connected'
    this.qrDataUrl = null;
    this.qrRaw = null;
    this.qrGeneratedAt = null;
    this.qrExpiresAt = null;
    this.connectedUser = null;
    this.lastConnectedAt = null;
    this.lastDisconnectedAt = null;
    this.lastError = null;
    this.isConnecting = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;

    // Ensure session directory exists
    if (!fs.existsSync(config.sessionPath)) {
      fs.mkdirSync(config.sessionPath, { recursive: true });
    }
  }

  getStatus() {
    return {
      enabled: config.enabled,
      status: this.status,
      connected: this.status === 'connected',
      user: this.connectedUser,
      lastConnectedAt: this.lastConnectedAt,
      lastDisconnectedAt: this.lastDisconnectedAt,
      lastError: this.lastError ? this.lastError.message || String(this.lastError) : null,
      hasSavedSession: this._hasSavedSession()
    };
  }

  getQr() {
    const isExpired = this.qrExpiresAt && Date.now() > this.qrExpiresAt;
    return {
      status: this.status,
      qr: isExpired ? null : this.qrDataUrl,
      generatedAt: this.qrGeneratedAt,
      expiresAt: this.qrExpiresAt,
      isExpired: Boolean(isExpired)
    };
  }

  _hasSavedSession() {
    try {
      if (!fs.existsSync(config.sessionPath)) return false;
      const files = fs.readdirSync(config.sessionPath);
      return files.some(f => f.startsWith('creds.json'));
    } catch {
      return false;
    }
  }

  async initialize(autoRestore = true) {
    if (this._hasSavedSession() && autoRestore) {
      console.log('[WhatsApp] Found existing session, restoring connection...');
      await this.connect();
    } else {
      console.log('[WhatsApp] Ready. No active session. Awaiting Admin connect request.');
    }
  }

  async connect() {
    if (this.status === 'connected') {
      return { success: true, status: 'connected', message: 'Already connected' };
    }
    if (this.isConnecting) {
      return { success: true, status: this.status, message: 'Connection already in progress' };
    }

    this.isConnecting = true;
    this.status = 'connecting';
    this.lastError = null;

    try {
      const { state, saveCreds } = await useMultiFileAuthState(config.sessionPath);
      let version;
      try {
        const vInfo = await fetchLatestBaileysVersion();
        version = vInfo?.version;
      } catch (verErr) {
        // Fallback to internal Baileys version if network check fails
      }

      this.sock = makeWASocket({
        version,
        logger,
        printQRInTerminal: false,
        auth: state,
        syncFullHistory: false,
        connectTimeoutMs: config.messageTimeoutMs,
        keepAliveIntervalMs: 25000,
        defaultQueryTimeoutMs: config.messageTimeoutMs
      });

      // Bind credentials update
      this.sock.ev.on('creds.update', saveCreds);

      // Bind connection update
      this.sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
          try {
            this.qrRaw = qr;
            this.qrDataUrl = await QRCode.toDataURL(qr, {
              margin: 2,
              width: 280,
              color: { dark: '#0E5C4E', light: '#FFFFFF' }
            });
            this.qrGeneratedAt = new Date().toISOString();
            this.qrExpiresAt = Date.now() + 60000; // QR valid for 60 seconds
            this.status = 'qr_ready';
            console.log('\n[WhatsApp] >>> NEW QR CODE READY <<<');
            try {
              const terminalQR = await QRCode.toString(qr, { type: 'terminal', small: true });
              console.log(terminalQR);
            } catch (tErr) {}
            console.log('[WhatsApp] You can also view/scan the QR in Admin Settings: http://localhost:8000/admin/settings.html\n');
          } catch (err) {
            console.error('[WhatsApp] QR DataURL generation failed:', err.message);
          }
        }

        if (connection === 'close') {
          this.isConnecting = false;
          this.status = 'disconnected';
          this.lastDisconnectedAt = new Date().toISOString();
          const statusCode = lastDisconnect?.error?.output?.statusCode;
          const isReplaced = statusCode === DisconnectReason.connectionReplaced || statusCode === 440;
          const shouldReconnect = statusCode !== DisconnectReason.loggedOut && !isReplaced;

          this.lastError = lastDisconnect?.error || 'Connection closed';
          console.log(`[WhatsApp] Connection closed. Reason: ${statusCode}, Reconnect: ${shouldReconnect}`);

          if (statusCode === DisconnectReason.loggedOut) {
            console.log('[WhatsApp] Session logged out by device. Cleaning session credentials...');
            this._cleanSession();
          } else if (isReplaced) {
            console.log('[WhatsApp] Connection replaced by another session/process (Reason 440). Halting auto-reconnect to prevent duplicate session collision.');
          } else if (shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const backoffMs = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 15000);
            console.log(`[WhatsApp] Reconnecting in ${backoffMs / 1000}s (Attempt ${this.reconnectAttempts})...`);
            setTimeout(() => this.connect(), backoffMs);
          }
        } else if (connection === 'open') {
          this.isConnecting = false;
          this.status = 'connected';
          this.reconnectAttempts = 0;
          this.lastConnectedAt = new Date().toISOString();
          this.qrDataUrl = null;
          this.qrRaw = null;
          this.qrExpiresAt = null;

          const me = this.sock.user;
          const phone = me?.id ? me.id.split(':')[0].split('@')[0] : 'Unknown';
          this.connectedUser = {
            id: me?.id || null,
            phone: phone,
            name: me?.name || 'Akriti Diagnostics WhatsApp'
          };
          console.log(`[WhatsApp] Connection opened successfully! Connected as: +${phone}`);
        }
      });

      return {
        success: true,
        status: this.status,
        message: 'Connection initialization triggered'
      };
    } catch (err) {
      this.isConnecting = false;
      this.status = 'disconnected';
      this.lastError = err;
      console.error('[WhatsApp] Connection error:', err.message);
      return { success: false, error: err.message };
    }
  }

  async disconnect() {
    try {
      if (this.sock) {
        try {
          await this.sock.logout();
        } catch {}
        try {
          this.sock.end(undefined);
        } catch {}
      }
    } finally {
      this.sock = null;
      this.status = 'disconnected';
      this.connectedUser = null;
      this.qrDataUrl = null;
      this.qrRaw = null;
      this.lastDisconnectedAt = new Date().toISOString();
      this._cleanSession();
      console.log('[WhatsApp] Logged out and session cleared.');
      return { success: true, message: 'Disconnected and session cleared' };
    }
  }

  _cleanSession() {
    try {
      if (fs.existsSync(config.sessionPath)) {
        const files = fs.readdirSync(config.sessionPath);
        for (const file of files) {
          const p = path.join(config.sessionPath, file);
          try { fs.unlinkSync(p); } catch {}
        }
      }
    } catch (err) {
      console.error('[WhatsApp] Failed to clean session folder:', err.message);
    }
  }

  getSocket() {
    return this.sock;
  }
}

module.exports = new ConnectionManager();

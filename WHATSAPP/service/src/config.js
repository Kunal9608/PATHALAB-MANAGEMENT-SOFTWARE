/**
 * WhatsApp Service Configuration
 * Strictly loads from the root-level .env file.
 */
const path = require('path');
const fs = require('fs');
const dotenv = require('dotenv');

// Resolve the root .env file absolutely relative to project root
const ROOT_DIR = path.resolve(__dirname, '../../..');
const ROOT_ENV_PATH = path.join(ROOT_DIR, '.env');

if (fs.existsSync(ROOT_ENV_PATH)) {
  dotenv.config({ path: ROOT_ENV_PATH });
} else {
  console.warn(`[WARN] Root .env not found at ${ROOT_ENV_PATH}. Falling back to process.env.`);
}

const config = {
  // Service configuration
  enabled: process.env.WHATSAPP_ENABLED !== 'false',
  port: parseInt(process.env.WHATSAPP_SERVICE_PORT || '8005', 10),
  host: process.env.WHATSAPP_SERVICE_HOST || '0.0.0.0',
  serviceToken: process.env.WHATSAPP_SERVICE_TOKEN || '',

  // Session persistence path (defaults to root/WHATSAPP/session)
  sessionPath: path.resolve(
    ROOT_DIR,
    process.env.WHATSAPP_SESSION_PATH || 'WHATSAPP/session'
  ),

  // Operational limits
  messageTimeoutMs: parseInt(process.env.WHATSAPP_MESSAGE_TIMEOUT_SECONDS || '15', 10) * 1000,
  maxRetries: parseInt(process.env.WHATSAPP_MAX_RETRIES || '3', 10),
  otpExpirySeconds: parseInt(process.env.WHATSAPP_OTP_EXPIRY_SECONDS || '300', 10),
  resendCooldownSeconds: parseInt(process.env.WHATSAPP_OTP_RESEND_COOLDOWN_SECONDS || '60', 10),
  maxOtpAttempts: parseInt(process.env.WHATSAPP_MAX_OTP_ATTEMPTS || '3', 10),
  
  // CORS restriction
  allowedOrigins: (process.env.ALLOWED_ORIGINS || 'http://localhost:8000,http://127.0.0.1:8000')
    .split(',')
    .map(o => o.trim()),

  // Lab metadata
  labName: process.env.LAB_NAME || 'Akriti Diagnostics Center',
  labPhone: process.env.LAB_PHONE || '9876543210'
};

function validateConfig(cfg = config) {
  const isProd = process.env.NODE_ENV === 'production' || process.env.ENVIRONMENT === 'production';
  if (isProd && cfg.enabled) {
    const knownInsecure = ['pathlab_wa_sec_token_9f83a21b47c0e6', 'change_me', 'secret', 'password'];
    if (!cfg.serviceToken || knownInsecure.includes(cfg.serviceToken) || cfg.serviceToken.length < 16) {
      throw new Error('[FATAL] WHATSAPP_SERVICE_TOKEN must be configured with a secure token. Missing or using an insecure placeholder, or too short (minimum 16 chars) in production.');
    }
  }
}

// Perform validation on load if production
if (process.env.NODE_ENV === 'production' || process.env.ENVIRONMENT === 'production') {
  validateConfig(config);
}

module.exports = config;
module.exports.validateConfig = validateConfig;


/**
 * Internal Service Authentication Middleware
 * Enforces constant-time token verification.
 */
const crypto = require('crypto');
const config = require('./config');

function safeCompare(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

function internalAuthMiddleware(req, res, next) {
  // Allow health check without token
  if (req.path === '/health') {
    return next();
  }

  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({
      success: false,
      error: 'Unauthorized: Missing or malformed Authorization header'
    });
  }

  const token = authHeader.slice(7).trim();
  if (!config.serviceToken || !safeCompare(token, config.serviceToken)) {
    return res.status(403).json({
      success: false,
      error: 'Forbidden: Invalid service authentication token'
    });
  }

  next();
}

module.exports = internalAuthMiddleware;

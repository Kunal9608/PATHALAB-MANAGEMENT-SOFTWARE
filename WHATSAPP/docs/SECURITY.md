# PathLab OS — WhatsApp Security & Compliance Architecture

This document details the security model, cryptographic controls, and privacy standards enforced across the WhatsApp integration.

---

## 1. Internal Service Authentication

All requests between the FastAPI Core Backend and the WhatsApp Node.js Microservice require an internal service token:
- **Header**: `X-Service-Token: <WHATSAPP_SERVICE_TOKEN>`
- **Constant-Time Verification**: Comparison is performed using `crypto.timingSafeEqual` in Node.js to protect against timing side-channel attacks.
- **Fail-Closed Design**: If the token is missing, wrong, or mismatched in byte length, the microservice immediately returns HTTP `401 Unauthorized` without processing.

```javascript
// Timing-safe comparison in WHATSAPP/service/src/auth-middleware.js
const bufExpected = Buffer.from(expectedToken, 'utf8');
const bufProvided = Buffer.from(providedToken, 'utf8');
if (bufExpected.length !== bufProvided.length) return res.status(401).json(...);
if (!crypto.timingSafeEqual(bufExpected, bufProvided)) return res.status(401).json(...);
```

---

## 2. Role-Based Access Control (RBAC)

All WhatsApp administration endpoints are protected by FastAPI's `require_role(["admin"])` dependency:
- `POST /api/v1/whatsapp/connect`
- `GET /api/v1/whatsapp/qr`
- `POST /api/v1/whatsapp/disconnect`
- `POST /api/v1/whatsapp/test-message`

Non-admin roles (technicians, frontdesk, unauthorized users) receive HTTP `403 Forbidden`.

---

## 3. Session Credential Protection

- WhatsApp multi-device authentication keys are stored locally in `WHATSAPP/session/`.
- The session path is explicitly excluded in `.gitignore` to prevent any credentials, tokens, or encryption keys from being committed to source control.
- In production, session storage permissions should be restricted to the daemon execution user (`chmod 700`).

---

## 4. OTP Cryptographic Integrity & Anti-Brute-Force

Patient login and verification via WhatsApp OTP implements the following defenses:
1. **HMAC-SHA256 Hashing**: Plaintext OTP codes are never persisted in the database. Only HMAC-SHA256 hashes generated with `SECRET_KEY` are stored.
2. **Fixed Time-to-Live (TTL)**: OTPs expire in 300 seconds (5 minutes).
3. **Resend Cooldown**: Enforces a strict 60-second cooldown between consecutive OTP requests for the same mobile number.
4. **Maximum Attempt Throttling**: After 3 failed verification attempts, the OTP record is invalidated immediately to prevent brute-force enumeration.
5. **Constant-Time Hash Comparison**: Hash verification uses `hmac.compare_digest` in Python.

---

## 5. Patient Health Information (PHI) & Data Privacy

1. **No Medical Results in Message Text**: Push notifications via WhatsApp contain only metadata (Patient Name, Report ID, Bill status) and a secure, signed download URL. Sensitive clinical diagnostic values are never broadcast in plain text notifications.
2. **Direct Document Streaming**: PDF reports are streamed directly to WhatsApp's encrypted media store over TLS.
3. **Audit Logging**: All administrative actions (connect, disconnect, test messages) are logged to the `audit_logs` table with actor ID, IP address, and timestamp.

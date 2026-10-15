# PathLab OS — WhatsApp Troubleshooting & Operational Runbook

This guide covers common operational scenarios, diagnostic steps, and recovery procedures for the WhatsApp microservice.

---

## 1. Status Codes & Badges

| Badge Text | Status Code | Meaning | Action Needed |
|------------|-------------|---------|---------------|
| **Connected** (Green) | `connected` | WhatsApp session active & linked | None. Automated delivery active. |
| **Scan QR** (Amber) | `connecting` | Session initialized, waiting for phone scan | Scan QR code using WhatsApp on phone. |
| **Disconnected** (Grey) | `disconnected` | Service running but no session active | Click "Connect WhatsApp" to pair. |
| **Service Offline** (Red) | `offline` | Microservice not reachable on port 3001 | Start `node WHATSAPP/service/src/server.js`. |

---

## 2. Common Issues & Solutions

### Scenario A: "WhatsApp background microservice is offline or unreachable"
- **Cause**: Node.js service is not running or blocked by a firewall/port collision.
- **Diagnostic**:
  ```bash
  # Check if port 3001 is listening
  curl http://localhost:3001/health
  ```
- **Fix**:
  1. Verify port in root `.env` (`WHATSAPP_SERVICE_PORT=3001`).
  2. Launch service: `node WHATSAPP/service/src/server.js`.
  3. Ensure no duplicate process occupies port 3001 (`netstat -ano | findstr :3001`).

---

### Scenario B: QR Code Expired / Scan Doesn't Connect
- **Cause**: Baileys QR codes expire every 20-40 seconds for security.
- **Fix**:
  1. The Admin Settings interface polls automatically every 2.5 seconds and refreshes the QR image.
  2. If timeout occurs, click "Cancel" and then "Connect WhatsApp to Send OTP" to trigger a fresh pair handshake.

---

### Scenario C: WhatsApp Logged Out from Phone
- **Cause**: User manually tapped "Log out" in WhatsApp Linked Devices, or phone was inactive for > 14 days.
- **Fix**:
  1. In Admin Settings, click "Disconnect WhatsApp" to wipe stale session tokens.
  2. Click "Connect WhatsApp to Send OTP" and scan the newly generated QR code.

---

### Scenario D: Message Sending Times Out or Retries
- **Cause**: Phone is offline, poor network connectivity, or recipient number is not registered on WhatsApp.
- **Fix**:
  1. The FastAPI client automatically retries up to `WHATSAPP_MAX_RETRIES` (default: 2) with backoff.
  2. Verify recipient number format: Indian numbers must have 10 digits (the service prepends `91` automatically).
  3. Ensure the lab phone has an active internet connection.

---

### Scenario E: Duplicate Messages Prevented
- **Behavior**: The Node.js service maintains an in-memory 10-minute LRU cache of `idempotency_key` values.
- **Result**: If an identical retry occurs within 10 minutes with the same idempotency key, the microservice safely responds with `{ success: true, cached: true }` without sending a duplicate WhatsApp message.

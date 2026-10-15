# PathLab OS — WhatsApp Integration Setup Guide

This guide describes how to configure, run, and maintain the WhatsApp integration for Akriti Diagnostics Center / PathLab OS.

---

## 1. Architectural Architecture

PathLab OS uses a lightweight decoupled microservice architecture:
- **FastAPI Core Backend (Python)**: Handles lab business logic, patients, test bookings, diagnostic report generation, and triggers WhatsApp communications.
- **WhatsApp Microservice (Node.js + Baileys)**: Lightweight background daemon using `@whiskeysockets/baileys` to communicate directly via WhatsApp WebSockets without requiring Chromium, Puppeteer, or heavy browser engines (~15 MB RAM footprint).
- **Communication Bridge**: HTTP REST calls authenticated with a secure internal token (`WHATSAPP_SERVICE_TOKEN`).

```
┌─────────────────────────┐          HTTP + Token Auth          ┌─────────────────────────┐
│     FastAPI Backend     │ ──────────────────────────────────> │   WhatsApp Microservice │
│       (Port 8000)       │ <────────────────────────────────── │       (Port 3001)       │
└─────────────────────────┘                                     └────────────┬────────────┘
             │                                                               │  Native WebSocket
             ▼                                                               ▼
   PostgreSQL / Supabase                                              WhatsApp Cloud
 (OTP Hashes, Audit Logs)                                         (Delivery to Patients)
```

---

## 2. Prerequisites

1. **Node.js**: v18.0.0 or higher (Tested on Node v20/v24).
2. **Python**: v3.10 or higher with existing virtual environment (`backend/venv`).
3. **WhatsApp Business or Standard Account**: On a physical mobile phone to scan the QR code.

---

## 3. Environment Configuration

All settings must reside exclusively in the **root `.env` file**. Do **NOT** create a separate `.env` inside `WHATSAPP/`.

The following parameters are required in root `.env`:

```env
# ─── WHATSAPP INTEGRATION ──────────────────────────────────────────────────
WHATSAPP_ENABLED=true
WHATSAPP_SERVICE_URL=http://localhost:3001
WHATSAPP_SERVICE_PORT=3001
WHATSAPP_SERVICE_TOKEN=pathlab_wa_secret_token_change_in_production_99218
WHATSAPP_SESSION_PATH=WHATSAPP/session
WHATSAPP_OTP_EXPIRY_SECONDS=300
WHATSAPP_OTP_RESEND_COOLDOWN_SECONDS=60
WHATSAPP_MAX_OTP_ATTEMPTS=3
WHATSAPP_MESSAGE_TIMEOUT_SECONDS=15
WHATSAPP_MAX_RETRIES=2
```

---

## 4. Starting the Services

### Step 1: Start the WhatsApp Microservice
From the workspace root directory:
```bash
# Navigate to service directory and start daemon
cd WHATSAPP/service
npm start
# Alternatively, from root:
node WHATSAPP/service/src/server.js
```
Expected output:
```
[INFO] Root .env loaded from: ...
[INFO] WhatsApp Microservice listening on port 3001
[INFO] Session directory: .../WHATSAPP/session
[INFO] WhatsApp connection state: disconnected
```

### Step 2: Start the FastAPI Backend
In a separate terminal:
```bash
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

---

## 5. Pairing WhatsApp (Admin QR Scan)

1. Open the Admin Dashboard: `http://localhost:8000/admin/settings.html`.
2. Locate the **WhatsApp Integration** section.
3. Click **Connect WhatsApp to Send OTP**.
4. A QR code will display in real time with auto-refreshing polling.
5. On your lab's WhatsApp mobile device:
   - Go to **Settings** > **Linked Devices**.
   - Tap **Link a Device**.
   - Point your phone camera at the QR code displayed on screen.
6. Upon successful authentication:
   - The card transitions to **Connected** status (green badge).
   - The phone number and account name appear.
   - The session credentials are automatically saved to `WHATSAPP/session/` for multi-device persistence across server restarts.

---

## 6. Verifying Delivery

1. In Admin Settings, click **Send Test Message**.
2. Enter your 10-digit mobile number and click **Send Test**.
3. Verify receipt of the message on your WhatsApp account.

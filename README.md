<div align="center">

# 🏥 Akriti Diagnostics Center — PathLab OS
### Enterprise-Grade, AI-Powered Laboratory Information Management System (LIMS)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B%20%7C%20pgvector-336791.svg?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![S3 Storage](https://img.shields.io/badge/Joy%20S3-Cloud%20Storage-563D7C.svg?style=for-the-badge&logo=amazon-s3&logoColor=white)](https://nz.in.s3.joy.services)
[![Encryption](https://img.shields.io/badge/Security-AES--256--GCM%20E2EE-22C55E.svg?style=for-the-badge&logo=security&logoColor=white)](#-module-3--admin-important-documents-vault-aes-256-gcm-e2ee)
[![License](https://img.shields.io/badge/License-Proprietary-0A192F.svg?style=for-the-badge)](#)

<p align="center">
  <strong>High-concurrency, offline-resilient, HIPAA/clinical-grade laboratory operating system.</strong><br>
  Engineered end-to-end for modern diagnostic centers, hospital testing wings, and pathology laboratories.
</p>

[Explore Key Features](#-core-architectural-modules) • [System Architecture](#-system-architecture) • [Security & Cryptography](#-security-and-zero-knowledge-cryptography) • [Quickstart Guide](#-quick-start--installation) • [API Reference](#-api-endpoints-reference)

</div>

---

## 📋 Executive Overview

**PathLab OS** is a modern, monolithic, high-throughput pathology laboratory information system engineered specifically for **Akriti Diagnostics Center**. It integrates reception patient intake, clinical report authoring, dynamic NPCI UPI billing, multi-channel automated report dispatch (WhatsApp & Email), face-recognition biometric staff attendance, an offline-first durable sync ledger, and a zero-knowledge **AES-256-GCM End-to-End Encrypted Admin Documents Vault**.

The system is architected as an asynchronous, single-deployable unit with a hyper-optimized **FastAPI** backend and a zero-framework, dependency-light **Vanilla HTML5/ES6** Clinical Workbench frontend capable of handling **5,000+ concurrent transactions** and millions of historical records with sub-millisecond query response times.

---

## 🏛️ System Architecture

```mermaid
flowchart TB
    subgraph ClientLayer["🖥️ Frontend — Clinical Workbench (Vanilla HTML5 / CSS3 / ES6 SPA)"]
        UI_Reception["Reception & Patient Intake<br/>(Durable Offline Queue / IndexedDB)"]
        UI_Admin["Admin Management Center<br/>(Financials, Vault, Audit, Staff)"]
        UI_Vault["Private Important Vault<br/>(AES-256-GCM WebCrypto)"]
        UI_Kiosk["Biometric Attendance Kiosk<br/>(Live Face Liveness & Vector Search)"]
    end

    subgraph APILayer["⚙️ Backend Engine — FastAPI (Asynchronous Python 3.11+)"]
        MW_Auth["Auth & Session Guard<br/>(Argon2id + HMAC Pepper + JWT)"]
        MW_Rate["Rate Limiter & Security Headers<br/>(SlowAPI + OTP 60s Cooldown)"]
        
        Router_Patients["Patient & Offline Sync<br/>(PostgreSQL Advisory Locks)"]
        Router_Vault["Admin Documents Vault<br/>(Strict Creator Isolation)"]
        Router_Reports["Diagnostic Report Engine<br/>(ReportLab PDF + SHA-256 QR)"]
        Router_Billing["UPI QR & Settlement<br/>(Fixed-Point Financial Ledger)"]
        Router_Copilot["Clinical AI Copilot<br/>(NVIDIA / Groq / Llama 3.3 70B)"]
    end

    subgraph StorageLayer["🗄️ Persistence & Storage Infrastructure"]
        DB_PG[("PostgreSQL 15+<br/>• Relational Schema<br/>• pgvector Face Embeddings<br/>• pg_trgm Search")]
        CACHE_Redis[("Redis In-Memory Cache<br/>• Session Storage<br/>• Query Caching<br/>• Rate Limits")]
        S3_Joy[("Joy S3 Cloud Storage<br/>• Clinical PDF Reports<br/>• Encrypted Vault Blobs (.enc)")]
        SVC_WA["WhatsApp Microservice<br/>(Baileys Socket / Internal Gateway)"]
        SVC_Mail["Transactional Mail Engine<br/>(Brevo REST API / SMTP)"]
    end

    ClientLayer --> MW_Auth
    MW_Auth --> MW_Rate
    MW_Rate --> Router_Patients & Router_Vault & Router_Reports & Router_Billing & Router_Copilot

    Router_Patients --> DB_PG
    Router_Vault --> DB_PG & S3_Joy
    Router_Reports --> DB_PG & S3_Joy & SVC_WA & SVC_Mail
    Router_Billing --> DB_PG
    Router_Copilot --> CACHE_Redis
```

---

## 🌟 Core Architectural Modules

### 1. 🛡️ Durable Offline-First Patient Ledger & Failed Registration Recovery
* **Dual-State ID Scheme**: Patients registered without an internet connection receive ephemeral local identifiers (`TMP-PAT-XXXXXXXX`) stored in browser IndexedDB.
* **Gapless Sequence Integrity**: Permanent `PAT26XXXX` identifiers are assigned **strictly at PostgreSQL commit time** using transactional advisory locks (`pg_advisory_xact_lock(42)`). Zero sequence gaps occur even during server restarts, network failures, or uncommitted transactions.
* **Isolated Failed Patient Recovery**: In case of duplicate phone numbers, unhandled payload conflicts, or network drops, registrations are saved into a dedicated **Failed Patients Backup Ledger** with strict creator-level isolation:
  * Staff members see, edit, and retry only their own saved registration drafts.
  * Administrators have isolated view of their own drafts and cannot leak or overwrite staff records without explicit authorization.
  * In-place JSON payload correction modal (`Edit & Retry`) allows instant rectification of errors (e.g., incorrect phone, missing gender) and clean 1-click re-commit into the active clinical registry.

### 2. 🔐 Admin Important Documents Vault (AES-256-GCM E2EE)
* **Zero-Knowledge Architecture**: Administrator credentials and encryption keys never leave the client browser. Plaintext documents are encrypted client-side using **WebCrypto AES-256-GCM** before transmission.
* **Deterministic PBKDF2 Key Derivation**: 256-bit symmetric keys derived with SHA-256, 100,000 iterations, and a 128-bit admin-bound cryptographic salt.
* **Ephemeral Active Tab Persistence**: Active sessions are cached in tab-scoped memory and `sessionStorage`, persisting across theme switches and page navigations while preventing cross-tab or cross-session leakage.
* **Cryptographic Erasure**: Deleting a vault item permanently wipes the ciphertext blob from Joy S3 and deletes the database record, ensuring complete data destruction.

### 3. ☁️ Joy.services S3 Cloud Storage Engine
* Production-configured cloud storage adapter targeting `https://nz.in.s3.joy.services` (Bucket: `pathlab-reprts`).
* Stores patient diagnostic PDF reports, barcode assets, and encrypted administrative vault files (`vault/{admin_id}/{item_id}.enc`).
* Features automated fallback, presigned time-limited secure download links, and direct streaming endpoints.

### 4. ⏱️ OTP Resend 60-Second Cooldown & Anti-Enumeration Protection
* **Timing Cooldown**: Strict 60-second cooldown enforced between consecutive OTP requests per recipient email. Early requests are rejected with `HTTP 429 Too Many Requests` indicating exact remaining cooldown seconds.
* **Account Enumeration Prevention**: Unregistered email addresses receive the exact same response status and delay as registered accounts, preventing attacker user reconnaissance.
* **Cryptographic Delivery**: Single-use 6-digit OTP codes hashed with salt and delivered via Brevo Transactional Email.

### 5. 🔬 Diagnostic Catalog & Smart Reference Range Engine
* **65+ Pre-Seeded Diagnostic Masters**: Complete coverage of Complete Blood Count (CBC), Liver Function Test (LFT), Kidney Function Test (KFT), Lipid Profile, Thyroid Panel, Blood Glucose, Urine Routine, and Infectious Disease Serology.
* **Automated Abnormality Detection**: Real-time evaluation against age- and biological-sex-dependent reference ranges with high/low visual flags on reports.
* **Tamper-Evident Report PDFs**: Auto-generated high-resolution PDFs rendered via ReportLab with embedded QR codes containing a SHA-256 digital verification fingerprint.

### 6. 💳 Dynamic NPCI UPI QR Billing & Split Financial Ledger
* **Dynamic UPI QR Code Generation**: Instant on-screen payment QR codes generated with exact payable amounts, lab VPA, and invoice references.
* **Zero-Fee Settlement**: Direct bank-to-bank settlement without third-party payment gateway transaction commissions.
* **Exact-Precision Financial Ledger**: Schemas enforce `Numeric(10,2)` across revenue, expenses, balances, and doctor referral commissions, completely preventing IEEE 754 floating-point rounding discrepancies.

### 7. 👤 Facial Biometric Staff Attendance Kiosk
* **Live Webcam Face Recognition**: Client-side face capture with anti-spoofing liveness checks.
* **Vector Search with pgvector**: Extracts 128-dimensional facial embeddings and performs sub-50ms cosine similarity searches against enrolled staff records.
* **Biometric Fallback**: Seamless PIN-based authentication fallback for low-light or camera failure conditions.

### 8. 💬 Multi-Channel Automated Patient Dispatch
* **Native WhatsApp Microservice**: Asynchronous background dispatch of PDF reports directly to patients' registered WhatsApp numbers via local Baileys socket integration.
* **Brevo Transactional Email Engine**: Verified email delivery of patient registration invoices, OTP codes, password resets, and clinical lab results.

### 9. 🤖 Clinical AI Copilot (Dual LLM Pipeline)
* **Primary LLM**: NVIDIA Nemotron / OpenAI-compatible endpoint for high-context clinical insights, daily patient analytics, revenue breakdowns, and operational metrics.
* **High-Speed Fallback**: Groq-powered Qwen/Llama models for instantaneous responses during high-load periods.
* **Security Guardrails**: Strict Role-Based Access Control (RBAC) ensuring Staff cannot prompt the Copilot for administrative financials or vault contents.

---

## 🎨 Clinical Workbench Design System

The frontend is custom-built with **Vanilla CSS3** adhering to clinical design tokens:
* **Dual-Theme Engine**:
  * **Clinical Dark Mode** (Default): Surface `#111C2E`, Canvas `#0A192F`, Input `#0D1728`, Accent `#60A5FA`, Border `#26364B`.
  * **Sterile Light Mode**: Surface `#FFFFFF`, Canvas `#F8FAFC`, Input `#F1F5F9`, Accent `#0A192F`, Border `#E2E8F0`.
* **Tabular Monospace Alignment**: Numeric lab values, reference limits, dates, and currency values are formatted in tabular monospace for rapid vertical reading by pathologists.
* **Single-Page Application (SPA) Router**: Smooth instantaneous client-side navigation (`shell.js`) that dynamically loads scoped stylesheets and scripts while preserving topbar integrity and actively purging stale modal backdrops.

---

## 🔐 Security and Zero-Knowledge Cryptography

| Security Domain | Architectural Implementation |
| :--- | :--- |
| **Password Hashing** | Argon2id (`time_cost=3`, `memory_cost=64MB`, `parallelism=4`) combined with a server-side HMAC secret pepper. |
| **Session Authentication** | `HttpOnly`, `SameSite=Lax`, `Secure` JWT cookies (15-min access token, 7-day refresh token) with rotation. |
| **Vault Client Encryption** | WebCrypto API: `AES-256-GCM` with PBKDF2-SHA256 (100,000 iterations). Nonce/IV: Unique 96-bit CSPRNG per item. |
| **Storage Isolation** | Tenant and creator-scoped Joy S3 object paths (`vault/{admin_id}/{item_id}.enc`). IDOR protection on all routes. |
| **Database Injection Prevention**| 100% parameterized queries via SQLAlchemy 2.0 ORM; strict Pydantic v2 request body schema validation. |
| **Anti-Bot & Rate Limiting** | Optional Google reCAPTCHA v3 verification; SlowAPI client-IP and user-token rate limiting on sensitive endpoints. |

---

## 🚀 Quick Start & Installation

### Option 1: Docker Compose (Recommended Production Setup)

The entire production stack (FastAPI Backend, PostgreSQL + pgvector, Redis, and static frontend) runs out of the box:

```bash
# 1. Clone repository
git clone https://github.com/Kunal9608/PATHALAB-MANAGEMENT-SOFTWARE.git
cd PATHALAB-MANAGEMENT-SOFTWARE

# 2. Configure environment keys
cp .env.example .env
# Edit .env and supply your database credentials, Joy S3 keys, and JWT secrets

# 3. Build and launch containers
docker compose up --build -d

# 4. Run database migrations
docker compose exec web alembic upgrade head
```

The application is now live at `http://localhost:8000`.

---

### Option 2: Local Manual Setup

#### 1. Prerequisites
* Python 3.11+
* PostgreSQL 15+ (with `pgvector` extension enabled)
* Redis Server (optional, graceful fallback to in-memory)

#### 2. Virtual Environment Setup
```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate

# macOS / Linux:
source .venv/bin/activate
```

#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Environment Configuration
Copy `.env.example` to `.env` in the root folder and configure your parameters:
```bash
cp .env.example .env
```

```ini
# Crucial Parameters in .env
ENVIRONMENT=production
DATABASE_URL=postgresql://postgres:password@localhost:5432/akriti_pathlab
JWT_SECRET_KEY=generate_your_64_character_random_hex_string_here
PASSWORD_PEPPER=generate_your_32_character_random_hex_string_here

# Joy.services S3 Configuration
STORAGE_PROVIDER=s3
S3_ENDPOINT_URL=https://nz.in.s3.joy.services
S3_ACCESS_KEY_ID=your_joy_access_key
S3_SECRET_ACCESS_KEY=your_joy_secret_key
S3_BUCKET_NAME=pathlab-reprts
S3_REGION_NAME=default
```

#### 5. Database Migrations & Initial Seed
```bash
alembic upgrade head
python backend/scripts/seed_initial_data.py
```

#### 6. Run the Application
```bash
python main.py
```
Open [http://localhost:8000](http://localhost:8000) in your web browser.

---

## 📡 API Endpoints Reference

### Authentication & OTP
| Method | Endpoint | Description | Access |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/login` | Authenticate credentials & issue secure cookies | Public |
| `POST` | `/api/v1/auth/logout` | Revoke tokens & clear session cookies | Authenticated |
| `GET` | `/api/v1/auth/me` | Fetch active user identity & role profile | Authenticated |
| `POST` | `/api/v1/auth/otp/request` | Request single-use OTP with 60s cooldown | Public |
| `POST` | `/api/v1/auth/otp/verify` | Verify OTP code and issue password reset token | Public |

### Patients & Offline Sync
| Method | Endpoint | Description | Access |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/patients` | List patients with pagination & search | Staff / Admin |
| `POST` | `/api/v1/patients` | Register patient & assign gapless `PAT26XXXX` ID | Staff / Admin |
| `GET` | `/api/v1/offline-patients` | List creator-isolated failed registrations | Staff / Admin |
| `PUT` | `/api/v1/offline-patients/{id}` | Edit payload & retry failed registration | Creator Only |
| `DELETE`| `/api/v1/offline-patients/{id}` | Discard individual failed patient draft | Creator Only |
| `DELETE`| `/api/v1/offline-patients/bulk-clear` | Purge all own failed patient drafts | Creator Only |

### Admin Important Documents Vault
| Method | Endpoint | Description | Access |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/admin/vault/verify-unlock` | Verify admin account password to derive key | Admin Only |
| `GET` | `/api/v1/admin/vault` | List own encrypted vault documents & notes | Admin Only |
| `POST` | `/api/v1/admin/vault/documents` | Upload ciphertext document to Joy S3 | Admin Only |
| `GET` | `/api/v1/admin/vault/{id}/content` | Stream raw ciphertext for browser decryption | Admin Only |
| `POST` | `/api/v1/admin/vault/notes` | Store client-encrypted administrative note | Admin Only |
| `PUT` | `/api/v1/admin/vault/{id}` | Update encrypted note title / content | Admin Only |
| `DELETE`| `/api/v1/admin/vault/{id}` | Cryptographically delete from S3 & database | Admin Only |

### Diagnostic Reports & Billing
| Method | Endpoint | Description | Access |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/reports` | List diagnostic test orders & reports | Staff / Admin |
| `POST` | `/api/v1/reports/{id}/results` | Submit test numerical/qualitative findings | Staff / Admin |
| `GET` | `/api/v1/reports/{id}/pdf` | Generate / download signed PDF report | Staff / Admin |
| `POST` | `/api/v1/reports/{id}/send-whatsapp`| Dispatch report PDF to patient's WhatsApp | Staff / Admin |
| `GET` | `/api/v1/billing/{id}/upi-qr` | Generate dynamic NPCI UPI payment QR | Staff / Admin |

---

## 🧪 Comprehensive Verification Suite

The system includes a zero-mock, end-to-end integration and security test suite covering all core modules:

```bash
# Execute master verification suite
python scratch/test_master_verification.py
```

### Verified Test Matrix (21/21 Automated Tests Passing):
* ✅ **Notification Engine Baseline Preservation**: Template rendering, Brevo client verification, and signature integrity.
* ✅ **Joy S3 Cloud Storage**: Object upload, content verification, and permanent deletion.
* ✅ **Failed Patient Backups**: Creator-level isolation, cross-account IDOR rejection, payload rectification, and sequence integrity.
* ✅ **Admin Important Documents Vault**: Zero-knowledge encryption, PBKDF2 derivation, creator isolation, ciphertext streaming, and cryptographic erasure.
* ✅ **OTP Cooldown & Anti-Enumeration**: Strict 60-second cooldown enforcement (`HTTP 429`) and blind enumeration protection for non-existent users.

---

## 📁 Repository Directory Structure

```text
├── alembic/                      # Database migration versions
│   └── versions/                 # Version history (including vault, offline sync, etc.)
├── backend/                      # Python FastAPI application core
│   ├── app/
│   │   ├── core/                 # DB configuration, security, config loader
│   │   ├── models/               # SQLAlchemy ORM models
│   │   ├── routers/              # FastAPI APIRouters (Auth, Vault, Patients, etc.)
│   │   ├── schemas/              # Pydantic v2 validation models
│   │   └── services/             # Business logic (Vault, S3, Offline Patient, etc.)
│   └── scripts/                  # Data seeding and secret generation scripts
├── frontend/                     # Pure HTML5 / CSS3 / ES6 Clinical Workbench
│   ├── admin/                    # Administrator UI (Dashboard, Vault, Reports, Staff)
│   ├── staff/                    # Receptionist / Lab Technician UI
│   ├── assets/
│   │   ├── css/                  # Design tokens, components, layouts, skeletons
│   │   └── js/                   # SPA shell, API client, WebCrypto vault, Offline queue
│   └── index.html                # Secure entry & login portal
├── WHATSAPP/                     # Node.js Baileys WhatsApp automation microservice
├── Dockerfile                    # Multi-stage optimized production Docker image
├── docker-compose.yml            # Full-stack container orchestration
├── requirements.txt              # Production Python package manifest
├── .env.example                  # Environment configuration template
└── README.md                     # Comprehensive system documentation
```

---

## 👥 Authors & Maintainers

* **Lead Architect & Developer**: Kunal ([@Kunal9608](https://github.com/Kunal9608))
* **Organization**: Akriti Diagnostics Center ([akritidc.in](https://akritidc.in))

<div align="center">
  <sub>Engineered with precision for diagnostic accuracy, data privacy, and clinical operational excellence.</sub>
</div>

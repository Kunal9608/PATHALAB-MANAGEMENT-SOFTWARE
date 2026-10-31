"""
Akriti Lab — Application Settings
Loads all configuration from environment variables / .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator
from typing import List, Set, ClassVar, Optional
import os


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/akriti_lab"

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if v and v.startswith("postgresql://") and not v.startswith("postgresql+"):
            v = v.replace("postgresql://", "postgresql+psycopg2://", 1)
        if v and "supabase" in v and "sslmode" not in v:
            separator = "&" if "?" in v else "?"
            v = f"{v}{separator}sslmode=require"
        return v

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = True
    REDIS_DEFAULT_TTL: int = 300
    REDIS_NEGATIVE_TTL: int = 60
    REDIS_FINANCE_TTL: int = 60
    REDIS_SSL_VERIFY: bool = True
    REDIS_SSL_CA_CERTS: Optional[str] = None

    @field_validator("REDIS_URL", mode="after")
    @classmethod
    def normalize_redis_url(cls, v: str) -> str:
        if v and "localhost" in v and (os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER")):
            import socket
            try:
                socket.gethostbyname("redis")
                return v.replace("localhost", "redis")
            except Exception:
                pass
        return v

    # Cryptographic Peppers & Keys
    PASSWORD_PEPPER: str = ""
    AADHAAR_PEPPER: str = ""
    JWT_SECRET_KEY: str = "change-this-secret"
    JWT_ACCESS_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    JWT_REFRESH_EXPIRE_HOURS: int = 168
    JWT_ALGORITHM: str = "HS256"

    INSECURE_JWT_PLACEHOLDERS: ClassVar[Set[str]] = {
        "change-this-secret",
        "secret",
        "jwt-secret",
        "your-secret-key",
        "your-secret",
        "generate_your_64_char_secure_random_string_here",
        "generate_your_32_char_secure_random_string_here",
        "password",
        "admin",
        "12345678",
        "default",
    }

    @model_validator(mode="after")
    def validate_jwt_and_auth_settings(self):
        # Sync refresh token expiry hours
        if self.JWT_REFRESH_EXPIRE_DAYS:
            self.JWT_REFRESH_EXPIRE_HOURS = self.JWT_REFRESH_EXPIRE_DAYS * 24

        # Validate JWT signing algorithm (strictly allow secure symmetric algorithms)
        allowed_algorithms = {"HS256", "HS384", "HS512"}
        algo = (self.JWT_ALGORITHM or "").strip().upper()
        if not algo or algo not in allowed_algorithms:
            raise ValueError(
                f"Invalid or insecure JWT_ALGORITHM '{self.JWT_ALGORITHM}'. "
                f"Allowed symmetric algorithms: {', '.join(sorted(allowed_algorithms))}."
            )

        # Validate JWT signing secret key
        key = (self.JWT_SECRET_KEY or "").strip()
        if not key:
            raise ValueError("JWT_SECRET_KEY must not be empty.")

        key_lower = key.lower()
        is_placeholder = key_lower in self.INSECURE_JWT_PLACEHOLDERS

        if self.is_production:
            if is_placeholder:
                raise ValueError(
                    "JWT_SECRET_KEY is using an insecure default or placeholder value in production. "
                    "Production requires an explicitly configured, cryptographically secure random secret."
                )
            if len(key) < 32:
                raise ValueError(
                    f"JWT_SECRET_KEY is too short ({len(key)} characters) for production. "
                    "Cryptographic signing with HMAC-SHA256 requires at least 32 characters (256 bits)."
                )
            if len(set(key)) < 10:
                raise ValueError(
                    "JWT_SECRET_KEY has insufficient character diversity / entropy. "
                    "Repetitive or predictable strings cannot be used as production secrets. "
                    "Generate a cryptographically secure random key using a CSPRNG."
                )

            # Validate PASSWORD_PEPPER in production
            pw_pepper = (self.PASSWORD_PEPPER or "").strip()
            if not pw_pepper:
                raise ValueError(
                    "PASSWORD_PEPPER must be configured in production. "
                    "Production requires a dedicated 32+ character cryptographically secure pepper."
                )
            if pw_pepper.lower() in self.INSECURE_JWT_PLACEHOLDERS or len(pw_pepper) < 32 or len(set(pw_pepper)) < 8:
                raise ValueError(
                    f"PASSWORD_PEPPER is using an insecure placeholder, too short ({len(pw_pepper)} chars), or lacks entropy in production. "
                    "Production requires at least 32 high-entropy random characters."
                )

            # Validate AADHAAR_PEPPER in production
            aadhaar_pep = (self.AADHAAR_PEPPER or "").strip()
            if not aadhaar_pep:
                raise ValueError(
                    "AADHAAR_PEPPER must be configured in production. "
                    "Keyed HMAC protection for sensitive Aadhaar IDs requires a dedicated 32+ character pepper."
                )
            if aadhaar_pep.lower() in self.INSECURE_JWT_PLACEHOLDERS or len(aadhaar_pep) < 32 or len(set(aadhaar_pep)) < 8:
                raise ValueError(
                    f"AADHAAR_PEPPER is using an insecure placeholder, too short ({len(aadhaar_pep)} chars), or lacks entropy in production."
                )
            if aadhaar_pep == pw_pepper:
                raise ValueError(
                    "AADHAAR_PEPPER must not be identical to PASSWORD_PEPPER. "
                    "Cryptographic domain separation requires distinct peppers."
                )

            # Validate reCAPTCHA keys in production
            if self.ENABLE_RECAPTCHA:
                if self.RECAPTCHA_SECRET_KEY in {
                    "6LeIxAcTAAAAAGG-vFI1TnFTxWGRtAUMuO_FnD4Q",
                    "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe",
                }:
                    raise ValueError("Cannot use Google reCAPTCHA public test secret key in production.")

            # Validate WhatsApp service token in production
            if self.WHATSAPP_ENABLED:
                wa_token = (self.WHATSAPP_SERVICE_TOKEN or "").strip()
                if not wa_token or wa_token == "pathlab_wa_sec_token_9f83a21b47c0e6" or wa_token.lower() in self.INSECURE_JWT_PLACEHOLDERS:
                    raise ValueError(
                        "WHATSAPP_SERVICE_TOKEN is missing or using an insecure default placeholder in production. "
                        "Configure a unique, high-entropy secret token for WhatsApp service authentication."
                    )
                if len(wa_token) < 16:
                    raise ValueError(
                        f"WHATSAPP_SERVICE_TOKEN is too short ({len(wa_token)} chars) for production. Minimum 16 characters required."
                    )

            # Validate Redis TLS verification in production
            if self.REDIS_URL.startswith("rediss://"):
                if not self.REDIS_SSL_VERIFY:
                    raise ValueError(
                        "REDIS_SSL_VERIFY cannot be False in production for rediss:// connections. "
                        "TLS certificate verification is required to prevent man-in-the-middle attacks."
                    )

        return self

    # Email
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "kunaldixit.2995@gmail.com"
    MAIL_FROM_NAME: str = "Akriti Diagnostics Center"
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_TLS: bool = True
    MAIL_SSL: bool = False
    BREVO_API_KEY: str = ""
    WASENDER_API_KEY: str = ""


    # Lab
    LAB_UPI_VPA: str = "akritilab@upi"
    LAB_NAME: str = "Akriti Diagnostics Center"
    LAB_ADDRESS: str = ""
    LAB_PHONE: str = ""
    LAB_GSTIN: str = ""

    # --- LLM / AI Copilot Settings ---
    LLM_PROVIDER: str = "groq"  # "groq", "nvidia", "openai", "custom"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: float = 0.6
    LLM_TOP_P: float = 0.95
    LLM_MAX_TOKENS: int = 600

    COPILOT_LIMIT_ADMIN: int = 10
    COPILOT_LIMIT_STAFF: int = 5

    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "qwen/qwen3.8-27b"

    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    @property
    def effective_llm_api_key(self) -> str:
        if self.LLM_API_KEY:
            return self.LLM_API_KEY
        provider = (self.LLM_PROVIDER or "").lower()
        if provider == "groq" and self.GROQ_API_KEY:
            return self.GROQ_API_KEY
        if provider == "nvidia" and self.NVIDIA_API_KEY:
            return self.NVIDIA_API_KEY
        if provider == "openai" and self.OPENAI_API_KEY:
            return self.OPENAI_API_KEY
        return self.NVIDIA_API_KEY or self.GROQ_API_KEY or self.OPENAI_API_KEY or ""

    @property
    def effective_llm_base_url(self) -> str:
        if self.LLM_BASE_URL:
            return self.LLM_BASE_URL
        provider = (self.LLM_PROVIDER or "").lower()
        if provider == "groq":
            return self.GROQ_BASE_URL or "https://api.groq.com/openai/v1"
        if provider == "nvidia":
            return self.NVIDIA_BASE_URL or "https://integrate.api.nvidia.com/v1"
        if provider == "openai":
            return self.OPENAI_BASE_URL or "https://api.openai.com/v1"
        if self.NVIDIA_API_KEY:
            return self.NVIDIA_BASE_URL or "https://integrate.api.nvidia.com/v1"
        if self.GROQ_API_KEY:
            return self.GROQ_BASE_URL or "https://api.groq.com/openai/v1"
        return self.OPENAI_BASE_URL or "https://api.openai.com/v1"

    @property
    def effective_llm_model(self) -> str:
        if self.LLM_MODEL:
            return self.LLM_MODEL
        provider = (self.LLM_PROVIDER or "").lower()
        if provider == "groq":
            return self.GROQ_MODEL or "qwen/qwen3.8-27b"
        if provider == "nvidia":
            return self.NVIDIA_MODEL or "nvidia/nemotron-3.5-lightning-30b-a3b"
        if provider == "openai":
            return "gpt-4o-mini"
        if self.NVIDIA_API_KEY:
            return self.NVIDIA_MODEL or "nvidia/nemotron-3.5-lightning-30b-a3b"
        if self.GROQ_API_KEY:
            return self.GROQ_MODEL or "qwen/qwen3.8-27b"
        return "nvidia/nemotron-3.5-lightning-30b-a3b"
    # ---------------------------------

    # Face Recognition
    FACE_MATCH_THRESHOLD: float = 0.6
    FACE_MIN_SAMPLES: int = 3
    DISABLE_PGVECTOR: bool = True

    # Seed
    ADMIN_SEED_EMAIL: str = "kunaldixit.2995@gmail.com"
    ADMIN_SEED_TEMP_PASSWORD: str = ""

    # Google reCAPTCHA
    RECAPTCHA_SITE_KEY: str = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
    RECAPTCHA_SECRET_KEY: str = "6LeIxAcTAAAAAGG-vFI1TnFTxWGRtAUMuO_FnD4Q"
    ENABLE_RECAPTCHA: bool = False

    # ClamAV Antivirus
    ENABLE_CLAMAV: bool = False
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310

    # Environment
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Storage Settings ('s3' for Joy.services S3, or 'local' fallback)
    STORAGE_PROVIDER: str = "s3"
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # S3 Object Storage (joy.services / AWS S3 / MinIO)
    S3_ENDPOINT_URL: str = "https://nz.in.s3.joy.services"
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = "pathlab-reprts"
    S3_REGION_NAME: str = "default"
    S3_SIGNATURE_VERSION: str = "s3v4"
    S3_ADDRESSING_STYLE: str = "path"

    # WhatsApp Integration Service
    WHATSAPP_ENABLED: bool = True
    WHATSAPP_SERVICE_URL: str = "http://127.0.0.1:8005"
    WHATSAPP_SERVICE_PORT: int = 8005
    WHATSAPP_SERVICE_TOKEN: str = "pathlab_wa_sec_token_9f83a21b47c0e6"
    WHATSAPP_SESSION_PATH: str = "WHATSAPP/session"
    WHATSAPP_OTP_EXPIRY_SECONDS: int = 300
    WHATSAPP_OTP_RESEND_COOLDOWN_SECONDS: int = 60
    WHATSAPP_MAX_OTP_ATTEMPTS: int = 3
    WHATSAPP_MESSAGE_TIMEOUT_SECONDS: int = 15
    WHATSAPP_MAX_RETRIES: int = 3

    # CORS
    ALLOWED_ORIGINS: str = (
        "http://localhost:8000,"
        "http://127.0.0.1:8000,"
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "https://akritidc.onrender.com,"
        "https://akritidc.in,"
        "https://www.akritidc.in"
    )

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip().rstrip("/") for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

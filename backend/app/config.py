"""
Akriti Lab — Application Settings
Loads all configuration from environment variables / .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator
from typing import List
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

    # JWT
    PASSWORD_PEPPER: str = ""
    JWT_SECRET_KEY: str = "change-this-secret"
    JWT_ACCESS_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    JWT_REFRESH_EXPIRE_HOURS: int = 168
    JWT_ALGORITHM: str = "HS256"

    @model_validator(mode="after")
    def sync_jwt_refresh_hours(self):
        if self.JWT_REFRESH_EXPIRE_DAYS:
            self.JWT_REFRESH_EXPIRE_HOURS = self.JWT_REFRESH_EXPIRE_DAYS * 24
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
    LLM_MAX_TOKENS: int = 4096

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
    ADMIN_SEED_TEMP_PASSWORD: str = "Akriti@2024"

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

    # Storage Settings
    STORAGE_PROVIDER: str = "local" # 'local' or 'supabase'
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

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

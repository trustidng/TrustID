from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_name: str = os.getenv("DB_NAME", "trustid")
    session_secret: str = os.getenv("SESSION_SECRET", "")
    pseudonym_hmac_secret: str = os.getenv("PSEUDONYM_HMAC_SECRET", "")
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "12"))
    otp_ttl_minutes: int = int(os.getenv("OTP_TTL_MINUTES", "10"))
    auth_max_attempts: int = int(os.getenv("AUTH_MAX_ATTEMPTS", "5"))
    auth_lock_minutes: int = int(os.getenv("AUTH_LOCK_MINUTES", "15"))
    ussd_session_ttl_minutes: int = int(os.getenv("USSD_SESSION_TTL_MINUTES", "3"))
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    signing_key_id: str = os.getenv("TRUSTID_SIGNING_KEY_ID", "")
    signing_private_key_b64: str = os.getenv("TRUSTID_SIGNING_PRIVATE_KEY_B64", "")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    evidence_storage_path: str = os.getenv("EVIDENCE_STORAGE_PATH", "var/organisation-evidence")

    def validate(self) -> None:
        if len(self.session_secret) < 32 or self.session_secret.startswith("change-me"):
            raise RuntimeError("SESSION_SECRET must be a random value of at least 32 characters")
        if len(self.pseudonym_hmac_secret) < 32 or self.pseudonym_hmac_secret.startswith("change-me"):
            raise RuntimeError("PSEUDONYM_HMAC_SECRET must be a random value of at least 32 characters")
        if self.pseudonym_hmac_secret == self.session_secret:
            raise RuntimeError("PSEUDONYM_HMAC_SECRET and SESSION_SECRET must be different")
        if self.auth_max_attempts < 2 or self.session_ttl_hours < 1 or self.otp_ttl_minutes < 1 or self.ussd_session_ttl_minutes < 1:
            raise RuntimeError("Authentication timing/attempt settings are invalid")
        if not (self.public_base_url.startswith("https://") or self.public_base_url.startswith("http://127.0.0.1") or self.public_base_url.startswith("http://localhost")):
            raise RuntimeError("PUBLIC_BASE_URL must use HTTPS except for local development")


settings = Settings()

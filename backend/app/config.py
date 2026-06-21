from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    domain: str = "localhost"
    database_url: str = "sqlite+aiosqlite:///./data/dcintel.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str
    jwt_expiry_min: int = 1440
    bcrypt_rounds: int = 12
    cors_origins: str = ""
    trust_proxy: bool = False
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    model_dir: str = "/data/models"
    twitter_enabled: bool = True
    finnhub_api_key: str = ""  # US fallback quote provider; chain degrades gracefully if unset
    fred_api_key: str = ""  # free FRED key for calendar release dates; degrades gracefully if unset
    # M4 social-intel + sentiment sources — each self-disables when its creds are unset
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "web:dc-intel:v1.0 (by /u/dc_intel)"
    stocktwits_access_token: str = ""
    twitter_auth_token: str = ""
    twitter_ct0: str = ""
    twitter_cookies_file: str = ""
    newsapi_api_key: str = ""
    # M10 ops (deployment-architecture §2.3/§8.3): win-rate alerting + local backup + alert channel
    win_rate_alert_threshold: float = 0.50
    win_rate_warn_threshold: float = 0.52
    win_rate_min_sample: int = 30
    alert_webhook_url: str = ""  # unset in v1 → alerts go to alert_log_path + console only
    alert_log_path: str = "logs/alerts.log"
    backup_dir: str = "/data/backups"
    backup_bucket: str = ""  # unset in v1 → nightly snapshot stays in the local backup_dir

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @property
    def sqlite_path(self) -> str:
        """Filesystem path from a SQLAlchemy sqlite URL.

        'sqlite+aiosqlite:///./data/x.db' -> './data/x.db'   (3 slashes, relative)
        'sqlite+aiosqlite:////data/x.db'  -> '/data/x.db'     (4 slashes, absolute)
        """
        url = self.database_url
        for prefix in ("sqlite+aiosqlite://", "sqlite://"):
            if url.startswith(prefix):
                rest = url[len(prefix):]
                return rest[1:] if rest.startswith("/") else rest
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()

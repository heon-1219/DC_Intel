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

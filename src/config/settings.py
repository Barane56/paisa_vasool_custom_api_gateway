from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App ────────────────────────────────────────────────────────────────
    APP_NAME: str = "API Gateway"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production
    PORT: int = 8080

    # ── Services ───────────────────────────────────────────────────────────
    auth_service_url: str = "http://auth:8001"
    dispute_service_url: str = "http://dispute:8002"
    frontend_url: str = "http://localhost:3000"

    # ── Gateway Specific ───────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:80",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:80",
        "http://127.0.0.1:3000",
    ]

    EXCLUDED_HEADERS: list[str] = [
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    ]

    @property
    def services(self) -> dict[str, str]:
        if self.ENVIRONMENT == "production":
            return {
                "auth": self.auth_service_url,
                "dispute": self.dispute_service_url,
            }
        return {
            "auth": "http://auth:8001",
            "dispute": "http://dispute:8002",
        }

    @property
    def all_allowed_origins(self) -> list[str]:
        origins = self.ALLOWED_ORIGINS.copy()
        if self.ENVIRONMENT == "production" and self.frontend_url:
            origins.append(self.frontend_url)
        return origins

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

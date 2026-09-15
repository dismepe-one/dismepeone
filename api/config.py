from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "DISMEPE ONE 2.0 - Auth API"
    environment: str = "development"

    supabase_url: str = Field(
        default="https://zgegtjyxmlgnwyjqsohb.supabase.co",
        alias="DISMEPE_SUPABASE_URL",
    )
    supabase_publishable_key: str = Field(
        default="",
        alias="DISMEPE_SUPABASE_PUBLISHABLE_KEY",
    )
    edge_token: str = Field(
        default="",
        alias="DISMEPE_EDGE_TOKEN",
    )
    auth_pepper: str = Field(
        default="",
        alias="DISMEPE_AUTH_PEPPER",
    )

    jwt_secret: str = Field(
        default="",
        alias="DISMEPE_JWT_SECRET",
    )
    jwt_issuer: str = "dismepe-one-2"
    session_seconds: int = 10800

    cookie_name: str = "dismepe_v2_session"
    cookie_secure: bool = Field(default=True, alias="DISMEPE_COOKIE_SECURE")
    cookie_samesite: str = "lax"
    cookie_domain: str | None = None

    # Mantido como string simples para aceitar:
    # http://localhost:8080,https://homolog.dismepe.com.br
    cors_origins_raw: str = Field(
        default="http://localhost:8080",
        alias="DISMEPE_CORS_ORIGINS",
    )

    request_timeout_seconds: float = 8.0

    @property
    def cors_origins(self) -> list[str]:
        return [
            x.strip()
            for x in self.cors_origins_raw.split(",")
            if x.strip()
        ]

    def validate_required_secrets(self) -> list[str]:
        missing = []
        if not self.supabase_publishable_key:
            missing.append("DISMEPE_SUPABASE_PUBLISHABLE_KEY")
        if not self.edge_token:
            missing.append("DISMEPE_EDGE_TOKEN")
        if not self.auth_pepper:
            missing.append("DISMEPE_AUTH_PEPPER")
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            missing.append("DISMEPE_JWT_SECRET (mínimo 32 caracteres)")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()

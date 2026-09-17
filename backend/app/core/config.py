from functools import lru_cache
from urllib.parse import quote, unquote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _encode_password(url: str) -> str:
    """Percent-encode the password so special chars ([ ] @ : # / ?) can't break parsing."""
    scheme, _, rest = url.partition("://")
    userinfo, at, hostinfo = rest.rpartition("@")
    if not at or ":" not in userinfo:
        return url
    user, _, password = userinfo.partition(":")
    return f"{scheme}://{user}:{quote(unquote(password), safe='')}@{hostinfo}"


class Settings(BaseSettings):
    """All configuration comes from environment variables / .env.

    Secrets are never hardcoded. See .env.example for documentation.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rag-ultimate"
    environment: str = "local"

    # PostgreSQL (local parts) — ignored when DATABASE_URL is set (cloud).
    postgres_user: str = "rag"
    postgres_password: str = ""
    postgres_db: str = "rag"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    # Full URI override for managed Postgres (Supabase). Example:
    # postgresql://postgres.xxx:PASSWORD@host:5432/postgres?sslmode=require
    database_url_override: str = Field(default="", validation_alias="DATABASE_URL")

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "chunks"

    # Security
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_expire_minutes: int = 60 * 24
    jwt_algorithm: str = "HS256"

    # OpenRouter (LLM)
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Embeddings (FastEmbed, local)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    fastembed_cache_dir: str = "/app/models"

    # Retrieval
    top_k: int = 6
    score_threshold: float = 0.5

    # Uploads
    max_upload_size_mb: int = 25
    storage_dir: str = "/app/storage"
    allowed_extensions: str = "pdf,docx,xlsx,csv,txt"

    # CORS / frontend
    cors_origins: str = "http://localhost:5173"
    frontend_origin: str = "http://localhost:5173"

    # Auth cookie. Cross-site frontend (Vercel) + backend (Render) requires
    # COOKIE_SAMESITE=none (browsers then also require Secure).
    cookie_samesite: str = "lax"
    cookie_secure: bool | None = None

    # Google OAuth (optional)
    google_client_id: str = ""

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            url = self.database_url_override.replace("postgresql://", "postgresql+asyncpg://")
            url = url.replace("?sslmode=require", "").replace("&sslmode=require", "")
            return _encode_password(url)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def db_connect_args(self) -> dict:
        """SSL for managed DBs; no prepared statements on Supabase pooler (6543)."""
        args: dict = {}
        override = self.database_url_override
        if "sslmode=require" in override or "supabase" in override:
            args["ssl"] = "require"
        if ":6543" in override:
            args["statement_cache_size"] = 0
        return args

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extension_list(self) -> list[str]:
        return [e.strip().lower().lstrip(".") for e in self.allowed_extensions.split(",") if e.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

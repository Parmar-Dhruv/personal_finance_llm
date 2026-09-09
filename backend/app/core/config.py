from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Single source of truth for runtime configuration.
    Never hardcode secrets here — everything comes from the environment.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    secret_key: str = "change_me_to_a_random_64_char_string"

    database_url: str = "postgresql+psycopg://finsight:finsight_dev_password@localhost:5432/finsight"
    valkey_url: str = "redis://localhost:6379/0"

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    object_storage_bucket: str = "finsight-documents"
    object_storage_endpoint: str = "http://localhost:8333"
    object_storage_access_key: str = "finsight-dev-access-key"
    object_storage_secret_key: str = "finsight-dev-secret-key-change-me"
    object_storage_region: str = "us-east-1"

    max_upload_size_mb: int = 25
    allowed_upload_mime_types: str = (
        "application/pdf,text/csv,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "image/png,image/jpeg"
    )

    anthropic_api_key: str | None = None
    voyage_api_key: str | None = None

    backend_cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def allowed_upload_mime_type_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_upload_mime_types.split(",") if t.strip()]


settings = Settings()

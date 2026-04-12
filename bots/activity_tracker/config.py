from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    db_url: str = "postgresql+asyncpg://padel:padel@db/padel"
    admin_ids: list[int] = []
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list | int) -> list[int]:
        if isinstance(v, int):
            return [v]  # single ID, parsed as JSON number by pydantic-settings
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v  # type: ignore[return-value]


settings = Settings()

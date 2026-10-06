from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    bot_username: str = Field(default="", alias="BOT_USERNAME")
    root_admin_id: int = Field(alias="ROOT_ADMIN_ID")

    required_channel: str = Field(default="", alias="REQUIRED_CHANNEL")
    required_group: str = Field(default="", alias="REQUIRED_GROUP")
    investors_group_invite: str = Field(default="", alias="INVESTORS_GROUP_INVITE")

    postgres_user: str = Field(default="", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="", alias="POSTGRES_DB")
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    use_sqlite: bool = Field(default=False, alias="USE_SQLITE")
    sqlite_path: str = Field(default="deposit_bot.db", alias="SQLITE_PATH")

    redis_host: str = Field(default="", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")

    admin_secret: str = Field(default="dev_secret", alias="ADMIN_SECRET")
    admin_web_login: str = Field(default="", alias="ADMIN_WEB_LOGIN")
    admin_web_password: str = Field(default="changeme", alias="ADMIN_WEB_PASSWORD")

    default_lang: str = Field(default="ru", alias="DEFAULT_LANG")
    timezone: str = Field(default="Asia/Bishkek", alias="TIMEZONE")

    @property
    def database_url(self) -> str:
        if self.use_sqlite:
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.use_sqlite:
            return f"sqlite:///{self.sqlite_path}"
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str | None:
        if not self.redis_host:
            return None
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

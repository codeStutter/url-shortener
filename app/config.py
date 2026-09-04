from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    base_url: str = "http://localhost:8000"
    database_path: str = "./data/shortener.db"
    create_rate_limit: str = "20/minute"
    redirect_rate_limit: str = "200/minute"
    default_expiry_days: int = 0

    @property
    def database_url(self) -> str:
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"


settings = Settings()

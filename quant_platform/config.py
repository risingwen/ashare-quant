from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg:///quant_platform"
    tushare_replay_base_url: str = "https://ai-tool.indevs.in/tushare/pro"
    tushare_replay_api_key: str = ""
    sqlite_source: Path = Path("data/quant.db")
    public_origin: str = "http://140.245.53.52:8080"


settings = Settings()

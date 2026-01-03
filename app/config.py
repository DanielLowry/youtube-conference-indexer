from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    youtube_api_key: str = ""
    database_url: str = "sqlite:///./data/indexer.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

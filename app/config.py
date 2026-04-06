from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    youtube_api_key: str = ""
    youtube_api_keys_path: str = "data/api_keys.json"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

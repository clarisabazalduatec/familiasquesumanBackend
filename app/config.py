from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    database_url_sync: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    gemini_api_key: str
    media_dir: str = "media"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    s3_endpoint: str = "http://almacen:9000"
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "familias"
    imagen_max_bytes: int = 2 * 1024 * 1024


settings = Settings()

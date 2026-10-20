import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("uvicorn.error")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "dev" en local; "prod" en el servidor. En prod se apagan /docs y se exigen secretos fuertes.
    entorno: str = "dev"

    database_url: str
    database_url_sync: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 1 día

    gemini_api_key: str
    media_dir: str = "media"

    s3_endpoint: str = "http://almacen:9000"
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "familias"
    imagen_max_bytes: int = 2 * 1024 * 1024

    # Rate limiting. Si TODO el tráfico entra por un proxy de confianza (Cloudflare), pon aquí
    # la cabecera con la IP real (ej. "cf-connecting-ip"). Vacío = IP de la conexión
    # (con uvicorn --proxy-headers ya trae la de X-Forwarded-For del proxy).
    ip_header: str = ""
    rate_limit_default: str = "300/minute"

    # Bloqueo temporal de cuenta tras contraseñas incorrectas
    login_max_fallos: int = 5
    login_bloqueo_minutos: int = 15

    # Chatbot: exigir que los turnos "asistente" del historial vengan firmados por el backend
    chat_exigir_firma: bool = True

    @property
    def es_prod(self) -> bool:
        return self.entorno.lower() in ("prod", "produccion", "production")

    @model_validator(mode="after")
    def _secretos_fuertes(self):
        debiles = {"cambia-esto-por-una-clave-larga-y-aleatoria", "secret", "changeme", "test"}
        problema = len(self.jwt_secret_key) < 32 or self.jwt_secret_key in debiles
        if problema and self.es_prod:
            raise ValueError("JWT_SECRET_KEY debe tener al menos 32 caracteres aleatorios en producción")
        if problema:
            log.warning("JWT_SECRET_KEY es débil (menos de 32 caracteres). En producción la API no arrancaría.")
        if self.jwt_algorithm not in ("HS256", "HS384", "HS512"):
            raise ValueError("JWT_ALGORITHM debe ser HS256, HS384 o HS512")
        return self


settings = Settings()

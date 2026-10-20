"""Rate limiting con slowapi (en memoria: sirve porque la API corre en un solo proceso).

Si algún día corres varias réplicas o workers, cambia storage_uri a Redis
(ej. "redis://redis:6379") para que todas compartan los contadores.
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def ip_cliente(request: Request) -> str:
    # Solo se confía en la cabecera si está configurada: si el tráfico NO pasa siempre por ese
    # proxy, cualquiera podría mandarla falsa y saltarse el límite.
    if settings.ip_header:
        valor = request.headers.get(settings.ip_header)
        if valor:
            return valor.split(",")[0].strip()
    return get_remote_address(request)


def usuario_o_ip(request: Request) -> str:
    """Para endpoints con sesión: el límite es por usuario (los de una misma red Wi-Fi no se estorban)."""
    usuario_id = getattr(request.state, "usuario_id", None)
    return f"u:{usuario_id}" if usuario_id else f"ip:{ip_cliente(request)}"


limiter = Limiter(
    key_func=ip_cliente,
    default_limits=[settings.rate_limit_default],
    headers_enabled=False,
)

# Límites por endpoint (por minuto salvo que se diga). Un salón con el mismo Wi-Fi comparte IP,
# por eso login y registro no son tan bajos; la cuenta además se bloquea tras 5 fallos.
LOGIN = "10/minute"
REGISTRO = "10/minute"
CHAT = "10/minute"
SUBIDAS = "20/minute"
INVITACIONES = "10/minute"
CONTACTO = "5/hour"
CAMBIO_PASSWORD = "5/minute"

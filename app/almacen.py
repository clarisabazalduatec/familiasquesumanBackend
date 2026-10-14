"""Almacén de objetos S3 (RustFS hoy; R2/S3 mañana cambiando endpoint y llaves)."""
import asyncio
import re
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

CLAVE_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
EXTENSIONES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
TIPOS = {v: k for k, v in EXTENSIONES.items()}

_s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name="us-east-1",
    config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
)


def tipo_por_bytes(datos: bytes) -> str | None:
    """Detecta el tipo real por la firma del archivo."""
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return None


def _preparar() -> None:
    try:
        _s3.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        _s3.create_bucket(Bucket=settings.s3_bucket)  # privado por defecto


def _guardar(clave: str, datos: bytes, tipo: str) -> None:
    _s3.put_object(Bucket=settings.s3_bucket, Key=clave, Body=datos, ContentType=tipo)


def _abrir(clave: str):
    return _s3.get_object(Bucket=settings.s3_bucket, Key=clave)


def _existe(clave: str) -> bool:
    try:
        _s3.head_object(Bucket=settings.s3_bucket, Key=clave)
        return True
    except ClientError:
        return False


def _borrar(clave: str) -> None:
    _s3.delete_object(Bucket=settings.s3_bucket, Key=clave)


# Versiones async (boto3 es síncrono: se ejecuta en un hilo para no bloquear la API)
async def preparar() -> None:
    await asyncio.to_thread(_preparar)

async def guardar(datos: bytes, tipo: str) -> str:
    clave = f"{uuid.uuid4().hex}.{EXTENSIONES[tipo]}"
    await asyncio.to_thread(_guardar, clave, datos, tipo)
    return clave

async def abrir(clave: str):
    return await asyncio.to_thread(_abrir, clave)

async def existe(clave: str) -> bool:
    return await asyncio.to_thread(_existe, clave)

async def borrar(clave: str) -> None:
    await asyncio.to_thread(_borrar, clave)


def clave_de(valor: str | None) -> str | None:
    """Normaliza lo que manda la app a lo que se guarda en la BD:
    '/imagenes/abc.jpg' -> 'abc.jpg'; http(s) externo se deja igual."""
    if not valor:
        return None
    valor = valor.strip()
    return valor.removeprefix("/imagenes/") or None


def url_publica(valor: str | None) -> str | None:
    """Lo que devuelve la API: clave -> '/imagenes/{clave}'. http y rutas '/...' pasan igual."""
    if not valor:
        return None
    if valor.startswith(("http", "/")):
        return valor
    return f"/imagenes/{valor}"
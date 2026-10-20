"""Contraseñas (bcrypt), tokens (PyJWT) y dependencias de autenticación.

Cambios de seguridad:
- python-jose (sin mantenimiento, CVE-2024-33663/33664) -> PyJWT.
- passlib (abandonada) -> bcrypt directo. Los hashes existentes ($2b$...) siguen sirviendo.
- El token lleva iat, jti y "ver" (sesion_version del usuario): subir esa versión invalida
  todos los tokens anteriores (cerrar sesión en todos lados, cambio de contraseña).
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import RolUsuario, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
oauth2_scheme_opcional = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


# ---------- Contraseñas ----------
def hashear_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verificar_password(password_plano: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password_plano.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Hash corrupto o contraseña de más de 72 bytes: nunca coincide (y no truena con 500)
        return False


# Se usa cuando el correo no existe, para que el login tarde lo mismo exista o no la cuenta
# (sin esto, la diferencia de tiempo revela qué correos están registrados).
HASH_FALSO = hashear_password(uuid.uuid4().hex)


# ---------- Tokens ----------
def crear_access_token(usuario: "Usuario | uuid.UUID") -> str:
    """Recibe el usuario (lo normal) o solo su id (compatibilidad con código y pruebas viejas;
    en ese caso la versión es 0, la de una cuenta que nunca ha cerrado sesión en todos lados)."""
    if isinstance(usuario, Usuario):
        usuario_id, version = usuario.id, usuario.sesion_version or 0
    else:
        usuario_id, version = usuario, 0
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario_id),
        "ver": version,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=settings.jwt_expire_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def _usuario_del_token(token: str, db: AsyncSession) -> Usuario | None:
    """Regresa el usuario si el token es válido y vigente; None en cualquier otro caso."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],  # fijo: no se acepta "none" ni otro algoritmo
            options={"require": ["sub", "exp", "iat"]},
        )
        usuario_id = uuid.UUID(str(payload["sub"]))  # dentro del try: un sub raro es 401, no 500
    except (jwt.PyJWTError, ValueError, KeyError):
        return None

    usuario = await db.scalar(select(Usuario).where(Usuario.id == usuario_id))
    if usuario is None:
        return None
    # Token emitido antes de un "cerrar sesión en todos lados" o de un cambio de contraseña
    if payload.get("ver", 0) != (usuario.sesion_version or 0):
        return None
    return usuario


async def obtener_usuario_actual(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    usuario = await _usuario_del_token(token, db)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar la sesión",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.usuario_id = str(usuario.id)  # para la bitácora y el rate limit por usuario
    return usuario


async def obtener_usuario_opcional(
    request: Request,
    token: str | None = Depends(oauth2_scheme_opcional),
    db: AsyncSession = Depends(get_db),
) -> Usuario | None:
    if token is None:
        return None
    usuario = await _usuario_del_token(token, db)
    if usuario is not None:
        request.state.usuario_id = str(usuario.id)
    return usuario


async def requiere_admin(request: Request, usuario: Usuario = Depends(obtener_usuario_actual)) -> Usuario:
    """Úsala en endpoints de administración: Depends(requiere_admin)."""
    if usuario.rol != RolUsuario.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores")
    request.state.es_admin = True  # la bitácora de auditoría registra lo que haga este request
    return usuario

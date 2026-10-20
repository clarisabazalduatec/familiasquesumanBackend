"""Verificación del correo al crear una cuenta (modo "suave").

- Al registrarse se manda un código de 6 dígitos al correo. La cuenta funciona desde ya:
  puede entrar y ver todo, pero NO inscribirse, publicar ni comentar hasta verificar.
- El código vence en 10 minutos, permite 5 intentos y se puede pedir otro cada 60 s.
- En la base solo se guarda el hash del código (con sal), nunca el código.
- El correo sale con la misma función SMTP que Contacto y ayuda (app/routers/contacto.py).
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models import Usuario, VerificacionCorreo
from app.routers import contacto  # enviar_email (se usa vía el módulo para poder simularlo en pruebas)
from app.security import obtener_usuario_actual

log = logging.getLogger(__name__)

DURACION = timedelta(minutes=10)
ESPERA_REENVIO = timedelta(seconds=60)
MAX_INTENTOS = 5


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(codigo: str, sal: str) -> str:
    return hashlib.sha256(f"{sal}:{codigo}".encode()).hexdigest()


async def enviar_codigo(db: AsyncSession, usuario: Usuario, *, respetar_espera: bool = True) -> None:
    """Genera un código nuevo (reemplaza al anterior), lo guarda y lo manda por correo.
    Lanza 409 si ya está verificado, 429 si pidió otro hace menos de 60 s y 503 si falla el SMTP."""
    if usuario.correo_verificado:
        raise HTTPException(status_code=409, detail="Tu correo ya está verificado")

    ahora = _ahora()
    pendiente = await db.get(VerificacionCorreo, usuario.id)
    if respetar_espera and pendiente is not None and ahora - pendiente.enviado_en < ESPERA_REENVIO:
        faltan = int((ESPERA_REENVIO - (ahora - pendiente.enviado_en)).total_seconds()) + 1
        raise HTTPException(status_code=429, detail=f"Espera {faltan} segundos para pedir otro código")

    codigo = f"{secrets.randbelow(1_000_000):06d}"
    sal = secrets.token_hex(16)
    if pendiente is None:
        pendiente = VerificacionCorreo(usuario_id=usuario.id)
        db.add(pendiente)
    pendiente.codigo_hash = _hash(codigo, sal)
    pendiente.sal = sal
    pendiente.enviado_en = ahora
    pendiente.expira_en = ahora + DURACION
    pendiente.intentos = 0
    await db.commit()

    try:
        await run_in_threadpool(
            contacto.enviar_email,
            usuario.email,
            "Verifica tu correo - Familias que Suman",
            (
                f"Hola {usuario.nombre.split(' ')[0]},\n\n"
                "Gracias por crear tu cuenta en Familias que Suman.\n\n"
                f"Tu código de verificación es: {codigo}\n\n"
                "Escríbelo en la app para verificar tu correo. Vence en 10 minutos.\n\n"
                "Si no creaste esta cuenta, ignora este correo.\n\n"
                "Familias que Suman"
            ),
        )
    except Exception as e:
        log.exception("No se pudo enviar el código de verificación a %s", usuario.email)
        raise HTTPException(status_code=503, detail="No se pudo enviar el código. Intenta de nuevo.") from e


async def confirmar_codigo(db: AsyncSession, usuario: Usuario, codigo: str) -> None:
    """Marca el correo como verificado si el código es correcto. 400 si es incorrecto o venció."""
    if usuario.correo_verificado:
        return  # ya estaba: no es error (p. ej. tocó dos veces "Verificar")

    pendiente = await db.get(VerificacionCorreo, usuario.id)
    if pendiente is None or _ahora() >= pendiente.expira_en:
        raise HTTPException(status_code=400, detail="El código venció. Pide uno nuevo.")
    if pendiente.intentos >= MAX_INTENTOS:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Pide un código nuevo.")

    pendiente.intentos += 1
    if not hmac.compare_digest(_hash(codigo, pendiente.sal), pendiente.codigo_hash):
        await db.commit()  # el intento cuenta
        restantes = MAX_INTENTOS - pendiente.intentos
        detalle = "Código incorrecto." + (f" Te quedan {restantes} intentos." if restantes else " Pide un código nuevo.")
        raise HTTPException(status_code=400, detail=detalle)

    usuario.correo_verificado = True
    await db.delete(pendiente)
    await db.commit()


async def requiere_correo_verificado(usuario: Usuario = Depends(obtener_usuario_actual)) -> Usuario:
    """Para lo que SÍ pide correo verificado: inscribirse, publicar y comentar."""
    if not usuario.correo_verificado:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verifica tu correo para poder hacer esto. Puedes hacerlo desde tu Perfil.",
        )
    return usuario

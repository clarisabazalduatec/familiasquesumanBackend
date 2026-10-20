
import os
import smtplib
import ssl
import secrets
import hashlib
import hmac
import logging
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from starlette.concurrency import run_in_threadpool

from app.limites import CONTACTO, limiter

router = APIRouter(prefix="/contacto", tags=["Contacto"])
logger = logging.getLogger(__name__)

CODIGO_DURACION = timedelta(minutes=10)
REENVIO_ESPERA = timedelta(seconds=60)
MAX_INTENTOS = 5
MAX_SOLICITUDES_HORA = 3

verificaciones = {}
solicitudes = {}
bloqueo = threading.Lock()


class MensajeContacto(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    correo: EmailStr
    mensaje: str = Field(min_length=1, max_length=5000)

class ConfirmarCodigo(BaseModel):
    correo: EmailStr
    codigo: str = Field(pattern=r"^[0-9]{6}$")

def fecha_actual():
    return datetime.now(timezone.utc)

def hash_codigo(codigo: str, sal: str) -> str:
    return hashlib.sha256(
        f"{sal}:{codigo}".encode("utf-8")
    ).hexdigest()

def enviar_email(destinatario: str, asunto: str, contenido: str, reply_to=None):
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    email = EmailMessage()
    email["Subject"] = asunto
    email["From"] = smtp_user
    email["To"] = destinatario

    if reply_to:
        email["Reply-To"] = reply_to
    email.set_content(contenido)
    contexto = ssl.create_default_context()
    with smtplib.SMTP(
        os.getenv("SMTP_HOST", "smtp.gmail.com"),
        int(os.getenv("SMTP_PORT", "587")),
        timeout=15,
    ) as servidor:
        servidor.starttls(context=contexto)
        servidor.login(smtp_user, smtp_password)
        servidor.send_message(email)

def enviar_codigo(correo: str, codigo: str):
    enviar_email(
        destinatario=correo,
        asunto="Código de verificación - Familias que Suman",
        contenido=(
            "Hola,\n\n"
            "Recibimos una solicitud para enviar un mensaje "
            "desde Contacto y Ayuda.\n\n"
            f"Tu código de verificación es: {codigo}\n\n"
            "Este código vence en 10 minutos.\n\n"
            "Si no solicitaste este código, ignora este correo.\n\n"
            "Familias que Suman"
        )
    )


def enviar_correo(datos: MensajeContacto):
    enviar_email(
        destinatario=os.environ["CONTACTO_DESTINATARIO"],
        asunto="Nuevo mensaje - Familias que Suman",
        contenido=(
            f"Nombre: {datos.nombre}\n"
            f"Correo: {datos.correo}\n\n"
            f"Mensaje:\n{datos.mensaje}"
        ),
        reply_to=str(datos.correo)
    )


def _purgar(ahora) -> None:
    """Los diccionarios viven en memoria: sin esto crecen para siempre (un correo nuevo por intento)."""
    for c in [c for c, v in verificaciones.items() if ahora >= v["expira"]]:
        verificaciones.pop(c, None)
    for c in [c for c, fechas in solicitudes.items() if all(ahora - f >= timedelta(hours=1) for f in fechas)]:
        solicitudes.pop(c, None)


@router.post("/solicitar-codigo")
@limiter.limit(CONTACTO)  # por IP: antes solo había límite por correo, y rotando correos se abusaba del SMTP
async def solicitar_codigo(request: Request, datos: MensajeContacto):
    correo = str(datos.correo).strip().lower()
    ahora = fecha_actual()
    with bloqueo:
        _purgar(ahora)
        historial = [
            fecha for fecha in solicitudes.get(correo, [])
            if ahora - fecha < timedelta(hours=1)
        ]
        if len(historial) >= MAX_SOLICITUDES_HORA:
            raise HTTPException(
                status_code=429,
                detail="Has solicitado demasiados códigos. Intenta más tarde."
            )
        anterior = verificaciones.get(correo)
        if anterior and ahora - anterior["creado"] < REENVIO_ESPERA:
            raise HTTPException(
                status_code=429,
                detail="Espera 60 segundos antes de solicitar otro código."
            )
        codigo = f"{secrets.randbelow(1000000):06d}"
        sal = secrets.token_hex(16)
        verificaciones[correo] = {
            "codigo_hash": hash_codigo(codigo, sal),
            "sal": sal,
            "datos": datos,
            "creado": ahora,
            "expira": ahora + CODIGO_DURACION,
            "intentos": 0,
            "enviando": False,
        }
        solicitudes[correo] = historial + [ahora]
    try:
        await run_in_threadpool(enviar_codigo, correo, codigo)
    except Exception as e:
        logger.exception("Error al enviar código de verificación")
        with bloqueo:
            actual = verificaciones.get(correo)
            if actual and actual["sal"] == sal:
                verificaciones.pop(correo, None)
        raise HTTPException(
            status_code=503,
            detail="No se pudo enviar el código. Intenta nuevamente."
        ) from e
    return {
        "mensaje": "Si el correo puede recibir mensajes, llegará un código de verificación.",
        "expira_en_minutos": 10
    }


@router.post("/confirmar-codigo")
@limiter.limit("20/hour")
async def confirmar_codigo(request: Request, datos: ConfirmarCodigo):
    correo = str(datos.correo).strip().lower()
    ahora = fecha_actual()
    with bloqueo:
        verificacion = verificaciones.get(correo)
        if verificacion is None or ahora >= verificacion["expira"]:
            verificaciones.pop(correo, None)
            raise HTTPException(
                status_code=400,
                detail="Código inválido o vencido. Solicita uno nuevo."
            )
        if verificacion["enviando"]:
            raise HTTPException(
                status_code=409,
                detail="El mensaje ya se está procesando."
            )
        if verificacion["intentos"] >= MAX_INTENTOS:
            verificaciones.pop(correo, None)
            raise HTTPException(
                status_code=429,
                detail="Demasiados intentos. Solicita otro código."
            )
        verificacion["intentos"] += 1
        codigo_recibido = hash_codigo(
            datos.codigo,
            verificacion["sal"]
        )
        if not hmac.compare_digest(
            codigo_recibido,
            verificacion["codigo_hash"]
        ):
            if verificacion["intentos"] >= MAX_INTENTOS:
                verificaciones.pop(correo, None)
            raise HTTPException(
                status_code=400,
                detail="Código incorrecto o vencido."
            )
        verificacion["enviando"] = True
        mensaje = verificacion["datos"]

    try:
        await run_in_threadpool(enviar_correo, mensaje)
    except Exception as e:
        logger.exception("Error al enviar mensaje de contacto")
        with bloqueo:
            actual = verificaciones.get(correo)
            if actual is verificacion:
                actual["enviando"] = False

        raise HTTPException(
            status_code=503,
            detail="No se pudo enviar el mensaje. Intenta nuevamente."
        ) from e

    with bloqueo:
        if verificaciones.get(correo) is verificacion:
            verificaciones.pop(correo, None)
    return {"mensaje": "Correo verificado y mensaje enviado correctamente"}


@router.post("", include_in_schema=False)
async def enviar_mensaje_anterior(datos: MensajeContacto):
    raise HTTPException(
        status_code=410,
        detail="Ahora es obligatorio verificar el correo antes de enviar el mensaje."
    )

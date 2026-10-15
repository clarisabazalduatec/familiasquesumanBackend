import asyncio
import logging
from time import perf_counter

import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import asistente_herramientas as herramientas
from app.asistente_prompt import instrucciones_sistema
from app.config import settings
from app.database import get_db
from app.metrics import CHATBOT_REQUEST_DURATION, CHATBOT_REQUESTS
from app.models import Usuario
from app.schemas import ChatMensajeEntrada, ChatMensajeRespuesta
from app.security import obtener_usuario_opcional

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger("uvicorn.error")  # el logger que uvicorn sí imprime en docker logs

genai.configure(api_key=settings.gemini_api_key)

MODELO = "gemini-3.1-flash-lite"
MAX_MENSAJE = 1000      # caracteres que acepta del usuario
MAX_HISTORIAL = 10      # mensajes previos (de la pantalla) que se mandan como contexto
MAX_RONDAS = 4          # máximo de idas y vueltas con herramientas por mensaje
TIEMPO_GEMINI = 20      # segundos máximos por llamada a Gemini
TIEMPO_TOTAL = 45       # segundos máximos por mensaje (la app espera 60)
RESPUESTA_FALLA = (
    "Perdón, tuve un problema para responderte en este momento. "
    "Intenta de nuevo en un ratito o revisa directamente la sección de la app."
)


def _llamadas(respuesta) -> list:
    """Las function_call que pidió el modelo en esta respuesta (puede pedir varias)."""
    try:
        partes = respuesta.candidates[0].content.parts
    except (IndexError, AttributeError):
        return []
    return [p.function_call for p in partes if p.function_call]


def _texto(respuesta) -> str:
    try:
        return (respuesta.text or "").strip()
    except Exception:  # respuesta bloqueada o sin texto
        return ""


async def _gemini(chat, contenido):
    return await asyncio.wait_for(chat.send_message_async(contenido), timeout=TIEMPO_GEMINI)


async def responder(chat, mensaje: str, db: AsyncSession, usuario: Usuario | None) -> str:
    """Bucle de function calling: el modelo pide herramientas, el backend las ejecuta
    y le regresa los resultados, hasta que el modelo contesta con texto."""
    t0 = perf_counter()
    respuesta = await _gemini(chat, mensaje)
    log.info("chatbot gemini ronda=0 %.1fs", perf_counter() - t0)
    for ronda in range(1, MAX_RONDAS + 1):
        llamadas = _llamadas(respuesta)
        if not llamadas:
            break
        partes = []
        for llamada in llamadas:
            args = {k: v for k, v in (llamada.args or {}).items()}
            log.info("chatbot herramienta=%s args=%s", llamada.name, args)
            try:
                resultado = await herramientas.ejecutar(llamada.name, args, db, usuario)
            except Exception:
                log.exception("Falló la herramienta %s", llamada.name)
                resultado = {"error": "No se pudo consultar esta información en este momento."}
            partes.append(genai.protos.Part(
                function_response=genai.protos.FunctionResponse(name=llamada.name, response=resultado)
            ))
        t = perf_counter()
        respuesta = await _gemini(chat, partes)
        log.info("chatbot gemini ronda=%d %.1fs", ronda, perf_counter() - t)
    log.info("chatbot total %.1fs", perf_counter() - t0)
    return _texto(respuesta)


@router.post("", response_model=ChatMensajeRespuesta)
async def enviar_mensaje(
    entrada: ChatMensajeEntrada,
    usuario: Usuario | None = Depends(obtener_usuario_opcional),
    db: AsyncSession = Depends(get_db),
):
    mensaje = entrada.mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=422, detail="Escribe un mensaje")
    if len(mensaje) > MAX_MENSAJE:
        raise HTTPException(status_code=422, detail=f"El mensaje es muy largo (máximo {MAX_MENSAJE} caracteres)")

    # Sin memoria guardada: el contexto es solo la conversación que la app tiene en pantalla.
    # Al salir del chat la app la borra, y el backend no guarda nada.
    historial_gemini = [
        {"role": "user" if t.rol == "usuario" else "model", "parts": [t.contenido]}
        for t in entrada.historial[-MAX_HISTORIAL:]
        if t.contenido.strip()
    ]

    # El modelo se crea por mensaje: las instrucciones llevan la fecha y si hay sesión.
    modelo = genai.GenerativeModel(
        model_name=MODELO,
        system_instruction=instrucciones_sistema(usuario),
        tools=[herramientas.DECLARACIONES],
        generation_config={"temperature": 0.4, "max_output_tokens": 700},
    )
    chat = modelo.start_chat(history=historial_gemini)

    inicio = perf_counter()
    try:
        texto_respuesta = await asyncio.wait_for(responder(chat, mensaje, db, usuario), timeout=TIEMPO_TOTAL)
        CHATBOT_REQUESTS.labels("success").inc()
    except Exception:
        log.exception("Falló la llamada a Gemini")
        CHATBOT_REQUESTS.labels("failure").inc()
        texto_respuesta = ""
    finally:
        CHATBOT_REQUEST_DURATION.observe(perf_counter() - inicio)

    return ChatMensajeRespuesta(respuesta=texto_respuesta or RESPUESTA_FALLA)
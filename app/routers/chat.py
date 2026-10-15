import asyncio
import logging
import os
import warnings
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app import asistente_herramientas as herramientas
from app.asistente_prompt import instrucciones_sistema
from app.config import settings
from app.database import get_db
from app.metrics import CHATBOT_REQUEST_DURATION, CHATBOT_REQUESTS
from app.models import Usuario
from app.schemas import ChatEnlace, ChatMensajeEntrada, ChatMensajeRespuesta
from app.security import obtener_usuario_opcional

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger("uvicorn.error")  # el logger que uvicorn sí imprime en docker logs

# Avisos internos de google-genai con nuestra versión de pydantic: no afectan, solo ensucian el log.
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

# Se puede cambiar sin tocar código: GEMINI_MODEL=... en el .env
MODELO = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
MAX_MENSAJE = 1000      # caracteres que acepta del usuario
MAX_HISTORIAL = 10      # mensajes previos (de la pantalla) que se mandan como contexto
MAX_RONDAS = 4          # máximo de idas y vueltas con herramientas por mensaje
MAX_ENLACES = 3         # botones bajo la respuesta
TIEMPO_GEMINI = 20      # segundos máximos por llamada a Gemini
TIEMPO_TOTAL = 45       # segundos máximos por mensaje (la app espera 60)
RESPUESTA_FALLA = (
    "No fue posible obtener una respuesta en este momento. Intenta de nuevo en unos minutos "
    "o consulta directamente la sección correspondiente de la app."
)

# Librería nueva (google-genai): conserva sola las "thought signatures" que los modelos
# Gemini 3 exigen al usar herramientas. Si Gemini está saturado (503/429) reintenta 2 veces rápido.
cliente = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=types.HttpOptions(
        timeout=TIEMPO_GEMINI * 1000,  # en milisegundos
        retry_options=types.HttpRetryOptions(
            attempts=3, initial_delay=0.5, max_delay=2.0, http_status_codes=[429, 503],
        ),
    ),
)


def _texto(respuesta) -> str:
    try:
        return (respuesta.text or "").strip()
    except Exception:  # respuesta bloqueada o sin texto
        return ""


async def _gemini(chat, contenido):
    return await asyncio.wait_for(chat.send_message(contenido), timeout=TIEMPO_GEMINI + 2)


def _enlaces_mencionados(texto: str, candidatos: list[dict]) -> list[ChatEnlace]:
    """De todo lo que regresaron las herramientas, solo lo que la respuesta sí menciona."""
    texto_n = herramientas._normalizar(texto)
    vistos, encontrados = set(), []
    for e in candidatos:
        clave = (e["tipo"], e["id"])
        posicion = texto_n.find(herramientas._normalizar(e["titulo"]))
        if clave in vistos or posicion < 0:
            continue
        vistos.add(clave)
        encontrados.append((posicion, ChatEnlace(**e)))
    encontrados.sort(key=lambda x: x[0])  # en el orden en que aparecen en la respuesta
    return [e for _, e in encontrados[:MAX_ENLACES]]


async def responder(chat, mensaje: str, db: AsyncSession, usuario: Usuario | None) -> tuple[str, list[ChatEnlace]]:
    """Bucle de function calling: el modelo pide herramientas, el backend las ejecuta
    y le regresa los resultados, hasta que el modelo contesta con texto."""
    candidatos: list[dict] = []
    t0 = perf_counter()
    respuesta = await _gemini(chat, mensaje)
    log.info("chatbot gemini ronda=0 %.1fs", perf_counter() - t0)
    for ronda in range(1, MAX_RONDAS + 1):
        llamadas = respuesta.function_calls or []
        if not llamadas:
            break
        partes = []
        for llamada in llamadas:
            args = dict(llamada.args or {})
            log.info("chatbot herramienta=%s args=%s", llamada.name, args)
            try:
                resultado = await herramientas.ejecutar(llamada.name, args, db, usuario)
            except Exception:
                log.exception("Falló la herramienta %s", llamada.name)
                resultado = {"error": "No se pudo consultar esta información en este momento."}
            candidatos += resultado.pop("_enlaces", [])  # los ids no se mandan al modelo
            partes.append(types.Part.from_function_response(name=llamada.name, response=resultado))
        t = perf_counter()
        respuesta = await _gemini(chat, partes)
        log.info("chatbot gemini ronda=%d %.1fs", ronda, perf_counter() - t)
    log.info("chatbot total %.1fs", perf_counter() - t0)
    texto = _texto(respuesta)
    return texto, _enlaces_mencionados(texto, candidatos)


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
    historial = [
        types.Content(
            role="user" if t.rol == "usuario" else "model",
            parts=[types.Part.from_text(text=t.contenido)],
        )
        for t in entrada.historial[-MAX_HISTORIAL:]
        if t.contenido.strip()
    ]

    # La configuración se arma por mensaje: las instrucciones llevan la fecha y si hay sesión.
    configuracion = types.GenerateContentConfig(
        system_instruction=instrucciones_sistema(usuario),
        tools=[herramientas.DECLARACIONES],
        # Las herramientas las ejecutamos nosotros (con la sesión de BD y el usuario del token).
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.4,
        max_output_tokens=2048,  # los modelos que "piensan" gastan parte de esto en pensar
    )
    chat = cliente.aio.chats.create(model=MODELO, config=configuracion, history=historial)

    inicio = perf_counter()
    try:
        texto_respuesta, enlaces = await asyncio.wait_for(
            responder(chat, mensaje, db, usuario), timeout=TIEMPO_TOTAL
        )
        CHATBOT_REQUESTS.labels("success").inc()
    except Exception:
        log.exception("Falló la llamada a Gemini")
        CHATBOT_REQUESTS.labels("failure").inc()
        texto_respuesta, enlaces = "", []
    finally:
        CHATBOT_REQUEST_DURATION.observe(perf_counter() - inicio)

    if not texto_respuesta:
        return ChatMensajeRespuesta(respuesta=RESPUESTA_FALLA)
    return ChatMensajeRespuesta(respuesta=texto_respuesta, enlaces=enlaces)
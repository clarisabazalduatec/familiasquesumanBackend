import google.generativeai as genai
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import MensajeChat, Usuario
from app.schemas import ChatMensajeEntrada, ChatMensajeRespuesta
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/chat", tags=["chat"])

genai.configure(api_key=settings.gemini_api_key)

INSTRUCCIONES_SISTEMA = (
    "Eres el Asistente Comunitario de la app Familias que Suman. Ayudas a las familias "
    "a encontrar actividades de voluntariado, proyectos para donar y a resolver dudas "
    "sobre el uso de la app. Responde en español, de forma breve, cálida y concreta."
)

modelo_gemini = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=INSTRUCCIONES_SISTEMA,
)


@router.post("", response_model=ChatMensajeRespuesta)
async def enviar_mensaje(
    entrada: ChatMensajeEntrada,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    # Recupera el historial reciente para dar contexto a la conversación
    resultado = await db.execute(
        select(MensajeChat)
        .where(MensajeChat.usuario_id == usuario.id)
        .order_by(MensajeChat.creado_en.desc())
        .limit(10)
    )
    historial = list(reversed(resultado.scalars().all()))

    # Gemini usa "user" y "model" como roles (no "assistant")
    historial_gemini = [
        {"role": "user" if m.rol == "usuario" else "model", "parts": [m.contenido]}
        for m in historial
    ]

    chat = modelo_gemini.start_chat(history=historial_gemini)
    respuesta_gemini = chat.send_message(entrada.mensaje)
    texto_respuesta = respuesta_gemini.text

    db.add(MensajeChat(usuario_id=usuario.id, rol="usuario", contenido=entrada.mensaje))
    db.add(MensajeChat(usuario_id=usuario.id, rol="asistente", contenido=texto_respuesta))
    await db.commit()

    return ChatMensajeRespuesta(respuesta=texto_respuesta)

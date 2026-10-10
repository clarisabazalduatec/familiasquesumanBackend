import google.generativeai as genai
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.security import obtener_usuario_opcional
from app.config import settings
from app.database import get_db
from app.models import MensajeChat, Usuario
from app.schemas import ChatMensajeEntrada, ChatMensajeRespuesta
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/chat", tags=["chat"])

genai.configure(api_key=settings.gemini_api_key)

INSTRUCCIONES_SISTEMA = """
Eres el Asistente Comunitario de la app Familias que Suman, una plataforma que conecta
familias con oportunidades de voluntariado y donación en Monterrey, NL.

La app tiene estas secciones:
- Actividades en Familia: eventos de voluntariado con cupo limitado, se pueden inscribir o entrar a lista de espera.
- Quiero Donar: donaciones en especie (ropa, alimentos, juguetes) o dinero a campañas activas.
- Proyectos: causas con metas específicas y seguimiento de avance.
- Directorio de Visiteo: asilos, casas hogar y comedores que se pueden visitar en persona.

Tu tono es cálido, cercano y breve — como alguien de la comunidad, no un bot corporativo.
Respondes siempre en español.

Si te preguntan algo fuera de estos temas (tarea de la escuela, clima, temas no
relacionados a la app), redirige amablemente hacia cómo puedes ayudar dentro de la app. No hablaras nunca de nada que no tenga que ver con
la aplicacion. 


No inventes datos específicos (cupos exactos, fechas, montos) que no te hayan dado — si
no tienes esa información, sugiere revisar la sección correspondiente en la app.
"""

modelo_gemini = genai.GenerativeModel(
    model_name="gemini-3.1-flash-lite",
    system_instruction=INSTRUCCIONES_SISTEMA,
)


@router.post("", response_model=ChatMensajeRespuesta)
async def enviar_mensaje(
    entrada: ChatMensajeEntrada,
    usuario: Usuario | None = Depends(obtener_usuario_opcional),
    db: AsyncSession = Depends(get_db),
):
    historial_gemini = []
    if usuario is not None:
        resultado = await db.execute(
            select(MensajeChat)
            .where(MensajeChat.usuario_id == usuario.id)
            .order_by(MensajeChat.creado_en.desc())
            .limit(10)
        )
        historial = list(reversed(resultado.scalars().all()))
        historial_gemini = [
            {"role": "user" if m.rol == "usuario" else "model", "parts": [m.contenido]}
            for m in historial
        ]

    chat = modelo_gemini.start_chat(history=historial_gemini)
    respuesta_gemini = chat.send_message(entrada.mensaje)
    texto_respuesta = respuesta_gemini.text

    if usuario is not None:
        db.add(MensajeChat(usuario_id=usuario.id, rol="usuario", contenido=entrada.mensaje))
        db.add(MensajeChat(usuario_id=usuario.id, rol="asistente", contenido=texto_respuesta))
        await db.commit()

    return ChatMensajeRespuesta(respuesta=texto_respuesta)

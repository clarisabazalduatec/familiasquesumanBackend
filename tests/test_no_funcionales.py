"""Requerimientos NO funcionales que se pueden comprobar en el backend (una prueba por RNF)."""
import asyncio
from time import perf_counter
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Usuario
from app.routers import chat


# RNF-01 Tiempo de respuesta del chatbot: aunque la IA tarde de más, el servidor corta a tiempo
# y contesta un mensaje amable (la app nunca se queda esperando sin respuesta).
async def test_rnf01_chatbot_responde_dentro_del_tiempo_limite(cliente, monkeypatch):
    async def gemini_lento(_contenido):
        await asyncio.sleep(5)  # una IA "colgada"
    sesion = SimpleNamespace(send_message=gemini_lento)
    monkeypatch.setattr(chat, "cliente", SimpleNamespace(aio=SimpleNamespace(chats=SimpleNamespace(create=lambda **kw: sesion))))
    monkeypatch.setattr(chat, "TIEMPO_TOTAL", 1)  # en producción son 45 s; aquí 1 s para no esperar

    inicio = perf_counter()
    r = await cliente.post("/chat", json={"mensaje": "¿Qué actividades hay?"})
    duracion = perf_counter() - inicio

    assert r.status_code == 200
    assert r.json()["respuesta"] == chat.RESPUESTA_FALLA
    assert duracion < 3  # cortó en ~1 s, no esperó los 5 s de la IA


# RNF-04 Navegación sin sesión: el contenido público se consulta sin iniciar sesión
async def test_rnf04_contenido_publico_sin_sesion(cliente):
    for ruta in ("/actividades", "/proyectos", "/donaciones", "/centros", "/comunidad", "/comunidad/avisos", "/ciudades"):
        r = await cliente.get(ruta)
        assert r.status_code == 200, ruta
    # y lo personal sí pide sesión
    assert (await cliente.get("/usuarios/me")).status_code == 401


# RNF-05 Seguridad de contraseñas: reglas mínimas, guardado cifrado (bcrypt) y bloqueo tras 5 fallos
async def test_rnf05_seguridad_de_contrasenas(cliente, db):
    debil = await cliente.post("/auth/registro", json={"nombre": "Ana", "email": "ana@ejemplo.mx", "password": "12345678"})
    assert debil.status_code == 422  # solo números

    await cliente.post("/auth/registro", json={"nombre": "Ana", "email": "ana@ejemplo.mx", "password": "Segura2026"})
    guardada = await db.scalar(select(Usuario.password_hash).where(Usuario.email == "ana@ejemplo.mx"))
    assert guardada != "Segura2026" and guardada.startswith("$2")  # hash bcrypt, nunca texto plano

    for _ in range(5):
        assert (await cliente.post("/auth/login", json={"email": "ana@ejemplo.mx", "password": "Mala1234"})).status_code == 401
    bloqueada = await cliente.post("/auth/login", json={"email": "ana@ejemplo.mx", "password": "Segura2026"})
    assert bloqueada.status_code == 429  # ni con la contraseña correcta: cuenta bloqueada


# RNF-09 Disponibilidad de información: la API y su base de datos responden (lo que revisa el healthcheck)
async def test_rnf09_api_y_base_de_datos_disponibles(cliente):
    assert (await cliente.get("/health")).json() == {"status": "ok"}
    assert (await cliente.get("/health/db")).json() == {"status": "ok"}

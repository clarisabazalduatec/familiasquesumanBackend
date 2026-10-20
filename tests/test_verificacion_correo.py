"""Verificación del correo al crear cuenta (modo suave): la cuenta funciona desde el registro,
pero inscribirse, publicar y comentar piden el correo verificado con un código de 6 dígitos."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import AmbitoCategoria, VerificacionCorreo
from app.routers import contacto
from tests.fabricas import categoria, crear_actividad, crear_familia

DATOS = {"nombre": "Mariana López", "email": "mariana@ejemplo.mx", "password": "secreta123"}


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(contacto, "enviar_email",
                        lambda destinatario, asunto, contenido, reply_to=None: enviados.append((destinatario, contenido)))
    return enviados


def _codigo(correo) -> str:
    return re.search(r"\b(\d{6})\b", correo[1]).group(1)


async def _registrar(cliente) -> dict:
    r = await cliente.post("/auth/registro", json=DATOS)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_al_registrarse_llega_un_codigo_y_la_cuenta_queda_sin_verificar(cliente, correos, db):
    r = await cliente.post("/auth/registro", json=DATOS)

    assert r.json()["usuario"]["correo_verificado"] is False
    assert correos[0][0] == "mariana@ejemplo.mx"
    # En la base solo queda el hash, nunca el código
    pendiente = await db.scalar(select(VerificacionCorreo))
    assert _codigo(correos[0]) not in pendiente.codigo_hash


async def test_sin_verificar_puede_entrar_pero_no_inscribirse_publicar_ni_comentar(cliente, correos, db):
    h = await _registrar(cliente)
    actividad = await crear_actividad(db)
    cat = await categoria(db, AmbitoCategoria.PUBLICACION, "Voluntariado")
    await db.commit()

    assert (await cliente.get("/usuarios/me", headers=h)).status_code == 200      # entra y ve su perfil
    assert (await cliente.get("/actividades")).status_code == 200                  # ve todo
    yo = (await cliente.get("/usuarios/me", headers=h)).json()
    await cliente.post("/familias", json={"nombre": "Familia López"}, headers=h)   # puede armar su familia
    inscribir = await cliente.post(f"/actividades/{actividad.id}/inscripcion", json={"usuario_ids": [yo["id"]]}, headers=h)
    publicar = await cliente.post("/comunidad", json={"titulo": "T", "contenido": "C", "categoria_id": cat.id}, headers=h)

    assert inscribir.status_code == 403 and "Verifica tu correo" in inscribir.json()["detail"]
    assert publicar.status_code == 403


async def test_con_el_codigo_correcto_queda_verificada_y_ya_puede_inscribirse(cliente, correos, db):
    h = await _registrar(cliente)
    actividad = await crear_actividad(db)

    r = await cliente.post("/auth/verificacion/confirmar", json={"codigo": _codigo(correos[0])}, headers=h)

    assert r.status_code == 200 and r.json()["correo_verificado"] is True
    assert (await cliente.get("/usuarios/me", headers=h)).json()["correo_verificado"] is True
    assert await db.scalar(select(VerificacionCorreo)) is None  # el código se borra
    yo = (await cliente.get("/usuarios/me", headers=h)).json()
    await cliente.post("/familias", json={"nombre": "Familia López"}, headers=h)
    r = await cliente.post(f"/actividades/{actividad.id}/inscripcion", json={"usuario_ids": [yo["id"]]}, headers=h)
    assert r.status_code == 201


async def test_codigo_incorrecto_cuenta_intentos_y_se_bloquea_a_los_5(cliente, correos):
    h = await _registrar(cliente)
    bueno = _codigo(correos[0])
    malo = "000000" if bueno != "000000" else "111111"

    r = await cliente.post("/auth/verificacion/confirmar", json={"codigo": malo}, headers=h)
    assert r.status_code == 400 and "Te quedan 4 intentos" in r.json()["detail"]
    for _ in range(4):
        await cliente.post("/auth/verificacion/confirmar", json={"codigo": malo}, headers=h)

    r = await cliente.post("/auth/verificacion/confirmar", json={"codigo": bueno}, headers=h)
    assert r.status_code == 429


async def test_reenviar_espera_60_segundos_y_el_codigo_viejo_deja_de_servir(cliente, correos, db):
    h = await _registrar(cliente)
    viejo = _codigo(correos[0])

    assert (await cliente.post("/auth/verificacion/enviar", headers=h)).status_code == 429

    await db.execute(update(VerificacionCorreo).values(enviado_en=VerificacionCorreo.enviado_en - timedelta(seconds=61)))
    await db.commit()
    assert (await cliente.post("/auth/verificacion/enviar", headers=h)).status_code == 200
    nuevo = _codigo(correos[1])

    if nuevo != viejo:
        assert (await cliente.post("/auth/verificacion/confirmar", json={"codigo": viejo}, headers=h)).status_code == 400
    assert (await cliente.post("/auth/verificacion/confirmar", json={"codigo": nuevo}, headers=h)).status_code == 200


async def test_codigo_vencido(cliente, correos, db):
    h = await _registrar(cliente)
    await db.execute(update(VerificacionCorreo).values(expira_en=VerificacionCorreo.enviado_en - timedelta(minutes=1)))
    await db.commit()

    r = await cliente.post("/auth/verificacion/confirmar", json={"codigo": _codigo(correos[0])}, headers=h)

    assert r.status_code == 400 and "venció" in r.json()["detail"]


async def test_si_falla_el_correo_la_cuenta_igual_se_crea(cliente, monkeypatch):
    def _falla(*a, **k):
        raise ConnectionError("SMTP caído")
    monkeypatch.setattr(contacto, "enviar_email", _falla)

    h = await _registrar(cliente)  # 201 aunque no salió el correo

    assert (await cliente.get("/usuarios/me", headers=h)).json()["correo_verificado"] is False


async def test_cuenta_ya_verificada_no_pide_otro_codigo(cliente, db):
    _, adultos, _ = await crear_familia(db)  # las cuentas de prueba ya vienen verificadas
    from tests.fabricas import auth

    assert (await cliente.post("/auth/verificacion/enviar", headers=auth(adultos[0]))).status_code == 409


async def test_formato_del_codigo_y_sesion(cliente, correos):
    h = await _registrar(cliente)
    assert (await cliente.post("/auth/verificacion/confirmar", json={"codigo": "12ab"}, headers=h)).status_code == 422
    assert (await cliente.post("/auth/verificacion/confirmar", json={"codigo": "123456"})).status_code == 401

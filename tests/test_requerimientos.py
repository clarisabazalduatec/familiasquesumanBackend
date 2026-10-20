"""Una prueba por requerimiento funcional (backend). Correr: docker compose exec api pytest"""
import re
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (AmbitoCategoria, EncuestaActividad, EstadoProyecto, ModalidadDonacion, TipoCentro)
from app.models.iniciativas import EncuestaInicialActividad
from app.routers import chat, contacto
from tests.fabricas import (HERMOSILLO, MONTERREY, PASSWORD, PNG_1PX, auth, categoria, crear_actividad,
                            crear_centro, crear_donacion, crear_familia, crear_proyecto, crear_usuario,
                            en_horas, inscribir_directo)


def inscribir(cliente, actividad, adultos, menores=(), espera=False):
    return cliente.post(f"/actividades/{actividad.id}/inscripcion", headers=auth(adultos[0]), json={
        "usuario_ids": [str(a.id) for a in adultos], "menor_ids": [str(m) for m in menores], "lista_espera": espera})


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(contacto, "enviar_email", lambda destinatario, asunto, contenido, reply_to=None:
                        enviados.append({"para": destinatario, "texto": contenido}))
    monkeypatch.setenv("CONTACTO_DESTINATARIO", "contacto@familiasquesuman.mx")
    contacto.verificaciones.clear(), contacto.solicitudes.clear()
    return enviados


async def enviar_contacto(cliente, correos, mensaje):
    datos = {"nombre": "Mariana López", "correo": "mariana@ejemplo.mx", "mensaje": mensaje}
    assert (await cliente.post("/contacto/solicitar-codigo", json=datos)).status_code == 200
    codigo = re.search(r"\b(\d{6})\b", correos[0]["texto"]).group(1)
    return await cliente.post("/contacto/confirmar-codigo", json={"correo": datos["correo"], "codigo": codigo})


# RF-01 Directorio: centros verificados y organizados por categoría
async def test_rf01_directorio_por_categoria(cliente, db):
    await crear_centro(db, "Asilo San José", tipo=TipoCentro.ASILO)
    await crear_centro(db, "Casa Hogar Esperanza", tipo=TipoCentro.CASA_HOGAR)

    r = (await cliente.get("/centros", params={"tipo": "ASILO"})).json()

    assert [(c["nombre"], c["tipo"], c["verificado"]) for c in r] == [("Asilo San José", "ASILO", True)]


# RF-02 Filtro por ubicación: solo la ciudad elegida, y la elección se recuerda
async def test_rf02_filtro_por_ciudad_y_se_recuerda(cliente, db):
    await crear_actividad(db, "Limpieza Fundidora", ciudad_id=MONTERREY)
    await crear_actividad(db, "Limpieza Cerro de la Campana", ciudad_id=HERMOSILLO)
    yo = await crear_usuario(db, ciudad_id=MONTERREY)

    await cliente.put("/usuarios/me/ciudad", json={"ciudad_id": HERMOSILLO}, headers=auth(yo))
    ciudad = (await cliente.get("/usuarios/me", headers=auth(yo))).json()["ciudad_id"]
    actividades = (await cliente.get("/actividades", params={"ciudad_id": ciudad})).json()

    assert ciudad == HERMOSILLO
    assert [a["titulo"] for a in actividades] == ["Limpieza Cerro de la Campana"]


# RF-03 Ficha de asociación: qué hace, qué necesita, dónde está y cómo contactarla
async def test_rf03_ficha_completa(cliente, db):
    centro = await crear_centro(db)

    f = (await cliente.get(f"/centros/{centro.id}")).json()

    assert f["informacion_general"] and f["necesidades"] == ["Leche y pañales", "Útiles escolares"]
    assert f["direccion"] and f["ubicacion"].startswith("https://") and f["ciudad"]["nombre"] == "Monterrey"
    assert f["telefono"] and f["whatsapp"]


# RF-04 Actividades: fecha, horario, lugar y descripción
async def test_rf04_detalle_actividad(cliente, db):
    actividad = await crear_actividad(db, "Reforestación")

    a = (await cliente.get(f"/actividades/{actividad.id}")).json()

    assert a["inicia_en"] and a["termina_en"] and a["ciudad"]["nombre"] and a["ubicacion"]
    assert a["descripcion_corta"] and a["acerca_de"]


# RF-05 Cupo en tiempo real: descuenta lugares y no deja rebasar el cupo
async def test_rf05_no_rebasa_el_cupo(cliente, db):
    actividad = await crear_actividad(db, cupo=3)
    _, fam1, _ = await crear_familia(db, "Uno", adultos=2)
    _, fam2, _ = await crear_familia(db, "Dos", adultos=2)

    assert (await inscribir(cliente, actividad, fam1)).status_code == 201
    assert (await inscribir(cliente, actividad, fam2)).status_code == 409  # pide 2, queda 1
    assert (await cliente.get(f"/actividades/{actividad.id}")).json()["plazas_disponibles"] == 1


# RF-06 Acompañantes: nombres y edades quedan registrados en la inscripción
async def test_rf06_inscripcion_con_acompanantes(cliente, db):
    _, adultos, menores = await crear_familia(db, menores=[("Sofía", date(2016, 3, 15))])
    actividad = await crear_actividad(db)

    r = await inscribir(cliente, actividad, adultos, menores=[menores[0].id])
    familia = (await cliente.get("/familias/mia", headers=auth(adultos[0]))).json()

    assert {(p["tipo"], p["nombre"]) for p in r.json()["participantes"]} == {("ADULTO", adultos[0].nombre), ("MENOR", "Sofía")}
    assert familia["menores"][0]["edad"] >= 10


# RF-08 Contacto: nombre, correo y mensaje llegan al correo de Familias que Suman
async def test_rf08_contacto_llega_al_correo(cliente, correos):
    r = await enviar_contacto(cliente, correos, "¿Cómo inscribo a mi familia?")

    assert r.status_code == 200
    assert correos[1]["para"] == "contacto@familiasquesuman.mx"
    assert all(t in correos[1]["texto"] for t in ("Mariana López", "mariana@ejemplo.mx", "¿Cómo inscribo"))


# RF-09 Proyectos y campañas: solo los vigentes
async def test_rf09_proyectos_vigentes(cliente, db):
    await crear_proyecto(db, "Vigente")
    await crear_proyecto(db, "Del año pasado", estado=EstadoProyecto.ANTERIOR)

    r = (await cliente.get("/proyectos", params={"estado": "ACTIVO"})).json()

    assert [p["titulo"] for p in r] == ["Vigente"]


# RF-10 Información para donar: qué se necesita, dónde y en qué horario
async def test_rf10_que_donde_y_cuando(cliente, db):
    donacion = await crear_donacion(db)

    d = (await cliente.get(f"/donaciones/{donacion.id}")).json()

    assert d["etiquetas"]["articulo"] == ["Cobijas", "Ropa de invierno"]
    assert d["ubicacion"].startswith("https://") and d["horario"] == "Sábados de 10:00 a 13:00"


# RF-11 Perfil e historial: "Mis actividades" con las realizadas y las próximas
async def test_rf11_historial_de_la_familia(cliente, db):
    familia, adultos, _ = await crear_familia(db)
    await inscribir_directo(db, await crear_actividad(db, "Pasada", inicia_en=en_horas(-24 * 30)), familia, adultos)
    await inscribir_directo(db, await crear_actividad(db, "Próxima", inicia_en=en_horas(48)), familia, adultos)

    r = (await cliente.get("/familias/mia/inscripciones", headers=auth(adultos[0]))).json()

    assert [i["actividad"]["titulo"] for i in r] == ["Pasada", "Próxima"]


# RF-12 Testimonio con foto: queda pendiente y no es público hasta aprobarse
async def test_rf12_testimonio_con_foto_pendiente(cliente, db):
    yo = await crear_usuario(db)
    cat = await categoria(db, AmbitoCategoria.PUBLICACION, "Voluntariado")
    await db.commit()
    foto = (await cliente.post("/comunidad/imagenes", files={"archivo": ("f.png", PNG_1PX, "image/png")}, headers=auth(yo))).json()["url"]

    r = await cliente.post("/comunidad", headers=auth(yo), json={
        "titulo": "Reforestamos", "contenido": "Plantamos 12 encinos.", "categoria_id": cat.id, "imagenes": [foto]})

    assert r.json()["estado"] == "PENDIENTE" and r.json()["imagenes"][0]["url"] == foto
    assert (await cliente.get("/comunidad")).json() == []


# RF-13 Encuestas: antes y después, guardadas y ligadas a usuario y actividad
async def test_rf13_encuestas_guardadas(cliente, db):
    yo = await crear_usuario(db)
    actividad = await crear_actividad(db)

    await cliente.post(f"/actividades/{actividad.id}/encuesta-inicial", headers=auth(yo),
                       json={"motivos": ["Convivir"], "expectativas": ["Aprender"]})
    await cliente.post(f"/actividades/{actividad.id}/encuesta", headers=auth(yo),
                       json={"experiencia_general": 5, "utilidad_valor": 4, "facilidad_participacion": 5})

    for modelo in (EncuestaInicialActividad, EncuestaActividad):
        e = await db.scalar(select(modelo))
        assert (e.usuario_id, e.actividad_id) == (yo.id, actividad.id)


# RF-14 Insignias: una por cada actividad ya realizada
async def test_rf14_insignia_por_actividad_realizada(cliente, db):
    familia, adultos, _ = await crear_familia(db)
    await inscribir_directo(db, await crear_actividad(db, "Hecha", inicia_en=en_horas(-48)), familia, adultos)
    await inscribir_directo(db, await crear_actividad(db, "Futura", inicia_en=en_horas(48)), familia, adultos)

    r = (await cliente.get("/usuarios/me/insignias", headers=auth(adultos[0]))).json()

    assert [i["titulo_actividad"] for i in r] == ["Hecha"]


# RF-15 Privacidad: la solicitud de eliminación de datos llega a Familias que Suman
async def test_rf15_solicitud_de_eliminacion_de_datos(cliente, correos):
    r = await enviar_contacto(cliente, correos, "Solicito la eliminación de mis datos personales.")

    assert r.status_code == 200
    assert correos[1]["para"] == "contacto@familiasquesuman.mx" and "eliminación de mis datos" in correos[1]["texto"]


# RF-16 Notificaciones: lo que genera el sistema aparece en la sección del usuario
async def test_rf16_notificacion_de_inscripcion(cliente, db):
    _, adultos, _ = await crear_familia(db)
    actividad = await crear_actividad(db, "Comedor Solidario")
    await inscribir(cliente, actividad, adultos)

    [n] = (await cliente.get("/notificaciones", headers=auth(adultos[0]))).json()

    assert n["tipo"] == "INSCRIPCION_ACTIVIDAD" and "Comedor Solidario" in n["cuerpo"] and not n["leida"]


# RF-17 Cancelación: libera el lugar y sube a la primera familia en espera
async def test_rf17_cancelar_sube_la_lista_de_espera(cliente, db):
    actividad = await crear_actividad(db, cupo=1)
    _, fam1, _ = await crear_familia(db, "Uno")
    _, fam2, _ = await crear_familia(db, "Dos")
    await inscribir(cliente, actividad, fam1)
    assert (await inscribir(cliente, actividad, fam2, espera=True)).json()["estado"] == "EN_ESPERA"

    assert (await cliente.delete(f"/actividades/{actividad.id}/inscripcion", headers=auth(fam1[0]))).status_code == 204

    r = (await cliente.get(f"/actividades/{actividad.id}/inscripcion", headers=auth(fam2[0]))).json()
    assert r["estado"] == "CONFIRMADA"


# RF-18 Comunidad: moderación antes de publicar y avisos oficiales solo del admin
async def test_rf18_moderacion_y_avisos_solo_admin(cliente, db):
    admin, yo = await crear_usuario(db, "Admin", admin=True), await crear_usuario(db)
    cat = await categoria(db, AmbitoCategoria.PUBLICACION, "Voluntariado")
    await db.commit()
    pub = (await cliente.post("/comunidad", headers=auth(yo), json={"titulo": "T", "contenido": "C", "categoria_id": cat.id})).json()
    assert (await cliente.get("/comunidad")).json() == []

    await cliente.post(f"/comunidad/{pub['id']}/aprobar", headers=auth(admin))

    assert [p["id"] for p in (await cliente.get("/comunidad")).json()] == [pub["id"]]
    aviso = {"titulo": "Colecta", "contenido": "Te esperamos"}
    assert (await cliente.post("/comunidad/avisos", json=aviso, headers=auth(yo))).status_code == 403
    assert (await cliente.post("/comunidad/avisos", json=aviso, headers=auth(admin))).status_code == 201


# RF-19 Metas de donación: el progreso se actualiza al registrar donaciones
async def test_rf19_progreso_de_la_meta(cliente, db):
    admin = await crear_usuario(db, "Admin", admin=True)
    donacion = await crear_donacion(db, modalidad=ModalidadDonacion.CAMPANA, meta=35700, recaudado=14000)

    await cliente.put(f"/donaciones/{donacion.id}", headers=auth(admin), json={
        "titulo": "Destellos de Luz", "descripcion_corta": "Campaña", "modalidad": "CAMPANA",
        "meta": 35700, "recaudado": 21000, "opciones": [{"titulo": "Bastón", "monto": 700}]})

    d = (await cliente.get(f"/donaciones/{donacion.id}")).json()
    assert (d["recaudado"], d["meta"], d["opciones"][0]["titulo"]) == (21000, 35700, "Bastón")


# RF-20 Sesión y roles: login válido, permisos por rol y sin sesión se bloquea
async def test_rf20_login_y_permisos_por_rol(cliente, db):
    await crear_usuario(db, email="carlos@ejemplo.mx")
    admin = await crear_usuario(db, "Admin", admin=True)

    token = (await cliente.post("/auth/login", json={"email": "carlos@ejemplo.mx", "password": PASSWORD})).json()["access_token"]
    yo = {"Authorization": f"Bearer {token}"}

    assert (await cliente.get("/usuarios/me", headers=yo)).status_code == 200
    assert (await cliente.get("/actividades/admin", headers=yo)).status_code == 403
    assert (await cliente.get("/actividades/admin", headers=auth(admin))).status_code == 200
    assert (await cliente.get("/usuarios/me")).status_code == 401


# RF-21 Chatbot: responde con información de la base de datos (Gemini simulado)
async def test_rf21_chatbot_responde_con_datos_de_la_bd(cliente, db, monkeypatch):
    actividad = await crear_actividad(db, "Reforestación Parque Central")
    respuestas = [
        SimpleNamespace(function_calls=[SimpleNamespace(name="buscar_actividades", args={"texto": "reforestación"})]),
        SimpleNamespace(function_calls=None, candidates=[SimpleNamespace(content=SimpleNamespace(
            parts=[SimpleNamespace(text="Te recomiendo Reforestación Parque Central.", thought=False)]))]),
    ]
    recibido = []

    async def send_message(contenido):
        recibido.append(contenido)
        return respuestas.pop(0)
    sesion = SimpleNamespace(send_message=send_message)
    monkeypatch.setattr(chat, "cliente", SimpleNamespace(aio=SimpleNamespace(chats=SimpleNamespace(create=lambda **kw: sesion))))

    r = (await cliente.post("/chat", json={"mensaje": "¿Hay reforestaciones?"})).json()

    assert recibido[1][0].function_response.response["resultados"][0]["titulo"] == "Reforestación Parque Central"
    assert r["enlaces"] == [{"tipo": "actividad", "id": str(actividad.id), "titulo": "Reforestación Parque Central"}]

"""Configuración común de las pruebas del backend.

- Base de datos: un Postgres de pruebas APARTE (por default `familias_test` en el mismo servidor
  que la base de desarrollo). Se crea sola si no existe y se vacía antes de CADA prueba, así que
  las pruebas no dependen entre sí ni tocan los datos reales.
  No usamos SQLite (como en la guía) porque el backend usa cosas que solo tiene Postgres:
  UUID, enums nativos, INSERT ... ON CONFLICT, SELECT ... FOR UPDATE.
- La app se prueba entera (routers, validaciones, permisos) con httpx + ASGITransport,
  cambiando solo la infraestructura: la sesión de BD (override de get_db), el almacén S3
  (un diccionario en memoria), el correo SMTP y Gemini.
"""
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import almacen
from app import database
from app.config import settings
from app.database import Base, get_db
from app import models  # noqa: F401  registra todas las tablas en Base.metadata
from app.models import Ciudad

# ---------- URL de la base de pruebas ----------
_url_real = make_url(settings.database_url)
# Ojo: str(url) esconde la contraseña ("***"); por eso se trabaja con el objeto URL directo
URL_PRUEBAS = make_url(os.environ["TEST_DATABASE_URL"]) if os.getenv("TEST_DATABASE_URL") \
    else _url_real.set(database="familias_test")
URL_PRUEBAS_SYNC = URL_PRUEBAS.set(drivername="postgresql+psycopg2")

if URL_PRUEBAS.database == _url_real.database:
    raise RuntimeError("La base de pruebas no puede ser la misma que la de desarrollo: se borra en cada prueba")

TABLAS = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)


def _crear_base_si_no_existe() -> None:
    admin = create_engine(URL_PRUEBAS_SYNC.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        existe = con.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": URL_PRUEBAS.database})
        if not existe:
            con.execute(text(f'CREATE DATABASE "{URL_PRUEBAS.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def motor_sync():
    """Crea las tablas UNA vez por corrida (desde los modelos: son iguales a las migraciones)."""
    _crear_base_si_no_existe()
    motor = create_engine(URL_PRUEBAS_SYNC)
    with motor.begin() as con:
        con.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


@pytest.fixture(autouse=True)
def base_limpia(motor_sync):
    """Antes de cada prueba: todas las tablas vacías y solo las 2 ciudades del catálogo."""
    with motor_sync.begin() as con:
        con.execute(text(f"TRUNCATE {TABLAS} RESTART IDENTITY CASCADE"))
        con.execute(text("INSERT INTO ciudades (nombre, estado, activa) VALUES "
                         "('Monterrey', 'Nuevo León', true), ('Hermosillo', 'Sonora', true)"))


# ---------- Sesiones async ----------
@pytest.fixture
async def motor():
    # NullPool: cada sesión abre su conexión en el event loop de la prueba actual
    m = create_async_engine(URL_PRUEBAS, poolclass=NullPool)
    yield m
    await m.dispose()


@pytest.fixture
def fabrica_sesiones(motor):
    return async_sessionmaker(bind=motor, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db(fabrica_sesiones):
    """Sesión para preparar datos y revisar lo que quedó guardado (aparte de la que usa la API)."""
    async with fabrica_sesiones() as s:
        yield s


# ---------- Infraestructura falsa ----------
@pytest.fixture
def almacen_falso(monkeypatch):
    """El almacén S3 en un diccionario: {clave: bytes}."""
    objetos: dict[str, bytes] = {}

    class _Cuerpo:
        def __init__(self, datos):
            self._datos = datos

        def iter_chunks(self, _tam):
            yield self._datos

    monkeypatch.setattr(almacen, "_preparar", lambda: None)
    monkeypatch.setattr(almacen, "_guardar", lambda clave, datos, tipo: objetos.__setitem__(clave, datos))
    monkeypatch.setattr(almacen, "_existe", lambda clave: clave in objetos)
    monkeypatch.setattr(almacen, "_abrir", lambda clave: {"Body": _Cuerpo(objetos[clave])})
    monkeypatch.setattr(almacen, "_borrar", lambda clave: objetos.pop(clave, None))
    return objetos


@pytest.fixture
async def cliente(motor, fabrica_sesiones, almacen_falso, monkeypatch):
    """Cliente HTTP contra la app real, con la BD de pruebas."""
    from app.main import app

    async def _get_db_pruebas():
        async with fabrica_sesiones() as s:
            yield s

    # Algunos endpoints usan el engine directo (no get_db): también se apuntan a la BD de pruebas
    monkeypatch.setattr(database, "engine", motor)
    monkeypatch.setattr(database, "AsyncSessionLocal", fabrica_sesiones)
    app.dependency_overrides[get_db] = _get_db_pruebas
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://pruebas") as c:
        yield c
    app.dependency_overrides.clear()


# ---------- Datos de apoyo ----------
@pytest.fixture
async def ciudades(db):
    """{'Monterrey': id, 'Hermosillo': id}"""
    filas = (await db.execute(text("SELECT nombre, id FROM ciudades"))).all()
    return {n: i for n, i in filas}


def nuevo_email() -> str:
    return f"u{uuid.uuid4().hex[:10]}@pruebas.mx"
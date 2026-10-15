from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, Request
from prometheus_client import start_http_server
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.routing import Match
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings

from app.database import get_db
from app.metrics import HTTP_REQUESTS, HTTP_REQUEST_DURATION, HTTP_SERVER_ERRORS
from app.routers import (
    actividades,
    auth,
    catalogo,
    centros,
    chat,
    comunidad,
    donaciones,
    familias,
    invitaciones,
    proyectos,
    usuarios,
    imagenes,
    inscripciones
)

from app import almacen

app = FastAPI(title="Familias que Suman API")
_metrics_server = None


def obtener_plantilla_ruta(request: Request) -> str:
    ruta_resuelta = request.scope.get("route")
    if ruta_resuelta is not None:
        return getattr(ruta_resuelta, "path", "unmatched")

    coincidencia_parcial = None
    for ruta in request.app.router.routes:
        coincidencia, _ = ruta.matches(request.scope)
        if coincidencia is Match.FULL:
            return getattr(ruta, "path", "unmatched")
        if coincidencia is Match.PARTIAL and coincidencia_parcial is None:
            coincidencia_parcial = ruta

    return getattr(coincidencia_parcial, "path", "unmatched")


@app.middleware("http")
async def medir_peticion(request: Request, call_next):
    inicio = perf_counter()
    try:
        response = await call_next(request)
        codigo = response.status_code
    except Exception:
        codigo = 500
        ruta = obtener_plantilla_ruta(request)
        HTTP_REQUESTS.labels(request.method, ruta, str(codigo)).inc()
        HTTP_SERVER_ERRORS.labels(request.method, ruta, str(codigo)).inc()
        HTTP_REQUEST_DURATION.labels(request.method, ruta).observe(perf_counter() - inicio)
        raise

    ruta = obtener_plantilla_ruta(request)
    HTTP_REQUESTS.labels(request.method, ruta, str(codigo)).inc()
    if codigo >= 500:
        HTTP_SERVER_ERRORS.labels(request.method, ruta, str(codigo)).inc()
    HTTP_REQUEST_DURATION.labels(request.method, ruta).observe(perf_counter() - inicio)
    return response

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(imagenes.router)
app.include_router(usuarios.router)
app.include_router(familias.router)
app.include_router(invitaciones.router)
app.include_router(catalogo.router)
app.include_router(actividades.router)
app.include_router(inscripciones.router)
app.include_router(proyectos.router)
app.include_router(donaciones.router)
app.include_router(centros.router)
app.include_router(comunidad.router)

# Imágenes subidas por el admin: /media/<archivo>
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

@app.get("/health")
async def health_check():
    return {"status": "ok"}  # SIN base de datos


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(
        Path(__file__).parent / "static" / "favicon.svg",
        media_type="image/svg+xml",
    )


@app.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))  # despierta a Neon
    return {"status": "ok"}

@app.on_event("startup")
async def al_iniciar():
    global _metrics_server
    await almacen.preparar()
    if _metrics_server is None:
        _metrics_server, _ = start_http_server(9100, addr="0.0.0.0")


@app.on_event("shutdown")
async def al_cerrar():
    global _metrics_server
    if _metrics_server is not None:
        _metrics_server.shutdown()
        _metrics_server.server_close()
        _metrics_server = None
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import start_http_server
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Match

from app import almacen
from app.config import settings
from app.database import get_db
from app.limites import limiter
from app.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS, HTTP_SERVER_ERRORS, RATE_LIMITED
from app.routers import (
    actividades,
    auth,
    catalogo,
    centros,
    chat,
    comunidad,
    contacto,
    donaciones,
    familias,
    imagenes,
    inscripciones,
    invitaciones,
    notificaciones,
    proyectos,
    usuarios,
)

log = logging.getLogger("uvicorn.error")
auditoria = logging.getLogger("auditoria")
auditoria.setLevel(logging.INFO)
if not auditoria.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s AUDITORIA %(message)s"))
    auditoria.addHandler(_h)

_metrics_server = None


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Reemplaza @app.on_event("startup"/"shutdown"), que Starlette 1.x ya no soporta
    global _metrics_server
    await almacen.preparar()
    if _metrics_server is None:
        _metrics_server, _ = start_http_server(9100, addr="0.0.0.0")
    yield
    if _metrics_server is not None:
        _metrics_server.shutdown()
        _metrics_server.server_close()
        _metrics_server = None


# En producción no se publica la documentación: /docs, /redoc y /openapi.json describen
# toda la API a cualquiera que tenga la URL (y llegan por el túnel).
app = FastAPI(
    title="Familias que Suman API",
    lifespan=ciclo_de_vida,
    docs_url=None if settings.es_prod else "/docs",
    redoc_url=None,
    openapi_url=None if settings.es_prod else "/openapi.json",
)


# ---------- Errores ----------
@app.exception_handler(Exception)
async def error_no_controlado(request: Request, exc: Exception):
    """Cualquier excepción no prevista: el detalle va al log, al cliente un mensaje genérico
    (nunca SQL, nombres de tablas ni rutas del servidor)."""
    log.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Error interno del servidor"}, status_code=500)


@app.exception_handler(RateLimitExceeded)
async def demasiadas_peticiones(request: Request, exc: RateLimitExceeded):
    RATE_LIMITED.labels(obtener_plantilla_ruta(request)).inc()
    return JSONResponse(
        {"detail": "Demasiadas solicitudes. Espera un momento e inténtalo de nuevo."},
        status_code=429,
        headers={"Retry-After": "60"},
    )


# ---------- Rate limiting ----------
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)  # aplica el límite general a todo lo que no tiene uno propio


# ---------- Límite de tamaño del cuerpo ----------
MAX_CUERPO = settings.imagen_max_bytes + 256 * 1024  # la imagen más el resto del formulario


class LimiteCuerpo:
    """Rechaza con 413 cuerpos más grandes que MAX_CUERPO ANTES de que Starlette procese el
    multipart completo (antes se leía todo y hasta después se validaban los 2 MB).
    Revisa Content-Length y, si no viene (chunked), va contando lo que llega."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        largo = dict(scope["headers"]).get(b"content-length")
        if largo is not None and largo.isdigit() and int(largo) > MAX_CUERPO:
            return await self._rechazar(send)

        recibidos = 0

        async def receive_contado():
            nonlocal recibidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibidos += len(mensaje.get("body", b""))
                if recibidos > MAX_CUERPO:
                    raise CuerpoDemasiadoGrande()
            return mensaje

        try:
            await self.app(scope, receive_contado, send)
        except CuerpoDemasiadoGrande:
            await self._rechazar(send)

    @staticmethod
    async def _rechazar(send):
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"detail":"El archivo es demasiado grande"}'})


class CuerpoDemasiadoGrande(Exception):
    pass


app.add_middleware(LimiteCuerpo)


# ---------- Cabeceras de seguridad y bitácora ----------
CABECERAS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # La API solo regresa JSON e imágenes: no necesita cargar nada
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
RUTAS_DOCS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def cabeceras_y_auditoria(request: Request, call_next):
    respuesta = await call_next(request)
    for nombre, valor in CABECERAS.items():
        # /docs (solo existe en dev) carga JS y CSS de un CDN: con esta CSP no abriría
        if nombre == "Content-Security-Policy" and request.url.path.startswith(RUTAS_DOCS):
            continue
        respuesta.headers.setdefault(nombre, valor)
    if "cache-control" not in respuesta.headers:
        respuesta.headers["Cache-Control"] = "no-store"  # datos personales: que nadie los cachee

    # Bitácora de auditoría: toda escritura hecha por un admin (quién, qué, resultado)
    if getattr(request.state, "es_admin", False) and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        auditoria.info(
            "admin=%s %s %s -> %s",
            getattr(request.state, "usuario_id", "?"), request.method, request.url.path, respuesta.status_code,
        )
    return respuesta


# ---------- Métricas ----------
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


# ---------- Rutas ----------
app.include_router(contacto.router)
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
app.include_router(notificaciones.router)


# Imágenes subidas por el admin antes del almacén: /media/<archivo>
Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
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
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}

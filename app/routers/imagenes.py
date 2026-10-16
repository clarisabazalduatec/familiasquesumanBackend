import re
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from app import almacen
from app.config import settings
from app.models import Usuario
from app.security import requiere_admin

router = APIRouter(prefix="/imagenes", tags=["imágenes"])

CACHE = "public, max-age=31536000, immutable"


class ImagenSubida(BaseModel):
    clave: str
    url: str   # relativa: "/imagenes/<clave>"


async def guardar_imagen_subida(archivo: UploadFile) -> str:
    """Valida tamaño y tipo real del archivo, lo guarda en el almacén y regresa su clave.
    La usan POST /imagenes (admin) y PUT /usuarios/me/foto (cualquier usuario)."""
    datos = await archivo.read(settings.imagen_max_bytes + 1)
    if len(datos) > settings.imagen_max_bytes:
        raise HTTPException(413, f"La imagen pesa más de {settings.imagen_max_bytes // 1024 // 1024} MB")
    if not datos:
        raise HTTPException(400, "El archivo está vacío")
    tipo = almacen.tipo_por_bytes(datos)
    if tipo is None:
        raise HTTPException(415, "Solo se aceptan imágenes JPG, PNG o WEBP")
    return await almacen.guardar(datos, tipo)


@router.post("", response_model=ImagenSubida, status_code=status.HTTP_201_CREATED)
async def subir_imagen(archivo: UploadFile, _admin: Usuario = Depends(requiere_admin)):
    clave = await guardar_imagen_subida(archivo)
    return ImagenSubida(clave=clave, url=f"/imagenes/{clave}")


@router.get("/{clave}")
async def descargar_imagen(clave: str, request: Request):
    if not almacen.CLAVE_RE.match(clave):
        raise HTTPException(404, "Imagen no encontrada")

    etag = f'"{clave}"'   # la clave nunca cambia de contenido
    cabeceras = {"ETag": etag, "Cache-Control": CACHE}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cabeceras)   # sin tocar el almacén

    try:
        obj = await almacen.abrir(clave)
    except Exception:
        raise HTTPException(404, "Imagen no encontrada")

    tipo = almacen.TIPOS[clave.rsplit(".", 1)[1]]
    return StreamingResponse(
        iterate_in_threadpool(obj["Body"].iter_chunks(64 * 1024)),
        media_type=tipo,
        headers=cabeceras,
    )
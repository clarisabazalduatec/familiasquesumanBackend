"""Subida de imágenes (logos y fotos de proyectos, actividades, etc.). Solo admins.

La imagen se guarda en settings.media_dir y se sirve en /media/<archivo> (ver main.py).
Se regresa una URL RELATIVA ("/media/abc.jpg"): la app le antepone la dirección del
servidor, así funciona igual con localhost, 10.0.2.2 o el túnel de Cloudflare.
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.config import settings
from app.models import Usuario
from app.security import requiere_admin

router = APIRouter(prefix="/imagenes", tags=["imágenes"])

TIPOS_PERMITIDOS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
TAMANO_MAXIMO = 5 * 1024 * 1024  # 5 MB


class ImagenSubida(BaseModel):
    url: str


def carpeta_media() -> Path:
    carpeta = Path(settings.media_dir)
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


@router.post("", response_model=ImagenSubida, status_code=status.HTTP_201_CREATED)
async def subir_imagen(archivo: UploadFile, _admin: Usuario = Depends(requiere_admin)):
    extension = TIPOS_PERMITIDOS.get(archivo.content_type or "")
    if extension is None:
        raise HTTPException(status_code=415, detail="Solo se aceptan imágenes JPG, PNG o WEBP")

    contenido = await archivo.read(TAMANO_MAXIMO + 1)
    if len(contenido) > TAMANO_MAXIMO:
        raise HTTPException(status_code=413, detail="La imagen pesa más de 5 MB")
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    nombre = f"{uuid.uuid4().hex}{extension}"  # nombre nuevo: nunca se usa el que mandó el cliente
    (carpeta_media() / nombre).write_bytes(contenido)
    return ImagenSubida(url=f"/media/{nombre}")
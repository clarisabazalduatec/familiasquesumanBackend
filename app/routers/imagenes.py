import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app import almacen
from app.config import settings
from app.models import Usuario
from app.limites import SUBIDAS, limiter, usuario_o_ip
from app.security import requiere_admin

router = APIRouter(prefix="/imagenes", tags=["imágenes"])

CACHE = "public, max-age=31536000, immutable"


class ImagenSubida(BaseModel):
    clave: str
    url: str   # relativa: "/imagenes/<clave>"


# Una imagen de 2 MB puede descomprimirse a cientos de MB en RAM ("bomba de descompresión").
# 40 MP alcanza de sobra para fotos de celular.
Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # pasar el límite = error, no aviso
FORMATOS_PIL = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def _recodificar(datos: bytes, tipo: str) -> bytes:
    """Abre la imagen y la vuelve a guardar desde cero. Así:
    - se eliminan EXIF/GPS (la ubicación de la casa donde se tomó la foto) y cualquier otro metadato,
    - se descarta lo que venga pegado al archivo (un "polyglot" imagen + HTML/JS),
    - se confirma que de verdad es una imagen válida, no solo que empieza con los bytes correctos."""
    try:
        with Image.open(io.BytesIO(datos)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)  # respeta la orientación antes de quitar el EXIF
            formato = FORMATOS_PIL[tipo]
            if formato == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            salida = io.BytesIO()
            opciones = {"quality": 88, "optimize": True} if formato in ("JPEG", "WEBP") else {"optimize": True}
            img.save(salida, format=formato, **opciones)  # sin exif=..., así que no se copia
            return salida.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(413, "La imagen tiene demasiados pixeles")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(415, "El archivo no es una imagen válida")


async def guardar_imagen_subida(archivo: UploadFile) -> str:
    """Valida tamaño y tipo real del archivo, le quita los metadatos, lo guarda en el almacén
    y regresa su clave. La usan POST /imagenes (admin), /comunidad/imagenes y /usuarios/me/foto."""
    datos = await archivo.read(settings.imagen_max_bytes + 1)
    if len(datos) > settings.imagen_max_bytes:
        raise HTTPException(413, f"La imagen pesa más de {settings.imagen_max_bytes // 1024 // 1024} MB")
    if not datos:
        raise HTTPException(400, "El archivo está vacío")
    tipo = almacen.tipo_por_bytes(datos)
    if tipo is None:
        raise HTTPException(415, "Solo se aceptan imágenes JPG, PNG o WEBP")
    limpios = await run_in_threadpool(_recodificar, datos, tipo)  # Pillow es CPU: fuera del event loop
    return await almacen.guardar(limpios, tipo)


@router.post("", response_model=ImagenSubida, status_code=status.HTTP_201_CREATED)
@limiter.limit(SUBIDAS, key_func=usuario_o_ip)
async def subir_imagen(request: Request, archivo: UploadFile, _admin: Usuario = Depends(requiere_admin)):
    clave = await guardar_imagen_subida(archivo)
    return ImagenSubida(clave=clave, url=f"/imagenes/{clave}")


@router.get("/{clave}")
async def descargar_imagen(clave: str, request: Request):
    if not almacen.CLAVE_RE.match(clave):
        raise HTTPException(404, "Imagen no encontrada")

    etag = f'"{clave}"'   # la clave nunca cambia de contenido
    # nosniff: el navegador no puede "adivinar" otro tipo (ej. ejecutar como HTML)
    cabeceras = {"ETag": etag, "Cache-Control": CACHE, "X-Content-Type-Options": "nosniff"}
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
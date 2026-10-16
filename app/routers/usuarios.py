from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Usuario
from app.routers._comun import _borrar_objetos
from app.routers.imagenes import guardar_imagen_subida
from app.schemas_familia import PerfilActualizar, PerfilOut
from app.security import obtener_usuario_actual
router = APIRouter(prefix="/usuarios", tags=["perfil"])


@router.get("/me", response_model=PerfilOut)
async def mi_perfil(usuario: Usuario = Depends(obtener_usuario_actual)):
    return usuario


@router.patch("/me", response_model=PerfilOut)
async def actualizar_mi_perfil(
    datos: PerfilActualizar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    # exclude_unset: solo cambia lo que la app mandó. Mandar "ubicacion": null sí la borra.
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if campo == "nombre" and valor is None:
            continue  # el nombre es obligatorio, no se puede borrar
        setattr(usuario, campo, valor)
    await db.commit()
    await db.refresh(usuario)
    return usuario


# ---------- Foto de perfil ----------
# La app manda el archivo directo (multipart, campo "archivo"); no pasa por POST /imagenes,
# que es solo para admins. Así un usuario solo puede cambiar SU foto.

@router.put("/me/foto", response_model=PerfilOut)
async def cambiar_mi_foto(
    archivo: UploadFile,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    # Mismas reglas que las demás imágenes: máx. 2 MB, solo JPG/PNG/WEBP (por su contenido real)
    clave_nueva = await guardar_imagen_subida(archivo)
    anterior = usuario.foto_url
    usuario.foto_url = clave_nueva
    try:
        await db.commit()
    except Exception:
        await _borrar_objetos([clave_nueva])  # no dejar la imagen huérfana en el almacén
        raise
    # Solo después del commit: la foto anterior ya no la usa nadie
    if anterior:
        await _borrar_objetos([anterior])
    await db.refresh(usuario)
    return usuario


@router.delete("/me/foto", response_model=PerfilOut)
async def quitar_mi_foto(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    anterior = usuario.foto_url
    usuario.foto_url = None
    await db.commit()
    if anterior:
        await _borrar_objetos([anterior])
    await db.refresh(usuario)
    return usuario
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Usuario
from app.schemas import UsuarioCrear, UsuarioLogin, TokenRespuesta
from app.security import hashear_password, verificar_password, crear_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/registro", response_model=TokenRespuesta, status_code=status.HTTP_201_CREATED)
async def registrar_usuario(datos: UsuarioCrear, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(select(Usuario).where(Usuario.email == datos.email))
    if resultado.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese correo")

    usuario = Usuario(
        nombre=datos.nombre,
        email=datos.email,
        password_hash=hashear_password(datos.password),
        ubicacion=datos.ubicacion,
    )
    db.add(usuario)
    await db.commit()
    await db.refresh(usuario)

    token = crear_access_token(usuario.id)
    return TokenRespuesta(access_token=token, usuario=usuario)


@router.post("/login", response_model=TokenRespuesta)
async def iniciar_sesion(datos: UsuarioLogin, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(select(Usuario).where(Usuario.email == datos.email))
    usuario = resultado.scalar_one_or_none()

    if usuario is None or not verificar_password(datos.password, usuario.password_hash):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

    token = crear_access_token(usuario.id)
    return TokenRespuesta(access_token=token, usuario=usuario)

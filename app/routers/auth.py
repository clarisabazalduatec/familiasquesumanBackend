from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.database import get_db
from app.models import Usuario
from app.schemas import UsuarioCrear, UsuarioLogin, TokenRespuesta
from app.security import hashear_password, verificar_password, crear_access_token
from app.metrics import AUTH_EVENTS
from app.routers._comun import _ciudad_id

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/registro", response_model=TokenRespuesta, status_code=status.HTTP_201_CREATED)
async def registrar_usuario(datos: UsuarioCrear, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(select(Usuario).where(Usuario.email == datos.email))
    if resultado.scalar_one_or_none() is not None:
        AUTH_EVENTS.labels("register", "failure").inc()
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese correo")

    usuario = Usuario(
        nombre=datos.nombre,
        email=datos.email,
        password_hash=hashear_password(datos.password),
        ciudad_id=await _ciudad_id(db, datos.ciudad_id),
    )
    db.add(usuario)
    await db.commit()
    await db.refresh(usuario)

    token = crear_access_token(usuario.id)
    AUTH_EVENTS.labels("register", "success").inc()
    return TokenRespuesta(access_token=token, usuario=usuario)


@router.post("/login", response_model=TokenRespuesta)
async def iniciar_sesion(datos: UsuarioLogin, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(select(Usuario).where(Usuario.email == datos.email))
    usuario = resultado.scalar_one_or_none()

    if usuario is None or not verificar_password(datos.password, usuario.password_hash):
        AUTH_EVENTS.labels("login", "failure").inc()
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

    token = crear_access_token(usuario.id)
    AUTH_EVENTS.labels("login", "success").inc()
    return TokenRespuesta(access_token=token, usuario=usuario)

@router.post("/token", include_in_schema=False)
async def token_para_swagger(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Solo para el botón Authorize de /docs (manda formulario, no JSON). La app usa /auth/login."""
    resultado = await db.execute(select(Usuario).where(Usuario.email == form.username))
    usuario = resultado.scalar_one_or_none()
    if usuario is None or not verificar_password(form.password, usuario.password_hash):
        AUTH_EVENTS.labels("token", "failure").inc()
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    AUTH_EVENTS.labels("token", "success").inc()
    return {"access_token": crear_access_token(usuario.id), "token_type": "bearer"}

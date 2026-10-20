from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.limites import LOGIN, REGISTRO, limiter
from app.metrics import AUTH_EVENTS
from app.models import Usuario
from app.routers._comun import _ciudad_id
from app.schemas import TokenRespuesta, UsuarioCrear, UsuarioLogin
from app.security import (
    HASH_FALSO, crear_access_token, hashear_password, obtener_usuario_actual, verificar_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

CREDENCIALES_INVALIDAS = "Correo o contraseña incorrectos"
CUENTA_BLOQUEADA = "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo."


async def _buscar_por_email(db: AsyncSession, email: str) -> Usuario | None:
    # Sin distinguir mayúsculas: Ana@x.mx y ana@x.mx son la misma cuenta
    return await db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.strip().lower()))


async def _autenticar(db: AsyncSession, email: str, password: str, accion: str) -> Usuario:
    """Login con bloqueo temporal por cuenta y tiempo de respuesta constante."""
    usuario = await _buscar_por_email(db, email)
    ahora = datetime.now(timezone.utc)

    if usuario is not None and usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
        AUTH_EVENTS.labels(accion, "locked").inc()
        raise HTTPException(status_code=429, detail=CUENTA_BLOQUEADA)

    # Siempre se calcula un bcrypt, exista o no el correo: así el tiempo no revela qué cuentas existen
    ok = verificar_password(password, usuario.password_hash if usuario else HASH_FALSO)

    if usuario is None or not ok:
        if usuario is not None:
            usuario.intentos_fallidos = (usuario.intentos_fallidos or 0) + 1
            if usuario.intentos_fallidos >= settings.login_max_fallos:
                usuario.bloqueado_hasta = ahora + timedelta(minutes=settings.login_bloqueo_minutos)
                usuario.intentos_fallidos = 0
                AUTH_EVENTS.labels(accion, "lockout").inc()
            await db.commit()
        AUTH_EVENTS.labels(accion, "failure").inc()
        raise HTTPException(status_code=401, detail=CREDENCIALES_INVALIDAS)

    if usuario.intentos_fallidos or usuario.bloqueado_hasta:
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
        await db.commit()
    AUTH_EVENTS.labels(accion, "success").inc()
    return usuario


@router.post("/registro", response_model=TokenRespuesta, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTRO)
async def registrar_usuario(request: Request, datos: UsuarioCrear, db: AsyncSession = Depends(get_db)):
    if await _buscar_por_email(db, datos.email) is not None:
        AUTH_EVENTS.labels("register", "failure").inc()
        # Este mensaje sí dice que el correo existe: sin verificación de correo no hay otra forma
        # de explicarle al usuario por qué no puede registrarse. El rate limit frena la enumeración.
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese correo")

    usuario = Usuario(
        nombre=datos.nombre,
        email=datos.email,  # ya viene en minúsculas desde el esquema
        password_hash=hashear_password(datos.password),
        ciudad_id=await _ciudad_id(db, datos.ciudad_id),
    )
    db.add(usuario)
    try:
        await db.commit()
    except IntegrityError:
        # Dos registros simultáneos con el mismo correo: el índice único lower(email) frena al segundo
        await db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese correo")
    await db.refresh(usuario)

    AUTH_EVENTS.labels("register", "success").inc()
    return TokenRespuesta(access_token=crear_access_token(usuario), usuario=usuario)


@router.post("/login", response_model=TokenRespuesta)
@limiter.limit(LOGIN)
async def iniciar_sesion(request: Request, datos: UsuarioLogin, db: AsyncSession = Depends(get_db)):
    usuario = await _autenticar(db, datos.email, datos.password, "login")
    return TokenRespuesta(access_token=crear_access_token(usuario), usuario=usuario)


@router.post("/token", include_in_schema=False)
@limiter.limit(LOGIN)
async def token_para_swagger(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Solo para el botón Authorize de /docs (manda formulario, no JSON). La app usa /auth/login."""
    usuario = await _autenticar(db, form.username, form.password, "token")
    return {"access_token": crear_access_token(usuario), "token_type": "bearer"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def cerrar_sesion_en_todos_lados(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """Invalida TODOS los tokens del usuario (este celular y cualquier otro)."""
    usuario.sesion_version = (usuario.sesion_version or 0) + 1
    await db.commit()
    AUTH_EVENTS.labels("logout", "success").inc()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

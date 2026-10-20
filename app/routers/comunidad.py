from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Response, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.enums import AmbitoCategoria

import uuid
from datetime import datetime, timezone
from app.security import requiere_admin
from app.routers.imagenes import guardar_imagen_subida, ImagenSubida
from app import almacen
from app.database import get_db
from app.models import (
    AmbitoCategoria,
    Categoria,
    EstadoPublicacion,
    Publicacion,
    PublicacionLike,
    PublicacionImagen,
    RolUsuario,
    TipoPublicacion,
    Usuario,
    Comentario,
)
from app.routers._comun import Paginacion, _ciudad_id
from app.models import DestinoNotificacion, TipoNotificacion
from app.notificaciones_servicio import (
    nombre_publicacion, notificar, notificar_admins, notificar_like, notificar_usuarios,
)
from app.schemas_comunidad import PublicacionDetalle
from app.schemas_comunidad import PublicacionCrear, PublicacionResumen, PublicacionRechazar, AvisoOficialCrear,ComentarioCrear,ComentarioRespuesta
from app.security import (
    obtener_usuario_actual,
    obtener_usuario_opcional,
    requiere_admin,
)

router = APIRouter(prefix="/comunidad", tags=["comunidad"])

## subir imagenes para comunidad (sin ser admin)
@router.post(
    "/imagenes",
    response_model=ImagenSubida,
    status_code=status.HTTP_201_CREATED
)
async def subir_imagen_comunidad(
    archivo: UploadFile,
    usuario: Usuario = Depends(obtener_usuario_actual)
):
    clave = await guardar_imagen_subida(archivo)
    return ImagenSubida( clave=clave, url=f"/imagenes/{clave}")

async def _validar_imagenes(urls: list[str]) -> list[str]:
    """Valida imágenes con el almacén existente del proyecto."""
    claves = []
    for url in urls:
        clave = almacen.clave_de(url)
        if not clave:
            raise HTTPException(
                status_code=422,
                detail="La imagen no es válida"
            )
        if not clave.startswith(("http", "/media/")):
            if not almacen.CLAVE_RE.match(clave) or not await almacen.existe(clave):
                raise HTTPException(
                    status_code=422,
                    detail=f"La imagen {clave} no existe en el almacén"
                )
        claves.append(clave)
    return claves


## publicaciones de comunidad
@router.get("", response_model=list[PublicacionResumen])
async def listar_publicaciones(
    pag: Paginacion = Depends(),
    usuario: Usuario | None = Depends(obtener_usuario_opcional),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
            Publicacion.estado == EstadoPublicacion.APROBADA,
        )
        .order_by(Publicacion.publicada_en.desc())
        .limit(pag.limit)
        .offset(pag.offset)
    )

    publicaciones = (await db.execute(stmt)).scalars().all()
    resultado = []
    for publicacion in publicaciones:
        respuesta = PublicacionResumen.model_validate(publicacion)
        respuesta.total_likes = len(publicacion.likes)
        respuesta.total_comentarios = sum(
            1 for comentario in publicacion.comentarios if comentario.visible
        )
        respuesta.me_gusta = (
            usuario is not None
            and any(like.usuario_id == usuario.id for like in publicacion.likes)
        )
        resultado.append(respuesta)
    return resultado


@router.post(
    "",response_model=PublicacionResumen,status_code=status.HTTP_201_CREATED,)
async def crear_publicacion(
    datos: PublicacionCrear,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    
    if datos.categoria_id is not None:
        categoria = await db.get(Categoria, datos.categoria_id)
    if categoria is None:
        raise HTTPException(status_code=400,detail="La categoría no existe")
    if categoria.ambito != AmbitoCategoria.PUBLICACION:
        raise HTTPException(  status_code=400, detail="La categoría debe pertenecer al ámbito PUBLICACION" )
    claves = await _validar_imagenes(datos.imagenes)
    publicacion = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD,
        autor_id=usuario.id,
        titulo=datos.titulo,
        contenido=datos.contenido,
        categoria_id=datos.categoria_id,
        ciudad_id=await _ciudad_id(db, datos.ciudad_id),
        ubicacion=datos.ubicacion,
        estado=EstadoPublicacion.PENDIENTE,
        imagenes=[
            PublicacionImagen(url=clave, orden=i)
            for i, clave in enumerate(claves)
        ],
    )

    db.add(publicacion)
    await db.flush()  # para tener el id
    # Admin: hay una publicación nueva que revisar
    await notificar_admins(
        db, TipoNotificacion.PUBLICACION_POR_REVISAR,
        "Nueva publicación por revisar",
        f"{usuario.nombre} envió «{nombre_publicacion(publicacion)}».",
        DestinoNotificacion.MODERACION, publicacion.id,
    )
    await db.commit()
    stmt = select(Publicacion).where(Publicacion.id == publicacion.id)
    return (await db.execute(stmt)).scalar_one()


# admin" consultar, aprobar y rechazar publicaciones de Comunidad
@router.get("/pendientes", response_model=list[PublicacionResumen])
async def listar_publicaciones_pendientes(
    pag: Paginacion = Depends(),
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
            Publicacion.estado == EstadoPublicacion.PENDIENTE,
        )
        .order_by(Publicacion.creado_en.asc())
        .limit(pag.limit)
        .offset(pag.offset)
    )

    return (await db.execute(stmt)).scalars().all()


@router.post(
    "/{publicacion_id}/aprobar",response_model=PublicacionResumen,)
async def aprobar_publicacion(
    publicacion_id: uuid.UUID,
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.id == publicacion_id,
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
        )
        .with_for_update()
    )
    publicacion = (await db.execute(stmt)).scalar_one_or_none()
    if publicacion is None:
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    if publicacion.estado != EstadoPublicacion.PENDIENTE:
        raise HTTPException(
            status_code=409,
            detail="Esta publicación ya fue revisada"
        )
    ahora = datetime.now(timezone.utc)
    publicacion.estado = EstadoPublicacion.APROBADA
    publicacion.revisado_por = admin.id
    publicacion.revisado_en = ahora
    publicacion.publicada_en = ahora
    publicacion.motivo_rechazo = None
    await notificar(
        db, publicacion.autor_id, TipoNotificacion.PUBLICACION_APROBADA,
        "Tu publicación fue aprobada",
        f"«{nombre_publicacion(publicacion)}» ya está visible en Comunidad.",
        DestinoNotificacion.PUBLICACION, publicacion.id,
    )
    await db.commit()
    stmt = select(Publicacion).where(
        Publicacion.id == publicacion_id
    )
    return (await db.execute(stmt)).scalar_one()


@router.post(
    "/{publicacion_id}/rechazar",response_model=PublicacionResumen,)
async def rechazar_publicacion(
    publicacion_id: uuid.UUID,
    datos: PublicacionRechazar,
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.id == publicacion_id,
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
        )
        .with_for_update()
    )
    publicacion = (await db.execute(stmt)).scalar_one_or_none()
    if publicacion is None:
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    if publicacion.estado != EstadoPublicacion.PENDIENTE:
        raise HTTPException(
            status_code=409,
            detail="Esta publicación ya fue revisada"
        )
    publicacion.estado = EstadoPublicacion.RECHAZADA
    publicacion.motivo_rechazo = datos.motivo_rechazo
    publicacion.revisado_por = admin.id
    publicacion.revisado_en = datetime.now(timezone.utc)
    publicacion.publicada_en = None
    await notificar(
        db, publicacion.autor_id, TipoNotificacion.PUBLICACION_RECHAZADA,
        "Tu publicación no fue aprobada",
        f"«{nombre_publicacion(publicacion)}»: {datos.motivo_rechazo}",
        DestinoNotificacion.MIS_PUBLICACIONES, publicacion.id,
    )
    await db.commit()
    stmt = select(Publicacion).where(
        Publicacion.id == publicacion_id
    )
    return (await db.execute(stmt)).scalar_one()

# Admin: historial de publicaciones aprobadas
@router.get("/aprobadas", response_model=list[PublicacionDetalle])
async def listar_publicaciones_aprobadas(
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
            Publicacion.estado == EstadoPublicacion.APROBADA,
            Publicacion.revisado_en.is_not(None),
        )
        .order_by(
            Publicacion.revisado_en.desc(),
            Publicacion.id.desc(),
        )
        .limit(10)
    )

    return (await db.execute(stmt)).scalars().all()


# Admin: historial de publicaciones rechazadas
@router.get("/rechazadas", response_model=list[PublicacionDetalle])
async def listar_publicaciones_rechazadas(
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
            Publicacion.estado == EstadoPublicacion.RECHAZADA,
            Publicacion.revisado_en.is_not(None),
        )
        .order_by(
            Publicacion.revisado_en.desc(),
            Publicacion.id.desc(),
        )
        .limit(10)
    )

    return (await db.execute(stmt)).scalars().all()

# admin: crear Avisos Oficiales
@router.post(
    "/avisos",
    response_model=PublicacionResumen,
    status_code=status.HTTP_201_CREATED,
)
async def crear_aviso_oficial(
    datos: AvisoOficialCrear,
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    if (
        datos.evento_inicia_en is not None
        and datos.evento_termina_en is not None
        and datos.evento_termina_en < datos.evento_inicia_en
    ):
        raise HTTPException(
            status_code=422,
            detail="La fecha de fin no puede ser anterior al inicio"
        )
    claves = await _validar_imagenes(datos.imagenes)
    ahora = datetime.now(timezone.utc)
    aviso = Publicacion(
        tipo=TipoPublicacion.OFICIAL,
        autor_id=admin.id,
        titulo=datos.titulo,
        contenido=datos.contenido,
        estado=EstadoPublicacion.APROBADA,
        publicada_en=ahora,
        evento_inicia_en=datos.evento_inicia_en,
        evento_termina_en=datos.evento_termina_en,
        publico_objetivo=datos.publico_objetivo,
        documento_url=datos.documento_url,
        documento_nombre=datos.documento_nombre,
        imagenes=[
            PublicacionImagen(url=clave, orden=i)
            for i, clave in enumerate(claves)
        ],
    )
    db.add(aviso)
    await db.flush()  # para tener el id
    # Todos los usuarios: nuevo aviso oficial
    await notificar_usuarios(
        db, TipoNotificacion.AVISO_OFICIAL,
        "Nuevo aviso de Familias que Suman",
        aviso.titulo,
        DestinoNotificacion.AVISO, aviso.id,
    )
    await db.commit()
    stmt = select(Publicacion).where(
        Publicacion.id == aviso.id
    )

    return (await db.execute(stmt)).scalar_one()


@router.get("/avisos",response_model=list[PublicacionResumen],)
async def listar_avisos_oficiales(
    pag: Paginacion = Depends(),
    usuario: Usuario | None = Depends(obtener_usuario_opcional),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.tipo == TipoPublicacion.OFICIAL,
            Publicacion.estado == EstadoPublicacion.APROBADA,
        )
        .order_by(Publicacion.publicada_en.desc())
        .limit(pag.limit)
        .offset(pag.offset)
    )
    publicaciones = (await db.execute(stmt)).scalars().all()
    resultado = []
    for publicacion in publicaciones:
        respuesta = PublicacionResumen.model_validate(publicacion)
        respuesta.total_likes = len(publicacion.likes)
        respuesta.total_comentarios = sum( 1 for comentario in publicacion.comentarios
            if comentario.visible
        )
        respuesta.me_gusta = (usuario is not None
            and any(like.usuario_id == usuario.id
                for like in publicacion.likes
            )
        )
        resultado.append(respuesta)
    return resultado



##likes de publicaciones
@router.post("/{publicacion_id}/like", status_code=status.HTTP_204_NO_CONTENT,)
async def dar_like_publicacion(
    publicacion_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    publicacion = await db.get(Publicacion, publicacion_id)
    if (publicacion is None
        or publicacion.tipo not in (
            TipoPublicacion.COMUNIDAD,
            TipoPublicacion.OFICIAL,
        )
        or publicacion.estado != EstadoPublicacion.APROBADA
    ):
        raise HTTPException(status_code=404,detail="Publicación no encontrada")
    like = await db.get(
        PublicacionLike,
        (publicacion_id, usuario.id)
    )
    if like is None:
        db.add(PublicacionLike(
                publicacion_id=publicacion_id,
                usuario_id=usuario.id
            )
        )
        await db.flush()  
        await notificar_like(db, publicacion, usuario)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
"/{publicacion_id}/like",status_code=status.HTTP_204_NO_CONTENT,)
async def quitar_like_publicacion(
    publicacion_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    publicacion = await db.get(Publicacion, publicacion_id)
    if (
        publicacion is None
        or publicacion.tipo not in (
            TipoPublicacion.COMUNIDAD,
            TipoPublicacion.OFICIAL,
        )
        or publicacion.estado != EstadoPublicacion.APROBADA
    ):
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    like = await db.get( PublicacionLike,(publicacion_id, usuario.id))
    if like is not None:
        await db.delete(like)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# consultar likes de una publicación
@router.get("/{publicacion_id}/likes")
async def consultar_likes_publicacion(
    publicacion_id: uuid.UUID,
    usuario: Usuario | None = Depends(obtener_usuario_opcional),
    db: AsyncSession = Depends(get_db),
):
    publicacion = await db.get(Publicacion, publicacion_id)
    if (
        publicacion is None
        or publicacion.tipo not in (
            TipoPublicacion.COMUNIDAD,
            TipoPublicacion.OFICIAL,
        )
        or publicacion.estado != EstadoPublicacion.APROBADA
    ):
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    stmt = select(func.count()).select_from(PublicacionLike).where(
        PublicacionLike.publicacion_id == publicacion_id
    )
    total_likes = await db.scalar(stmt)
    me_gusta = False
    if usuario is not None:
        mi_like = await db.get(
            PublicacionLike, (publicacion_id, usuario.id))
        me_gusta = mi_like is not None
    return {
        "total_likes": total_likes or 0,
        "me_gusta": me_gusta,
    }

##comentarios (comunidad)
@router.post(
    "/{publicacion_id}/comentarios",response_model=ComentarioRespuesta,status_code=status.HTTP_201_CREATED,)
async def crear_comentario(
    publicacion_id: uuid.UUID,
    datos: ComentarioCrear,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    publicacion = await db.get(Publicacion, publicacion_id)
    if (
        publicacion is None
        or publicacion.tipo not in (
            TipoPublicacion.COMUNIDAD,
            TipoPublicacion.OFICIAL,
        )
        or publicacion.estado != EstadoPublicacion.APROBADA
    ):
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    comentario = Comentario(
        publicacion_id=publicacion_id,
        autor_id=usuario.id,
        contenido=datos.contenido,
    )
    db.add(comentario)
    if publicacion.autor_id != usuario.id:
        texto = " ".join(datos.contenido.split())
        await notificar(
            db, publicacion.autor_id, TipoNotificacion.NUEVO_COMENTARIO,
            "Nuevo comentario",
            f"{usuario.nombre.split(' ')[0]} comentó «{nombre_publicacion(publicacion)}»: "
            f"{texto[:80]}{'…' if len(texto) > 80 else ''}",
            DestinoNotificacion.PUBLICACION, publicacion.id,
        )
    await db.commit()
    stmt = select(Comentario).where(
        Comentario.id == comentario.id
    )
    return (await db.execute(stmt)).scalar_one()


##consultar ocmentarios 
@router.get(
    "/{publicacion_id}/comentarios", response_model=list[ComentarioRespuesta],)
async def listar_comentarios(
    publicacion_id: uuid.UUID,
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    publicacion = await db.get(Publicacion, publicacion_id)
    if (publicacion is None
        or publicacion.tipo not in (
            TipoPublicacion.COMUNIDAD,
            TipoPublicacion.OFICIAL,
        )
        or publicacion.estado != EstadoPublicacion.APROBADA
    ):
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    stmt = (
        select(Comentario)
        .where(
            Comentario.publicacion_id == publicacion_id,
            Comentario.visible.is_(True),
        )
        .order_by(Comentario.creado_en.asc(), Comentario.id.asc())
        .limit(pag.limit)
        .offset(pag.offset)
    )
    return (await db.execute(stmt)).scalars().all()


##mis publicaciones - consultar estado
@router.get("/mias", response_model=list[PublicacionDetalle])
async def listar_mis_publicaciones(
    pag: Paginacion = Depends(),
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Publicacion)
        .where(
            Publicacion.autor_id == usuario.id,
            Publicacion.tipo == TipoPublicacion.COMUNIDAD,
        )
        .order_by(Publicacion.creado_en.desc())
        .limit(pag.limit)
        .offset(pag.offset)
    )

    publicaciones = (await db.execute(stmt)).scalars().all()
    resultado = []
    for publicacion in publicaciones:
        respuesta = PublicacionDetalle.model_validate(publicacion)
        respuesta.total_likes = len(publicacion.likes)
        respuesta.total_comentarios = sum( 1 for comentario in publicacion.comentarios if comentario.visible)
        respuesta.me_gusta = any(like.usuario_id == usuario.id for like in publicacion.likes )
        resultado.append(respuesta)
    return resultado



## detalle de publicación de comunidad
@router.get(
    "/{publicacion_id}",response_model=PublicacionDetalle,)
async def detalle_publicacion(
    publicacion_id: uuid.UUID,
    usuario: Usuario | None = Depends(obtener_usuario_opcional),
    db: AsyncSession = Depends(get_db),
):
    publicacion = await db.get(Publicacion, publicacion_id)
    if ( publicacion is None
        or publicacion.estado != EstadoPublicacion.APROBADA
    ):
        raise HTTPException(
            status_code=404,
            detail="Publicación no encontrada"
        )
    # Contar likes
    stmt_likes = (
        select(func.count())
        .select_from(PublicacionLike)
        .where(PublicacionLike.publicacion_id == publicacion_id)
    )
    total_likes = await db.scalar(stmt_likes)
    # Contar comentarios visibles
    stmt_comentarios = (
        select(func.count())
        .select_from(Comentario)
        .where(
            Comentario.publicacion_id == publicacion_id,
            Comentario.visible.is_(True),
        )
    )
    total_comentarios = await db.scalar(stmt_comentarios)
    me_gusta = False
    if usuario is not None:
        mi_like = await db.get(
            PublicacionLike,
            (publicacion_id, usuario.id)
        )
        me_gusta = mi_like is not None
    respuesta = PublicacionDetalle.model_validate(publicacion)
    respuesta.total_likes = total_likes or 0
    respuesta.total_comentarios = total_comentarios or 0
    respuesta.me_gusta = me_gusta
    return respuesta





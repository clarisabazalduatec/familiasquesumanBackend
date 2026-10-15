"""Familia del usuario: crearla, verla, salirse, menores e invitaciones enviadas.

Reglas:
- Un usuario pertenece a máximo una familia.
- Cualquier adulto de la familia puede invitar y gestionar menores.
- Nadie puede sacar a otro adulto; cada quien solo puede salirse.
- Si sale el último adulto se borra la familia (y por CASCADE sus menores e invitaciones),
  para que nunca queden familias con puros niños.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import EstadoInvitacion, Familia, FamiliaMenor, InvitacionFamilia, Usuario
from app.schemas_familia import (
    FamiliaActualizar,
    FamiliaCrear,
    FamiliaOut,
    InvitacionCrear,
    InvitacionEnviadaOut,
    MenorActualizar,
    MenorCrear,
    MenorOut,
)
from app.inscripciones_servicio import cancelar_inscripciones_vacias, quitar_adulto_de_inscripciones_futuras
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/familias", tags=["familia"])


# ---------- helpers ----------
def _exigir_familia(usuario: Usuario) -> uuid.UUID:
    if usuario.familia_id is None:
        raise HTTPException(status_code=404, detail="Todavía no perteneces a una familia")
    return usuario.familia_id


async def _familia_completa(db: AsyncSession, familia_id: uuid.UUID) -> FamiliaOut:
    """Arma la respuesta con adultos, menores e invitaciones pendientes.

    En async no hay carga perezosa de relaciones, por eso todo va con selectinload.
    """
    familia = (
        await db.execute(
            select(Familia)
            .where(Familia.id == familia_id)
            .options(
                selectinload(Familia.adultos),
                selectinload(Familia.menores),
                selectinload(Familia.invitaciones).selectinload(InvitacionFamilia.invitado),
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    return FamiliaOut(
        id=familia.id,
        nombre=familia.nombre,
        creado_en=familia.creado_en,
        adultos=sorted(familia.adultos, key=lambda u: u.nombre.lower()),
        menores=sorted(familia.menores, key=lambda m: m.fecha_nacimiento),
        invitaciones_pendientes=[
            i for i in sorted(familia.invitaciones, key=lambda i: i.creado_en)
            if i.estado == EstadoInvitacion.PENDIENTE
        ],
    )


async def _menor_de_mi_familia(db: AsyncSession, usuario: Usuario, menor_id: uuid.UUID) -> FamiliaMenor:
    familia_id = _exigir_familia(usuario)
    menor = (
        await db.execute(
            select(FamiliaMenor).where(FamiliaMenor.id == menor_id, FamiliaMenor.familia_id == familia_id)
        )
    ).scalar_one_or_none()
    if menor is None:
        raise HTTPException(status_code=404, detail="Menor no encontrado en tu familia")
    return menor


# ---------- familia ----------
@router.post("", response_model=FamiliaOut, status_code=status.HTTP_201_CREATED)
async def crear_familia(
    datos: FamiliaCrear,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    if usuario.familia_id is not None:
        raise HTTPException(status_code=409, detail="Ya perteneces a una familia")

    familia = Familia(nombre=datos.nombre)
    db.add(familia)
    await db.flush()  # para que familia.id exista

    usuario.familia_id = familia.id
    if datos.parentesco is not None:
        usuario.parentesco = datos.parentesco
    await db.commit()
    return await _familia_completa(db, familia.id)


@router.get("/mia", response_model=FamiliaOut)
async def mi_familia(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    return await _familia_completa(db, _exigir_familia(usuario))


@router.patch("/mia", response_model=FamiliaOut)
async def actualizar_familia(
    datos: FamiliaActualizar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _exigir_familia(usuario)
    familia = await db.get(Familia, familia_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(familia, campo, valor)
    await db.commit()
    return await _familia_completa(db, familia_id)


@router.post("/mia/salir", status_code=status.HTTP_204_NO_CONTENT)
async def salir_de_familia(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _exigir_familia(usuario)

    # Bloquea la fila de la familia: si los dos últimos adultos se salen al mismo
    # tiempo, el segundo espera al primero y sí detecta que es el último.
    await db.execute(select(Familia.id).where(Familia.id == familia_id).with_for_update())
    
    # Deja de ir a las actividades futuras de la familia que abandona
    await quitar_adulto_de_inscripciones_futuras(db, usuario.id, familia_id)
    await cancelar_inscripciones_vacias(db, familia_id)

    usuario.familia_id = None
    usuario.parentesco = None  # el parentesco era relativo a esa familia
    await db.flush()

    restantes = await db.scalar(select(func.count()).select_from(Usuario).where(Usuario.familia_id == familia_id))
    if restantes == 0:
        # ON DELETE CASCADE borra menores e invitaciones.
        await db.execute(delete(Familia).where(Familia.id == familia_id))

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- menores ----------
@router.post("/mia/menores", response_model=MenorOut, status_code=status.HTTP_201_CREATED)
async def agregar_menor(
    datos: MenorCrear,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _exigir_familia(usuario)
    menor = FamiliaMenor(familia_id=familia_id, registrado_por_id=usuario.id, **datos.model_dump())
    db.add(menor)
    await db.commit()
    await db.refresh(menor)
    return menor


@router.patch("/mia/menores/{menor_id}", response_model=MenorOut)
async def editar_menor(
    menor_id: uuid.UUID,
    datos: MenorActualizar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    menor = await _menor_de_mi_familia(db, usuario, menor_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if valor is not None:  # nombre y fecha son obligatorios, no se pueden borrar
            setattr(menor, campo, valor)
    await db.commit()
    await db.refresh(menor)
    return menor


@router.delete("/mia/menores/{menor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_menor(
    menor_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    menor = await _menor_de_mi_familia(db, usuario, menor_id)
    await db.delete(menor)
    await db.flush()  # CASCADE quita al menor de sus inscripciones
    await cancelar_inscripciones_vacias(db, menor.familia_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- invitaciones enviadas ----------
@router.post("/mia/invitaciones", response_model=InvitacionEnviadaOut, status_code=status.HTTP_201_CREATED)
async def invitar_adulto(
    datos: InvitacionCrear,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _exigir_familia(usuario)

    invitado = (
        await db.execute(select(Usuario).where(func.lower(Usuario.email) == datos.email.lower()))
    ).scalar_one_or_none()
    if invitado is None:
        raise HTTPException(status_code=404, detail="No existe una cuenta con ese correo")
    if invitado.id == usuario.id:
        raise HTTPException(status_code=400, detail="No puedes invitarte a ti mismo")
    if invitado.familia_id == familia_id:
        raise HTTPException(status_code=409, detail="Esa persona ya es parte de tu familia")
    if invitado.familia_id is not None:
        raise HTTPException(status_code=409, detail="Esa persona ya pertenece a otra familia")

    invitacion = InvitacionFamilia(familia_id=familia_id, invitado_id=invitado.id, invitado_por_id=usuario.id)
    db.add(invitacion)
    try:
        await db.commit()
    except IntegrityError:
        # uq_invitacion_pendiente: ya hay una pendiente para esta persona
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ya hay una invitación pendiente para esa persona")

    await db.refresh(invitacion, attribute_names=["invitado"])
    return invitacion


@router.delete("/mia/invitaciones/{invitacion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancelar_invitacion(
    invitacion_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _exigir_familia(usuario)
    invitacion = (
        await db.execute(
            select(InvitacionFamilia)
            .where(InvitacionFamilia.id == invitacion_id, InvitacionFamilia.familia_id == familia_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invitacion is None:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitacion.estado != EstadoInvitacion.PENDIENTE:
        raise HTTPException(status_code=409, detail="Esa invitación ya fue respondida")

    invitacion.estado = EstadoInvitacion.CANCELADA
    invitacion.respondida_en = func.now()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
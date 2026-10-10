from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers import actividades, auth, catalogo, centros, chat, donaciones, proyectos

app = FastAPI(title="Familias que Suman API")

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(catalogo.router)
app.include_router(actividades.router)
app.include_router(proyectos.router)
app.include_router(donaciones.router)
app.include_router(centros.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}  # SIN base de datos


@app.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))  # despierta a Neon
    return {"status": "ok"}
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers import auth, chat

app = FastAPI(title="Familias que Suman API")
app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}          # SIN base de datos


@app.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))   # despierta a Neon
    return {"status": "ok"}
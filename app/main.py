from fastapi import FastAPI

from app.routers import auth, chat

app = FastAPI(title="Familias que Suman API")

app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

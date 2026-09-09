# Familias que Suman — Backend (FastAPI)

Backend inicial: autenticación (registro/login con JWT) y chatbot conectado a la API de Gemini.

## Estructura

```
app/
  main.py           punto de entrada de FastAPI
  config.py         variables de entorno
  database.py       conexión async a Postgres (SQLAlchemy)
  models.py         tablas: Usuario, MensajeChat
  schemas.py        modelos Pydantic de entrada/salida
  security.py       hashing de password + JWT
  routers/
    auth.py         POST /auth/registro, POST /auth/login
    chat.py         POST /chat
alembic/            migraciones de base de datos
docker-compose.yml  levanta Postgres + la API
```

## Cómo arrancar

1. Copia `.env.example` a `.env` y llena `JWT_SECRET_KEY` y `GEMINI_API_KEY`.

   ```bash
   cp .env.example .env
   ```

2. Levanta Postgres y la API:

   ```bash
   docker compose up --build
   ```

3. En otra terminal, corre la primera migración (crea las tablas en Postgres):

   ```bash
   docker compose exec api alembic revision --autogenerate -m "tablas iniciales"
   docker compose exec api alembic upgrade head
   ```

4. Verifica que esté vivo: abre `http://localhost:8000/docs` — ahí ves y pruebas todos los endpoints (Swagger, autogenerado por FastAPI).

## Endpoints disponibles

- `POST /auth/registro` — crea usuario, regresa token
- `POST /auth/login` — regresa token
- `POST /chat` — requiere header `Authorization: Bearer <token>`, manda `{"mensaje": "..."}`, regresa la respuesta del asistente

## Próximos pasos sugeridos

- Agregar tabla y endpoints de `actividades` (para la pantalla de Actividades en Familia)
- Agregar tabla de `proyectos` y `donaciones` con su meta/progreso
- Conectar la app Android (Retrofit) a `http://10.0.2.2:8000` si usas el emulador, o la IP de tu máquina si usas un dispositivo físico

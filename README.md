# Familias que Suman — Backend (FastAPI)

Backend inicial: autenticación (registro/login con JWT) y chatbot conectado a la API de Gemini.

## Cómo arrancar

1. Copia `.env.example` a `.env` y llena las claves necesarias.

   ```bash
   cp .env.example .env
   ```

2. Levanta Postgres y la API:

   ```bash
   docker compose up -d --build
   ```

3. Verifica que esté vivo: abre `http://localhost:8000/docs` — ahí ves y pruebas todos los endpoints (Swagger, autogenerado por FastAPI).
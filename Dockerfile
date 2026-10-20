FROM python:3.12-slim

# Sin .pyc en el contenedor y logs sin buffer
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Usuario sin privilegios: si alguien llegara a ejecutar código en la API, no es root
RUN useradd --system --uid 10001 --no-create-home app

COPY --chown=app:app . .
RUN mkdir -p /code/media && chown app:app /code/media

USER app

EXPOSE 8000

# Docker (y Dokploy) marcan el contenedor como "unhealthy" si /health deja de responder
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# --proxy-headers: toma la IP real de X-Forwarded-For (Traefik/cloudflared) para el rate limit.
# Render define $PORT; en local cae a 8000.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

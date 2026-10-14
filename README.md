# Familias que Suman — Backend (FastAPI)

Backend inicial: autenticación (registro/login con JWT), endpoints de consumo para las distintas pantallas, monitoreo de contenedores y endpoints y chatbot conectado a la API de Gemini.

## Cómo arrancar

1. Copia `.env.example` a `.env` y llena las claves necesarias.

   ```bash
   cp .env.example .env
   ```

2. Levanta los servicios generales (Postgres, almacenamiento, API y túnel):

   ```bash
   docker compose up -d --build
   ```

3. Verifica que esté vivo: abre `http://localhost:8000/docs` — ahí ves y pruebas todos los endpoints (Swagger, autogenerado por FastAPI).

Para detener solo los servicios generales:

```bash
docker compose stop api cloudflared almacen db
```

## Monitoreo local

El monitoreo es opcional y corre con el perfil `monitoreo`. Antes de levantarlo,
define `GRAFANA_ADMIN_USER` y `GRAFANA_ADMIN_PASSWORD` en `.env` (puedes partir
de `.env.example`) y reconstruye la API para instalar `prometheus_client`:

```bash
docker compose up -d --build
docker compose --profile monitoreo up -d
```

El segundo comando también inicia los servicios generales si estaban detenidos.
Consulta el estado de todos los contenedores con:

```bash
docker compose --profile monitoreo ps
```

Puertos disponibles solo en la máquina local:

- Grafana: [http://localhost:3000](http://localhost:3000), con las credenciales del `.env`.
- Prometheus: [http://localhost:9090](http://localhost:9090); la consulta `up` muestra los targets.
- cAdvisor: [http://localhost:8081](http://localhost:8081).
- La API conserva su puerto local `8000`. Sus métricas se exponen en `api:9100`
   solo dentro de la red de Docker; no se publica en el host ni pasa por `cloudflared`.
- Las métricas de `cloudflared` están disponibles solo en Docker en el puerto `2000`.

Grafana provisiona el datasource Prometheus y cuatro dashboards al arrancar:

- **Resumen:** estado de targets, tráfico de la API y errores 5xx.
- **API:** tráfico y p95 por endpoint, llamadas/latencia de Gemini y eventos de auth.
- **Contenedores:** CPU, memoria y tráfico de red reportados por cAdvisor.
- **Base de datos:** CPU, memoria y red del contenedor Postgres, sin métricas internas de SQL.

También se provisionan alertas para targets caídos, tasa 5xx superior al 5%,
p95 de API superior a 1.5 s, fallos de Gemini y reinicios frecuentes. Prometheus
retiene 15 días de series. Los datos de Prometheus y Grafana persisten en volúmenes
con nombre.

Para detener solo los servicios de monitoreo y dejar la API corriendo:

```bash
docker compose --profile monitoreo stop prometheus grafana cadvisor
```

Para detener todos los servicios, incluidos los generales y los de monitoreo:

```bash
docker compose --profile monitoreo stop
```

`stop` conserva los contenedores y los volúmenes. Para volver a levantar todo el
stack, ejecuta `docker compose --profile monitoreo up -d --build`. No uses
`down -v` salvo que quieras borrar también los datos persistidos.
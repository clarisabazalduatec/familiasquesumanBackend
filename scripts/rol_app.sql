-- Rol de runtime para la API: puede leer y escribir datos, pero NO crear, alterar ni borrar tablas.
-- Las migraciones (Alembic) siguen usando el dueño, familias_user.
--
-- Ejecútalo UNA vez, como familias_user:
--   docker compose exec -T db psql -U familias_user -d familias_que_suman \
--     -v clave="'tu-clave-del-rol-app'" < scripts/rol_app.sql
-- Después pon esa clave en DATABASE_URL (usuario familias_app) y reinicia la API.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'familias_app') THEN
    CREATE ROLE familias_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;

ALTER ROLE familias_app WITH PASSWORD :clave;

GRANT CONNECT ON DATABASE familias_que_suman TO familias_app;
GRANT USAGE ON SCHEMA public TO familias_app;
REVOKE CREATE ON SCHEMA public FROM familias_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Tablas y secuencias que ya existen
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO familias_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO familias_app;
-- alembic_version es de Alembic: la API no tiene por qué tocarla
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM familias_app;

-- Tablas que creen migraciones futuras (las crea familias_user)
ALTER DEFAULT PRIVILEGES FOR ROLE familias_user IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO familias_app;
ALTER DEFAULT PRIVILEGES FOR ROLE familias_user IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO familias_app;

# Despliegue en producción con Docker (marcha blanca)

Servicios (`docker-compose.yml`):

| Servicio | Qué es | Expuesto |
|---|---|---|
| `backend` | API FastAPI + asistente IA (1 proceso) | puerto `BACKEND_PORT` (8000) → el proxy HTTPS |
| `ollama` | Modelo de IA `gemma4:e2b` en CPU | no (solo red interna) |
| `ollama-pull` | Descarga el modelo la primera vez y termina | no |

La **base de datos no va en Docker**: es la de producción existente (`DATABASE_URL`).

## Requisitos del servidor

- Docker y Docker Compose.
- **RAM ≥ 12 GB** (el modelo ocupa ~7 GB) y ~10 GB de disco libre para el modelo.
- Acceso del servidor a PostgreSQL y salida a `smtp.gmail.com:587` (correo de verificación).

## Primer despliegue

1. **Respaldo de la BD**: `pg_dump -Fc -f appalta2_antes.dump appalta2`
2. **Migración del DNI único** (una sola vez):
   ```sql
   -- debe devolver 0 filas; si no, resolver los DNI repetidos antes de seguir
   SELECT document_of_identity, count(*) FROM users GROUP BY 1 HAVING count(*) > 1;
   ```
   Luego ejecutar `sql/006_users_unique_dni.sql`.
3. **Configuración**: `cp .env.production.example .env.production` y completar:
   - `DATABASE_URL` de producción (si PostgreSQL está en el mismo servidor: host `host.docker.internal`).
   - `BACKEND_URL=https://proyectos-didt.inictel-uni.edu.pe/api/palta` (los enlaces del correo usan esta URL).
   - `MAIL_*`: cuenta de Gmail con **contraseña de aplicación** (16 caracteres;
     Cuenta de Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones).
4. **Levantar**:
   ```bash
   docker compose --env-file .env.production up -d --build
   docker compose logs -f ollama-pull     # la primera vez descarga ~7 GB; termina con "success"
   ```
5. **Verificar**:
   ```bash
   curl http://localhost:8000/api/v1/                    # {"status":"running"}
   curl http://localhost:8000/api/v1/assistant/health    # {"database":true,"model":true}
   docker compose exec backend python -m scripts.assistant.run_eval   # debe ser ≥ 95 %
   ```
6. **Probar el correo**: registrar un usuario de prueba desde la app, abrir el enlace del correo
   e iniciar sesión (sin verificar, el login responde "Correo no verificado").

## Actualizar

```bash
git pull
docker compose --env-file .env.production up -d --build backend
```

Las conversaciones del chat en curso se reinician al actualizar (la memoria vive en el proceso).

## Operación

- Logs: `docker compose logs -f backend` (rotan a 5 × 20 MB).
- Estado: `docker compose ps` (el backend tiene healthcheck).
- **No aumentar `--workers`**: la memoria del chat es por proceso; para varios procesos o
  réplicas hay que implementar `ConversationStore` sobre Redis.
- Evaluación mensual del asistente: `docker compose exec backend python -m scripts.assistant.run_eval`.

## Volver atrás

```bash
git checkout <versión anterior> && docker compose --env-file .env.production up -d --build backend
```

La migración del DNI no necesita revertirse (versiones anteriores funcionan con ella). Si hiciera falta:
`ALTER TABLE users DROP CONSTRAINT users_document_of_identity_key;`

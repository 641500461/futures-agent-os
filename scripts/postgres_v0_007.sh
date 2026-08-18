#!/usr/bin/env bash
set -euo pipefail

# Pinned, disposable PostgreSQL for V0-007; it never starts a donor database.
container_name="fao-postgres-v0-007"
host_port="${FAO_POSTGRES_PORT:-54329}"
database_url="postgresql+psycopg://postgres@127.0.0.1:${host_port}/futures_agent_os"

case "${1:-}" in
  start)
    docker rm -f "$container_name" >/dev/null 2>&1 || true
    docker run --detach --name "$container_name" --publish "127.0.0.1:${host_port}:5432" \
      --env POSTGRES_DB=futures_agent_os --env POSTGRES_HOST_AUTH_METHOD=trust \
      --health-cmd='pg_isready -U postgres -d futures_agent_os' \
      --health-interval=2s --health-timeout=3s --health-retries=30 postgres:17.5-alpine >/dev/null
    until [ "$(docker inspect --format='{{.State.Health.Status}}' "$container_name")" = "healthy" ]; do sleep 1; done
    printf 'FAO_DATABASE_URL=%s\n' "$database_url"
    ;;
  stop) docker rm -f "$container_name" ;;
  migrate) FAO_DATABASE_URL="$database_url" uv run alembic upgrade head ;;
  exercise)
    FAO_DATABASE_URL="$database_url" uv run alembic upgrade head
    FAO_DATABASE_URL="$database_url" uv run alembic downgrade base
    FAO_DATABASE_URL="$database_url" uv run alembic upgrade head
    FAO_DATABASE_URL="$database_url" uv run pytest tests/integration -q
    ;;
  *) printf 'Usage: %s {start|stop|migrate|exercise}\n' "$0" >&2; exit 64 ;;
esac

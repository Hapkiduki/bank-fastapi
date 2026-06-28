# Bankito

Backend for a banking system built with **FastAPI** and **SQLModel**, served
locally behind **Traefik**, with **PostgreSQL** and **Mailpit**. Dependencies are
managed with [`uv`](https://docs.astral.sh/uv/).

> This Compose stack is for **local development only**. The Traefik dashboard and
> the insecure API are enabled for convenience and must never be used in
> staging or production.

## Prerequisites

- Docker Engine + Docker Compose v2 (`docker compose`)
- The Compose stack uses an **external** Docker network, so create it once first.

## 1. Create the Docker network

The `bankito_local_nw` network is declared as `external` so it can be shared
across stacks. Create it before the first run:

```bash
docker network create bankito_local_nw

# Verify it exists
docker network ls | grep bankito_local_nw
```

If it already exists, Docker prints an error you can safely ignore.

## 2. Configure environment variables

Copy the example file and fill in the values (Postgres user/password/db, etc.):

```bash
cp .envs/.env.example .envs/.env.local
```

`DATABASE_URL` is set for **in-container** use — host `postgres`, internal port
`5432`. External tools connect on `localhost:5433` (see below).

## 3. Build and run

```bash
docker compose -f local.yml up --build -d --remove-orphans
```

This starts:

| Service  | URL / Port                         | Purpose                            |
| -------- | ---------------------------------- | ---------------------------------- |
| API      | http://api.localhost (via Traefik) | FastAPI app                        |
| API      | http://localhost:8000              | Direct access (bypasses Traefik)   |
| Docs     | http://api.localhost/api/v1/docs   | Swagger UI                         |
| Health   | http://api.localhost/health        | Liveness probe (`{"status":"ok"}`) |
| Traefik  | http://localhost:8080              | Traefik dashboard                  |
| Mailpit  | http://localhost:8025              | Captured outgoing email            |
| Postgres | localhost:5433                     | DB for external clients            |

Run detached with `-d`, and follow logs with
`docker compose -f local.yml logs -f api`.

## Connecting an external database client

The Postgres container listens on `5432` internally and is published on host
port `5433` to avoid clashing with a local Postgres install. From your host
(psql, DBeaver, etc.):

```
host=localhost  port=5433  user=$POSTGRES_USER  password=$POSTGRES_PASSWORD  db=$POSTGRES_DB
```

## Migrations

The container entrypoint runs `alembic upgrade head` automatically **only if**
an `alembic.ini` is present. Until Alembic is initialised, migrations are
skipped (logged to stderr) and the app boots normally.

## Tear down

```bash
# Stop and remove containers (keeps volumes)
docker compose -f local.yml down

# Also remove named volumes (DB + Mailpit data)
docker compose -f local.yml down -v
```

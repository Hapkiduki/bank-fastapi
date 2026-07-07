# Bankito — Banking API

A production-grade banking backend built with **FastAPI** and **SQLModel** (async
SQLAlchemy + PostgreSQL), featuring two-factor authentication, atomic money
movement with row-level locking, idempotent transfers, distributed rate limiting,
asynchronous background processing with **Celery**, and an **ML fraud-detection
pipeline** (gradient boosting, tracked and deployed through **MLflow**).

## Features

- **Authentication** — registration with email activation, two-step login
  (password + emailed OTP), short-lived JWT access token + refresh token in
  `HttpOnly` cookies, account lockout after repeated failures, Argon2 hashing
  for passwords _and_ security answers, role-based access (customer, teller,
  account executive, branch manager, admin).
- **Accounts & KYC** — profile + next-of-kin requirements, executive-verified
  KYC activation, up to 3 accounts per user, multi-currency (USD/EUR/GBP/KES)
  with Luhn-checked account numbers.
- **Money movement** — teller deposits, two-step OTP-verified transfers with
  currency conversion, cash withdrawals, virtual-card top-ups. Every balance
  mutation uses `SELECT ... FOR UPDATE` with deterministic lock ordering,
  re-validates under the lock and commits atomically. All money is `Decimal` /
  `NUMERIC` — never floats.
- **Idempotency** — transfers, withdrawals and top-ups accept an
  `Idempotency-Key` header (UUID v4); replays return the cached response.
- **Fraud detection** — every transfer/withdrawal is scored by the deployed ML
  model _before_ any balance changes; flagged transactions are held for human
  review by an account executive. Model inference runs behind a circuit
  breaker with a fail-closed fallback. Celery beat retrains, evaluates and
  auto-deploys models on a schedule, all tracked in MLflow.
- **Operations** — Redis-backed per-endpoint rate limiting with violation
  auditing, aggregated `/health` endpoint consumed by Traefik's load-balancer
  healthcheck, structured logging (Loguru), PDF statements generated
  asynchronously, transactional emails for every sensitive event.

## Architecture

The codebase is organized as **vertical slices**: each feature owns its models,
schemas, business logic and HTTP routes. `api/main.py` is only a composition
root, and `core/` holds cross-cutting infrastructure.

```
backend/app/
├── auth/            # registration, activation, OTP login, JWT, dependencies
├── user_profile/    # KYC profile data, photo uploads (Cloudinary)
├── next_of_kin/     # next-of-kin records (KYC requirement)
├── bank_account/    # account lifecycle: creation, KYC activation
├── transaction/     # deposits, transfers, withdrawals, statements,
│                    # history, fraud review
├── virtual_card/    # card issuing, activation, block, top-up
├── api/             # composition root (aggregated feature routers)
└── core/            # config, db, exceptions, resilience (circuit breaker),
                     # rate limiting, health checks, celery, emails, ai/ml
```

Models are **auto-discovered**: `core/model_registry.py` imports every
`models.py` under `backend/app/`, so both the app and Alembic's autogenerate
see new tables without any manual registration. Celery tasks are auto-discovered
the same way.

### Runtime topology

```
                    ┌─ Traefik (round-robin LB, /health checks)
 client ──────────► │
                    └─► FastAPI (uvicorn) ──► PostgreSQL 16
                          │   │
                          │   └─► Redis (rate limits, results, statements)
                          └─► RabbitMQ ──► Celery worker / beat ──► MLflow
                                                 └─► Mailpit (local SMTP)
```

## Getting started (local)

### Prerequisites

- Docker Engine + Docker Compose v2 (`docker compose`)

### 1. Create the external Docker network (once)

```bash
docker network create bankito_local_nw
```

### 2. Configure environment variables

```bash
cp .envs/.env.example .envs/.env.local
```

Fill in at minimum:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `JWT_SECRET_KEY` and `SIGNING_KEY` — **required**; the app refuses to start
  without them. Generate each with `openssl rand -hex 32`.
- `ENVIRONMENT="local"` (enables dev-friendly cookie/OTP settings)

`DATABASE_URL` is set for in-container use (host `postgres`, port `5432`);
external DB clients connect to `localhost:5433`.

### 3. Build and run

```bash
make build          # docker compose -f local.yml up --build -d --remove-orphans
```

Database migrations run automatically on startup (`alembic upgrade head` in the
container entrypoint).

| Service  | URL / Port                         | Purpose                          |
| -------- | ---------------------------------- | -------------------------------- |
| API      | http://api.localhost (via Traefik) | FastAPI app                      |
| API      | http://localhost:8000              | Direct access (bypasses Traefik) |
| Docs     | http://localhost:8000/api/v1/docs  | Swagger UI                       |
| Health   | http://localhost:8000/health       | Aggregated service health        |
| Traefik  | http://localhost:8080              | Traefik dashboard                |
| Mailpit  | http://localhost:8025              | Captured outgoing email          |
| RabbitMQ | http://localhost:15672             | Broker management UI             |
| Flower   | http://localhost:5555              | Celery monitoring                |
| MLflow   | http://localhost:4000              | Model registry & experiments     |
| Postgres | localhost:5433                     | DB for external clients          |

### 4. Seed test data (optional)

```bash
docker compose -f local.yml exec api python -m backend.app.core.management.commands.seed_db
```

Creates 20 users (admin, account executive, teller + customers; password
`password123`, security answer `test answer`), active bank accounts and ~1000
transactions (including labeled fraud) for training the ML model.

### 5. Try the API

Interactive docs live at `/api/v1/docs`. A typical happy path:

1. `POST /api/v1/auth/register` → check Mailpit for the activation link.
2. `GET /api/v1/auth/activate/{token}`.
3. `POST /api/v1/auth/login/request-otp` → OTP arrives in Mailpit.
4. `POST /api/v1/auth/login/verify-otp` → auth cookies are set.
5. Create profile + next of kin → create a bank account → executive activates it.
6. Move money: deposits (teller), transfers (OTP + `Idempotency-Key` header),
   withdrawals, card top-ups.

For Postman, [postman-prescript.js](postman-prescript.js) auto-generates the
`Idempotency-Key` header on every request.

## Day-to-day commands

```bash
make build              # build & start the stack
make up / make down     # start / stop
make down-v             # stop and delete volumes (DB reset)
make makemigrations name="add_x_table"   # autogenerate an Alembic revision
make migrate            # apply migrations
make current-migration  # show current revision
make psql               # psql shell into the database
uvx ruff check .        # lint
```

## Environment & configuration

Configuration lives in `backend/app/core/config.py` (pydantic-settings).
Resolution order: real environment variables → `.envs/.env.local` →
`.envs/.env.production` → code defaults. `ENVIRONMENT` defaults to
`production` on purpose (secure by default); environment-dependent values
(OTP/token lifetimes, cookie `Secure` flag, lockout duration) are computed at
runtime from it.

## Production

`production.yml` runs the same topology hardened for a server: Traefik
terminates TLS (Let's Encrypt), the API runs `uvicorn --workers 4` behind it,
and Postgres/Redis/RabbitMQ persist to named volumes. Deploy with:

```bash
export DIGITAL_OCEAN_IP_ADDRESS=x.x.x.x
./deploy.sh   # git archive → rsync → docker compose -f production.yml up --build -d
```

Secrets come from `.envs/.env.production` on the server (never committed).

## Documentation

- [explanation.md](explanation.md) — transaction risk analysis model
- [ml-pipeline.md](ml-pipeline.md) — fraud-detection ML workflow
- [gradient-boosting.md](gradient-boosting.md) — why gradient boosting
- [how_it_works.md](how_it_works.md) — ML pipeline architecture summary

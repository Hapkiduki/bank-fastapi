# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13.1

# Shared base: Python + the uv binary
FROM python:${PYTHON_VERSION}-slim-bookworm AS python-base

# Pin uv via its official image; copy just the static binaries
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ARG APP_HOME=/src

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="${APP_HOME}/.venv/bin:$PATH"

# Stage 1: resolve and install dependencies into a project venv
FROM python-base AS python-build-stage

WORKDIR ${APP_HOME}

# Install dependencies first (without the project) for a cache-friendly layer.
# Our deps ship as wheels (psycopg[binary], asyncpg, argon2-cffi, greenlet),
# so no build-essential / libpq-dev toolchain is required.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Install the project itself (editable, so the runtime bind-mount keeps reload).
COPY . ${APP_HOME}
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Stage 2: runtime
FROM python-base AS python-run-stage

ARG APP_HOME=/src
ARG APP_USER=fastapi
ARG APP_GROUP=fastapi

WORKDIR ${APP_HOME}

RUN groupadd -r ${APP_GROUP} && \
    useradd -r -g ${APP_GROUP} -d ${APP_HOME} -m ${APP_USER}

# Bring in the fully built application (code + .venv) from the build stage.
COPY --from=python-build-stage --chown=${APP_USER}:${APP_GROUP} ${APP_HOME} ${APP_HOME}

RUN mkdir -p ${APP_HOME}/backend/app/logs && \
    chown -R ${APP_USER}:${APP_GROUP} ${APP_HOME}/backend/app/logs && \
    chmod 775 ${APP_HOME}/backend/app/logs

COPY --chown=${APP_USER}:${APP_GROUP} ./backend/docker/local/fastapi/entrypoint.sh /entrypoint.sh
COPY --chown=${APP_USER}:${APP_GROUP} ./backend/docker/local/fastapi/start.sh /start.sh
COPY --chown=${APP_USER}:${APP_GROUP} ./backend/docker/local/fastapi/celery/worker/start.sh /start-celeryworker.sh
COPY --chown=${APP_USER}:${APP_GROUP} ./backend/docker/local/fastapi/celery/beat/start.sh /start-celerybeat.sh
COPY --chown=${APP_USER}:${APP_GROUP} ./backend/docker/local/fastapi/celery/flower/start.sh /start-flower.sh

RUN sed -i 's/\r$//g' /entrypoint.sh /start.sh /start-celeryworker.sh /start-celerybeat.sh /start-flower.sh && \
    chmod +x /entrypoint.sh /start.sh /start-celeryworker.sh /start-celerybeat.sh /start-flower.sh

USER ${APP_USER}

ENTRYPOINT ["/entrypoint.sh"]

#!/bin/bash

set -o errexit

set -o nounset

set -o pipefail

# Database readiness is handled by the postgres healthcheck +
# `depends_on: condition: service_healthy` in local.yml, so no wait loop here.

# Apply migrations only once Alembic is fully initialised (config + a
# migrations/ scripts folder). Without the folder `alembic upgrade` aborts,
# which would kill every service that shares this entrypoint.
if [ -f alembic.ini ] && [ -d migrations ]; then
  alembic upgrade head
else
  echo >&2 'Alembic not initialised (missing alembic.ini or migrations/), skipping migrations.'
fi

exec "$@"

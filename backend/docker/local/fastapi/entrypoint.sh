#!/bin/bash

set -o errexit

set -o nounset

set -o pipefail

# Database readiness is handled by the postgres healthcheck +
# `depends_on: condition: service_healthy` in local.yml, so no wait loop here.

# Apply migrations only once Alembic has been initialised in the repo.
if [ -f alembic.ini ]; then
  alembic upgrade head
else
  echo >&2 'No alembic.ini found, skipping migrations.'
fi

exec "$@"

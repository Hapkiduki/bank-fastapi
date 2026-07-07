#!/bin/bash

set -o errexit

set -o nounset

set -o pipefail


echo "Running database migrations..."
if alembic current 2>/dev/null; then
  echo "Alembic already initialized, running upgrade only"
  alembic upgrade head
else
  echo "Initializing Alembic and running migrations"
  alembic revision --autogenerate -m "Initial migration"
  alembic upgrade head
fi

>&2 echo 'Migrations applied'

exec "$@"
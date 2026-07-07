#!/bin/bash

set -o errexit

set -o nounset

set -o pipefail

python -c "from backend.app.core.ml.cleanup import cleanup_mlflow_runs; cleanup_mlflow_runs()"

exec celery \
  -A backend.app.core.celery_app \
  worker \
  -Q bankito_tasks,ml_tasks \
  -l INFO

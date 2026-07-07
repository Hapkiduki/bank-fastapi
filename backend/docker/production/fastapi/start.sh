#!/bin/bash

set -o errexit

set -o nounset

set -o pipefail

exec uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --log-level info

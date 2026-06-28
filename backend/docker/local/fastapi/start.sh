#!/bin/bash

set -o errexit

set -o nounset

set -o pipefail

# Development server with autoreload.
# We invoke uvicorn directly rather than the `fastapi` CLI: inside a bind-mounted
# dev container the CLI reads pyproject.toml over the mount and can hit
# "OSError: [Errno 35] Resource deadlock avoided". uvicorn avoids that read.
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

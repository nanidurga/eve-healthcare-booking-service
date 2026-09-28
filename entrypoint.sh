#!/bin/sh
# Apply migrations before serving. The database is already healthy by the time
# this runs: compose gates startup on the Postgres healthcheck.
set -e

echo "Applying database migrations..."
alembic upgrade head

if [ "${SEED_ON_START:-false}" = "true" ]; then
    echo "Seeding demo data..."
    python -m scripts.seed
fi

exec "$@"

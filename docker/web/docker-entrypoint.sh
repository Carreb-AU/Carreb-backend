#!/bin/sh
set -e

echo "Waiting for postgres..."

timeout=30
count=0

while ! nc -z db 5432; do
  sleep 1
  count=$((count+1))

  if [ "$count" -ge "$timeout" ]; then
    echo "Postgres not available after 30 seconds"
    exit 1
  fi
done

echo "PostgreSQL started"

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting server..."
exec "$@"

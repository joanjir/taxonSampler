#!/bin/bash
set -e

# 1. Start Redis in background
echo "Starting Redis..."
redis-server --daemonize yes --maxmemory 128mb --maxmemory-policy allkeys-lru
echo "Redis started."

# 2. Run migrations
python manage.py migrate --noinput

# 3. Start Celery worker in background
echo "Starting Celery worker..."
celery -A config worker -l info --pool=solo -Q default,ncbi_sync &
CELERY_PID=$!
echo "Celery worker started (PID $CELERY_PID)."

# Graceful shutdown: stop Celery on SIGTERM/SIGINT
trap "echo 'Shutting down...'; kill $CELERY_PID 2>/dev/null; redis-cli shutdown nosave 2>/dev/null; exit 0" SIGTERM SIGINT

# 4. Start gunicorn (foreground)
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile -

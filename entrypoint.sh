#!/bin/bash
set -e

# Run migrations
python manage.py migrate --noinput

# Start gunicorn
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile -

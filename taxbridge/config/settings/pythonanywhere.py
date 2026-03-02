"""
Django settings for PythonAnywhere (free tier).

Key differences from local/prod:
  - SQLite instead of PostgreSQL (free tier has no PostgreSQL)
  - Celery disabled (no Redis on free tier)
  - Static files served via PythonAnywhere's static-file mappings
  - ALLOWED_HOSTS set for *.pythonanywhere.com
"""
from .base import *  # noqa
import os

# ── Core ──
DEBUG = False
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "change-me-on-pythonanywhere-set-in-env",
)

ALLOWED_HOSTS = [
    "joanji.pythonanywhere.com",
]

CSRF_TRUSTED_ORIGINS = [
    "https://joanji.pythonanywhere.com",
]

# ── Database: SQLite (free tier) ──
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ── Static files ──
# collectstatic places files here; PythonAnywhere serves them directly
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── Security ──
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# ── Celery: disabled on free tier (no Redis) ──
CELERY_TASK_ALWAYS_EAGER = True          # Tasks execute synchronously
CELERY_TASK_EAGER_PROPAGATES = True      # Raise exceptions immediately
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# ── Logging ──
LOG_LEVEL = os.environ.get("LOG_LEVEL", "WARNING")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}

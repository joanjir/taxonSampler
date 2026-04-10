from .prod import *  # noqa

# WhiteNoise for static files (after SecurityMiddleware)
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Neon pooler doesn't set search_path — force it to 'public'
DATABASES["default"]["OPTIONS"] = {
    "options": "-c search_path=public",
}

# Redis runs in the same container (started by entrypoint.sh)
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "taxonsampler",
        "TIMEOUT": 600,
    }
}

# Celery — real async processing with local Redis
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

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

# In-process cache (no Redis dependency)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "KEY_PREFIX": "taxonsampler",
        "TIMEOUT": 600,
    }
}

# Celery disabled on Fly.io (no workers running)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

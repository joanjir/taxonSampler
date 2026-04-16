from .prod import *  # noqa

# SSL is terminated externally (before Nginx); Django must not redirect.
SECURE_SSL_REDIRECT = False

# Static files — served directly by Nginx
STATIC_ROOT = BASE_DIR / "staticfiles"

# Cache — use local memory until Valkey/Redis is installed
# Switch to RedisCache once Valkey is running on port 6379
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "KEY_PREFIX": "taxonsampler",
        "TIMEOUT": 600,
    }
}

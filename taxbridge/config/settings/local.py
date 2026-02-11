from .base import *  # noqa
DEBUG = True

# Celery / Redis configuration
USE_CELERY_FOR_SYNC = True
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

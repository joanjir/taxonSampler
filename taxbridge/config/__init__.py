# config/__init__.py
"""
This module loads Celery when Django starts (if installed).
"""
try:
    from .celery import app as celery_app
    __all__ = ("celery_app",)
except ImportError:
    # Celery not installed - continue without it
    celery_app = None
    __all__ = ()

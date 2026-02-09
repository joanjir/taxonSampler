# config/__init__.py
"""
Este módulo carga Celery cuando Django inicia (si está instalado).
"""
try:
    from .celery import app as celery_app
    __all__ = ("celery_app",)
except ImportError:
    # Celery no instalado - continuar sin él
    celery_app = None
    __all__ = ()

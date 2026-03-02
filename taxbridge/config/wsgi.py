import os
import sys

# Auto-detect PythonAnywhere
if "PYTHONANYWHERE_SITE" in os.environ or "/home/joanji" in os.path.abspath(__file__):
    # Ensure project dir is in sys.path
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.pythonanywhere")
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()

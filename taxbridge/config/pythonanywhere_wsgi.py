"""
PythonAnywhere WSGI configuration.

Copy the contents of this file into:
  /var/www/joanji_pythonanywhere_com_wsgi.py

Or paste it in the PythonAnywhere Web tab → WSGI configuration file link.
"""
import os
import sys

# ── Project path ──
PROJECT_DIR = "/home/joanji/taxonSampler/taxbridge"
sys.path.insert(0, PROJECT_DIR)

# ── Virtualenv (if used) ──
# PythonAnywhere sets this automatically from the Web tab,
# but we add an explicit fallback just in case.
VENV = "/home/joanji/.virtualenvs/taxonsampler"
venv_path = os.path.join(VENV, "lib", "python3.10", "site-packages")
if os.path.isdir(venv_path):
    sys.path.insert(0, venv_path)

# ── Django settings ──
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.pythonanywhere")

# You can set environment variables here for secrets:
# os.environ["DJANGO_SECRET_KEY"] = "your-long-random-key"
# os.environ["NCBI_API_KEY"] = "your-ncbi-key"

from django.core.wsgi import get_wsgi_application  # noqa: E402
application = get_wsgi_application()

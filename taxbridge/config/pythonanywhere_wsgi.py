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

# ── Virtualenv ──
VENV = "/home/joanji/envs/taxbridge13"
venv_path = os.path.join(VENV, "lib", "python3.13", "site-packages")
if os.path.isdir(venv_path):
    sys.path.insert(0, venv_path)

# ── Load .env file ──
env_file = os.path.join(PROJECT_DIR, ".env")
if os.path.isfile(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# ── Django settings ──
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.pythonanywhere")

from django.core.wsgi import get_wsgi_application  # noqa: E402
application = get_wsgi_application()

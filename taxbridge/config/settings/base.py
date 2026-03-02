from pathlib import Path
import environ

# ======================
# Paths
# ======================
BASE_DIR = Path(__file__).resolve().parents[2]

# ======================
# Environment
# ======================
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    LOG_LEVEL=(str, "INFO"),
)

ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    environ.Env.read_env(str(ENV_FILE))

DJANGO_ENV = env("DJANGO_ENV", default="local")

# ======================
# Core Django
# ======================
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")

ALLOWED_HOSTS = [
    h.strip() for h in env("DJANGO_ALLOWED_HOSTS", default="").split(",") if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", default="").split(",") if o.strip()
]

# ======================
# Applications
# ======================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 'fontawesomefree',  # TODO: Enable Long Paths on Windows to install
    "rest_framework",
    # Local apps
    "apps.taxonomy",
]

# Celery apps (añadir si están instalados)
try:
    import django_celery_results
    INSTALLED_APPS.append("django_celery_results")
except ImportError:
    pass

try:
    import django_celery_beat
    INSTALLED_APPS.append("django_celery_beat")
except ImportError:
    pass

# ======================
# Middleware
# ======================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ======================
# URLs / WSGI / ASGI
# ======================
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ======================
# Templates
# ======================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.taxonomy.context_processors.user_role",
            ],
        },
    },
]

# ======================
# Database (PostgreSQL)
# ======================
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3")
}

# ======================
# Password validation
# ======================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ======================
# Internationalization
# ======================
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

# ======================
# Static files
# ======================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ======================
# Authentication
# ======================
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/taxonomy/"
LOGOUT_REDIRECT_URL = "/taxonomy/"

# ======================
# External APIs (centralizado)
# ======================
NCBI_API_KEY = env("NCBI_API_KEY", default="")
NCBI_USER_AGENT = env("NCBI_USER_AGENT", default="taxbridge/0.1")
COL_DATASET_KEY = env.int("COL_DATASET_KEY", default=3)

# ======================
# Logging
# ======================
LOG_LEVEL = env("LOG_LEVEL")
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

# ======================
# Celery Configuration
# ======================
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60  # 1 hora máximo por tarea

# Cola por defecto
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = {
    "default": {},
    "ncbi_sync": {},  # Dedicated queue for NCBI sync
}

# ======================
# NCBI Sync Settings
# ======================
NCBI_API_KEY = env("NCBI_API_KEY", default="")
NCBI_SYNC_BATCH_SIZE = env.int("NCBI_SYNC_BATCH_SIZE", default=100)
NCBI_SYNC_CHECK_PROTEOMES = env.bool("NCBI_SYNC_CHECK_PROTEOMES", default=False)
NCBI_SYNC_MAX_RETRIES = env.int("NCBI_SYNC_MAX_RETRIES", default=3)

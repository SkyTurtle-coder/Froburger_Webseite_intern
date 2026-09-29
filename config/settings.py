import os
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_str(*names, default=None, required=False):
    for name in names:
        raw = os.getenv(name)
        if raw is not None:
            value = raw.strip()
            if value:
                return value
    if required:
        joined = ", ".join(names)
        raise ImproperlyConfigured(f"Missing required environment variable: {joined}")
    return default


def env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def env_int(name, default=0):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def env_list(*names, default=""):
    raw = env_str(*names, default=default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_path(*names, default):
    raw = env_str(*names, default=None)
    if raw is None:
        return Path(default)
    return Path(raw).expanduser()


def static_asset_version():
    explicit = env_str("STATIC_ASSET_VERSION", default="")
    if explicit:
        return explicit

    candidate_files = (
        BASE_DIR / "static" / "css" / "app.css",
        BASE_DIR / "static" / "css" / "navigation.css",
        BASE_DIR / "static" / "js" / "app.js",
    )
    mtimes = [int(path.stat().st_mtime) for path in candidate_files if path.exists()]
    return str(max(mtimes)) if mtimes else "1"


# SEC-015: reject known placeholders from every template shipped in this repo
# (.env.example, .env.production.example, deploy/*.example), Django's own
# "django-insecure-..." startproject prefix, and anything implausibly short
# to be a real generated key - while staying out of the way of any real
# secret a deployer actually generates (e.g. get_random_secret_key(), 50 chars).
SECRET_KEY_PLACEHOLDERS = {
    "change-me",
    "django-insecure-change-me",
    "replace-with-strong-secret",
    "replace-with-local-secret",
}
SECRET_KEY_MIN_LENGTH = 20


def is_secret_key_acceptable(value):
    if not value:
        return False
    if value in SECRET_KEY_PLACEHOLDERS:
        return False
    if value.startswith("django-insecure-"):
        return False
    if len(value) < SECRET_KEY_MIN_LENGTH:
        return False
    return True


SECRET_KEY = env_str("DJANGO_SECRET_KEY", required=True)
if not is_secret_key_acceptable(SECRET_KEY):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a real, non-placeholder value of at "
        "least 20 characters (e.g. via django.core.management.utils."
        "get_random_secret_key())."
    )

# SEC-003: fail safe. If DJANGO_DEBUG is ever missing from the environment
# (e.g. an incomplete systemd EnvironmentFile), the app must come up in
# production mode, not with tracebacks/settings visible to every visitor.
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8000,http://127.0.0.1:8000",
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    "events",
    "documents",
    "forum",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.ContentSecurityPolicyReportOnlyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.app_meta",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

database_name = env_str("DB_NAME", "DJANGO_DB_NAME")
database_user = env_str("DB_USER", "DJANGO_DB_USER", default="")
database_password = env_str("DB_PASSWORD", "DJANGO_DB_PASSWORD", default="")
database_host = env_str("DB_HOST", "DJANGO_DB_HOST", default="")
database_port = env_str("DB_PORT", "DJANGO_DB_PORT", default="")
database_engine = env_str("DB_ENGINE", "DJANGO_DB_ENGINE")
if not database_engine:
    if any([database_user, database_password, database_host, database_port]):
        database_engine = "django.db.backends.mysql"
    else:
        database_engine = "django.db.backends.sqlite3"

database_config = {
    "ENGINE": database_engine,
    "NAME": database_name or str(BASE_DIR / "db.sqlite3"),
}
if database_engine == "django.db.backends.sqlite3":
    sqlite_name = Path(database_config["NAME"])
    if not sqlite_name.is_absolute():
        database_config["NAME"] = str((BASE_DIR / sqlite_name).resolve())
if database_engine != "django.db.backends.sqlite3":
    database_config.update(
        {
            "USER": database_user,
            "PASSWORD": database_password,
            "HOST": database_host,
            "PORT": database_port,
        }
    )
    if not database_name:
        raise ImproperlyConfigured("DB_NAME or DJANGO_DB_NAME must be set for non-SQLite databases.")

DATABASES = {"default": database_config}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de-ch"
TIME_ZONE = "Europe/Zurich"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = env_path("STATIC_ROOT", default=BASE_DIR / "staticfiles")
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STATIC_ASSET_VERSION = static_asset_version()

MEDIA_URL = "/media/"
MEDIA_ROOT = env_path("MEDIA_ROOT", default=BASE_DIR / "media")

# SEC-008: an internal portal holding private documents/obituaries shouldn't
# default to Django's 2-week rolling session with no idle timeout. 8 hours
# (one working day) with SESSION_SAVE_EVERY_REQUEST=True gives a sliding idle
# timeout (extends while the member is active, expires 8h after the last
# request) rather than a hard cutoff mid-session. Configurable in case this
# turns out to be too short/long in practice.
SESSION_COOKIE_AGE = env_int("DJANGO_SESSION_COOKIE_AGE", 8 * 60 * 60)
SESSION_SAVE_EVERY_REQUEST = True
PASSWORD_RESET_TIMEOUT = env_int("PASSWORD_RESET_TIMEOUT", 7200)

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
AUTHENTICATION_BACKENDS = [
    "accounts.auth_backends.EmailOrVulgoBackend",
    "django.contrib.auth.backends.ModelBackend",
]
EMAIL_BACKEND = env_str(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.console.EmailBackend"
        if DEBUG
        else "django.core.mail.backends.smtp.EmailBackend"
    ),
)
EMAIL_HOST = env_str("EMAIL_HOST", default="")
EMAIL_PORT = env_int("EMAIL_PORT", 25)
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env_str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = env_str(
    "DEFAULT_FROM_EMAIL",
    default="AV Froburger Intern <noreply@localhost>",
)

PUBLIC_EVENT_SOURCE_BASE_URL = os.getenv("PUBLIC_EVENT_SOURCE_BASE_URL", "").rstrip("/")
PUBLIC_EVENT_DETAIL_PATH_PREFIX = os.getenv("PUBLIC_EVENT_DETAIL_PATH_PREFIX", "/anlaesse").strip() or "/anlaesse"
PUBLIC_WEBSITE_PRIMARY_URL = env_str(
    "PUBLIC_WEBSITE_PRIMARY_URL",
    "PUBLIC_WEBSITE_URL",
    default="https://test.avfroburger.ch/",
)
PUBLIC_WEBSITE_FALLBACK_URL = env_str(
    "PUBLIC_WEBSITE_FALLBACK_URL",
    "PUBLIC_WORDPRESS_SITE_URL",
    default="https://avfroburger.ch/",
)
PUBLIC_WORDPRESS_SITE_URL = PUBLIC_WEBSITE_FALLBACK_URL.rstrip("/")
PUBLIC_MEDIA_BASE_URL = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip()
PUBLIC_EVENT_SIGNUP_SHARED_SECRET = os.getenv("PUBLIC_EVENT_SIGNUP_SHARED_SECRET", "").strip()
if not PUBLIC_MEDIA_BASE_URL and PUBLIC_EVENT_SOURCE_BASE_URL:
    PUBLIC_MEDIA_BASE_URL = f"{PUBLIC_EVENT_SOURCE_BASE_URL}{MEDIA_URL}"

CALENDAR_PAST_RETENTION_DAYS = env_int("CALENDAR_PAST_RETENTION_DAYS", 90)
CALENDAR_FUTURE_HORIZON_DAYS = env_int("CALENDAR_FUTURE_HORIZON_DAYS", 730)
CALENDAR_PUBLIC_FEED_URL = env_str(
    "CALENDAR_PUBLIC_FEED_URL",
    default=(f"{PUBLIC_EVENT_SOURCE_BASE_URL}/calendar/public/events.ics" if PUBLIC_EVENT_SOURCE_BASE_URL else ""),
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("DJANGO_ENABLE_PROXY_SSL_HEADER", False) else None
USE_X_FORWARDED_HOST = env_bool("DJANGO_USE_X_FORWARDED_HOST", False)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0 if DEBUG else 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_REFERRER_POLICY = os.getenv("DJANGO_SECURE_REFERRER_POLICY", "same-origin")
SECURE_CONTENT_TYPE_NOSNIFF = env_bool("DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", True)
X_FRAME_OPTIONS = os.getenv("DJANGO_X_FRAME_OPTIONS", "DENY")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# SEC-022: explicit LOGGING config so production errors/security warnings
# reliably reach journalctl (the systemd service's stdout/stderr sink - see
# deploy/avf-intern.service) in a consistent, filterable format, instead of
# relying on Django's implicit defaults. This only configures HOW Django's
# own logger calls are formatted/routed - it does not add any new logging of
# passwords, tokens, session IDs, CSRF tokens, Authorization headers, or full
# request bodies (the application's own logger.* calls, in documents/views.py
# and events/public_views.py, were checked to confirm neither does either).
# Deliberately no external error-tracking service (e.g. Sentry) wired in
# here - that would be a new external data transmission and a deliberate
# product/ops decision on its own, not something to add as a side effect.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Suspicious operations, disallowed hosts, CSRF failures, etc.
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

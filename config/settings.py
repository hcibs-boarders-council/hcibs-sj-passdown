
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent

FIREBASE_SERVICE_ACCOUNT_KEY = (
    BASE_DIR
    / "secrets"
    / "hcibs-sj-passdown-firebase-adminsdk-fbsvc-767c25e06f.json"
)


# Environment helpers

def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    value = os.environ.get(name)
    if not value:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


def database_from_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError(
            "DATABASE_URL must use postgres:// or postgresql://"
        )

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


# Core settings

IS_PRODUCTION = (
    os.environ.get("DJANGO_ENV", "development").lower()
    == "production"
)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")

if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set in production."
        )
    SECRET_KEY = (
        "django-insecure-local-development-only-not-for-production"
    )

DEBUG = env_bool("DJANGO_DEBUG", not IS_PRODUCTION)

if IS_PRODUCTION and DEBUG:
    raise ImproperlyConfigured(
        "DJANGO_DEBUG must be false in production."
    )

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    ["localhost", "127.0.0.1"],
)

CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS"
)


# Cloudinary configuration

CLOUDINARY_CLOUD_NAME = os.environ.get(
    "CLOUDINARY_CLOUD_NAME", ""
)
CLOUDINARY_API_KEY = os.environ.get(
    "CLOUDINARY_API_KEY", ""
)
CLOUDINARY_API_SECRET = os.environ.get(
    "CLOUDINARY_API_SECRET", ""
)

CLOUDINARY_CONFIGURED = all(
    [
        CLOUDINARY_CLOUD_NAME,
        CLOUDINARY_API_KEY,
        CLOUDINARY_API_SECRET,
    ]
)

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
    "API_KEY": CLOUDINARY_API_KEY,
    "API_SECRET": CLOUDINARY_API_SECRET,
}


# Installed applications
# Keep Django's staticfiles app before Cloudinary Storage.

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cloudinary_storage",
    "cloudinary",
    "channels",
    "accounts",
    "listings.apps.ListingsConfig",
    "chat.apps.ChatConfig",
]


# Middleware

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "chat.context_processors.chat_unread_count",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Database

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": database_from_url(DATABASE_URL),
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get(
                "POSTGRES_DB", "hcibs_sj_passdown"
            ),
            "USER": os.environ.get(
                "POSTGRES_USER", "hcibs_sj_user"
            ),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }


# Redis / Channels

REDIS_URL = os.environ.get("REDIS_URL")

if IS_PRODUCTION and not REDIS_URL:
    raise ImproperlyConfigured(
        "REDIS_URL must be configured in production."
    )

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL or "redis://127.0.0.1:6379/0"],
        },
    },
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Singapore"
USE_I18N = True
USE_TZ = True


# Static files and uploaded media

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if CLOUDINARY_CONFIGURED
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.StaticFilesStorage",
    },
}

STATICFILES_STORAGE = "whitenoise.storage.StaticFilesStorage"


# Security / proxy settings

SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if env_bool("DJANGO_SECURE_PROXY_SSL_HEADER", not DEBUG)
    else None
)

SESSION_COOKIE_SECURE = env_bool(
    "DJANGO_SESSION_COOKIE_SECURE", not DEBUG
)

CSRF_COOKIE_SECURE = env_bool(
    "DJANGO_CSRF_COOKIE_SECURE", not DEBUG
)


# Email

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
        "OPTIONS": {},
    },
}

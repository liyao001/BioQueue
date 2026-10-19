"""Settings used by an installed BioQueue package.

A git checkout may still have ``BioQueue/settings.py`` (not part of the
package). ``bioqueue`` uses that file when it exists, and this module otherwise.

The secret and the database live in the user's ``custom.conf`` (or in
environment variables), not in this file.

To use MySQL or PostgreSQL, set BIOQUEUE_DB_ENGINE (for example
``django.db.backends.postgresql``) plus BIOQUEUE_DB_NAME, BIOQUEUE_DB_USER,
BIOQUEUE_DB_PASSWORD, BIOQUEUE_DB_HOST, and BIOQUEUE_DB_PORT.
"""
import os
from configparser import ConfigParser

from django.core.exceptions import ImproperlyConfigured

from BioQueue.paths import config_file, package_dir

BASE_DIR = os.path.dirname(package_dir())


def _custom_conf():
    parser = ConfigParser(interpolation=None)
    parser.read(config_file())
    return parser


def _conf_get(parser, section, key, default=""):
    if parser.has_option(section, key):
        return parser.get(section, key)
    return default


def _template_dirs():
    dirs = []
    checkout = os.path.join(BASE_DIR, "templates")
    bundled = os.path.join(package_dir(), "templates")
    for path in (checkout, bundled):
        if os.path.isdir(path) and path not in dirs:
            dirs.append(path)
    return dirs


_cfg = _custom_conf()


def _prefer(env_name, section, key):
    """Environment value when it is non-empty, otherwise custom.conf."""
    env = os.environ.get(env_name)
    if env is not None and env.strip():
        return env.strip()
    return _conf_get(_cfg, section, key).strip()


def _flag(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv(value):
    return [part.strip() for part in str(value).split(",") if part.strip()]


_LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# Bind addresses that are not names a browser sends in the Host header.
_WILDCARD_BINDS = {"", "*", "0.0.0.0", "::", "[::]"}

_secret = _prefer("BIOQUEUE_SECRET_KEY", "env", "secret_key")
if not _secret:
    raise ImproperlyConfigured(
        "BioQueue has no secret key. Run `bioqueue init`, or set BIOQUEUE_SECRET_KEY "
        "or env.secret_key in custom.conf."
    )
SECRET_KEY = _secret

# Off unless custom.conf or BIOQUEUE_DEBUG asks for error pages.
DEBUG = _flag(_prefer("BIOQUEUE_DEBUG", "env", "debug"))

ALLOWED_HOSTS = _csv(_prefer("BIOQUEUE_ALLOWED_HOSTS", "env", "allowed_hosts")) or list(_LOCAL_HOSTS)
_bind = os.environ.get("BIOQUEUE_BIND_HOST", "").strip()
if _bind and _bind not in _WILDCARD_BINDS and _bind not in ALLOWED_HOSTS and "*" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_bind)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "QueueDB",
    "accounts",
    "ui",
    "worker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "BioQueue.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": _template_dirs(),
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "BioQueue.wsgi.application"

_engine = os.environ.get("BIOQUEUE_DB_ENGINE", "").strip()
if _engine == "django.db.backends.mysql":
    # Django imports MySQLdb. PyMySQL provides that module name.
    import pymysql

    pymysql.install_as_MySQLdb()
if _engine:
    DATABASES = {
        "default": {
            "ENGINE": _engine,
            "NAME": os.environ.get("BIOQUEUE_DB_NAME", ""),
            "USER": os.environ.get("BIOQUEUE_DB_USER", ""),
            "PASSWORD": os.environ.get("BIOQUEUE_DB_PASSWORD", ""),
            "HOST": os.environ.get("BIOQUEUE_DB_HOST", "localhost"),
            "PORT": os.environ.get("BIOQUEUE_DB_PORT", ""),
        }
    }
else:
    _data = _conf_get(_cfg, "env", "workspace") or BASE_DIR
    _name = _conf_get(_cfg, "env", "database") or os.path.join(_data, "db.sqlite3")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _name,
            # Seconds to wait if the worker (or the site) is in the middle of a write.
            "OPTIONS": {"timeout": 30},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"

# Site-specific ui extensions (WandB, Dec, …). Dotted modules that call
# ui.plugins.register(...) at import. You can also drop files in
# ui/plugins/local/ (gitignored).
UI3_PLUGINS = []

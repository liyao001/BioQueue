"""Isolated Django settings for ui3 tests (SQLite, no Celery/Postgres)."""

import os
import sys
import types

from django.db import models as dj_models

# QueueDB.extmodels.WandB imports wandb and Postgres ArrayField at module load.
sys.modules.setdefault("wandb", types.ModuleType("wandb"))


class _SQLiteArrayField(dj_models.JSONField):
    def __init__(self, base_field=None, size=None, **kwargs):
        super().__init__(**kwargs)


_pg = types.ModuleType("django.contrib.postgres")
_pg_fields = types.ModuleType("django.contrib.postgres.fields")
_pg_fields.ArrayField = _SQLiteArrayField
_pg.fields = _pg_fields
sys.modules["django.contrib.postgres"] = _pg
sys.modules["django.contrib.postgres.fields"] = _pg_fields

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = "ui3-test-secret-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "QueueDB",
    "ui.apps.Ui3Config",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "ui.test_urls"

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
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
USE_TZ = True
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
SILENCED_SYSTEM_CHECKS = ["fields.E005"]
UI3_PLUGINS = []

# Skip historical QueueDB migrations; build tables from current models.
class _DisableMigrations(dict):
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()

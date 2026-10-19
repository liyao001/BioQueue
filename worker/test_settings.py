"""Isolated Django settings for worker tests (SQLite, no Celery/Postgres)."""

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

SECRET_KEY = "worker-test-secret-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "QueueDB",
]

ROOT_URLCONF = "worker.test_urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
SILENCED_SYSTEM_CHECKS = ["fields.E005"]


class _DisableMigrations(dict):
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()

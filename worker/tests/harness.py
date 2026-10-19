"""Test helpers: Django setup for worker without a full BioQueue env."""
from __future__ import annotations

import os
import sys
import types


def _install_optional_stubs() -> None:
    sys.modules.setdefault("wandb", types.ModuleType("wandb"))

    if "psutil" not in sys.modules:
        try:
            import psutil  # noqa: F401
        except ImportError:
            stub = types.ModuleType("psutil")
            stub.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
            stub.AccessDenied = type("AccessDenied", (Exception,), {})
            stub.ZombieProcess = type("ZombieProcess", (Exception,), {})
            stub.wait_procs = lambda *args, **kwargs: ([], [])
            stub.Process = object
            stub.pids = lambda: []
            sys.modules["psutil"] = stub

    if "scipy" not in sys.modules:
        try:
            import scipy  # noqa: F401
        except ImportError:
            scipy = types.ModuleType("scipy")
            stats = types.ModuleType("scipy.stats")
            stats.linregress = lambda *args, **kwargs: (0, 0, 0, 1, 0)
            scipy.stats = stats
            sys.modules["scipy"] = scipy
            sys.modules["scipy.stats"] = stats

    if "magic" not in sys.modules:
        try:
            import magic  # noqa: F401
        except ImportError:
            stub = types.ModuleType("magic")
            stub.from_file = lambda *args, **kwargs: "text"
            stub.from_buffer = lambda *args, **kwargs: "text"
            sys.modules["magic"] = stub


def setup_django():
    """
    Configure Django for worker tests.

    Returns (ok, error). Callers should skip when ok is False.
    """
    try:
        import django  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:
        return False, exc

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "worker.test_settings")
    _install_optional_stubs()

    import worker._bootstrap  # noqa: F401
    import worker.test_settings  # noqa: F401

    import django

    if not django.apps.apps.ready:
        django.setup()
    return True, None

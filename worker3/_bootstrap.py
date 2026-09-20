"""Keep stdlib ``queue`` visible; do not put legacy ``worker/`` on ``sys.path``."""
import os
import sys

_PACKAGE_DIR = os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
_REPO_ROOT = os.path.abspath(os.path.join(_PACKAGE_DIR, ".."))


def _abs_sys_path_entry(entry: str) -> str:
    return os.path.realpath(os.path.abspath(entry or os.getcwd()))


def prepare_sys_path(script_dir=None):
    """Drop package/script dirs that would shadow stdlib ``queue``; add repo root."""
    drop = {_PACKAGE_DIR}
    if script_dir:
        drop.add(os.path.realpath(os.path.abspath(script_dir)))
    sys.path[:] = [p for p in sys.path if _abs_sys_path_entry(p) not in drop]
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)


# ``python worker3/bioqueue.py`` puts this package directory on sys.path, so the
# local ``queue/`` package shadows the stdlib ``queue`` module. Django → asgiref
# → concurrent.futures then import the wrong ``queue`` and fail with a circular
# ImportError on ``async_to_sync``.
prepare_sys_path()

REPO_ROOT = _REPO_ROOT
PACKAGE_DIR = _PACKAGE_DIR

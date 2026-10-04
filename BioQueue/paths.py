"""Locations that work both in a git checkout and in an installed package."""
import os


def package_dir():
    return os.path.dirname(os.path.abspath(__file__))


def checkout_root():
    """Repository root when this file lives next to manage.py, else None.

    An installed copy lives in site-packages and has no manage.py beside it.
    """
    root = os.path.dirname(package_dir())
    if os.path.isfile(os.path.join(root, "manage.py")):
        return root
    env = os.environ.get("BIOQUEUE_HOME", "")
    if env and os.path.isfile(os.path.join(env, "manage.py")):
        return os.path.abspath(env)
    return None


def data_dir():
    return os.environ.get("BIOQUEUE_DATA") or os.path.join(os.path.expanduser("~"), "BioQueue")


def config_file():
    """User configuration. Never a path inside site-packages."""
    env = os.environ.get("BIOQUEUE_CUSTOM_CONF")
    if env:
        return env
    root = checkout_root()
    if root:
        return os.path.join(root, "config", "custom.conf")
    return os.path.join(data_dir(), "custom.conf")


def bundled_config_template():
    return os.path.join(package_dir(), "data", "custom.conf")


def django_settings_module():
    """Checkout settings.py when a developer has one, otherwise the packaged settings."""
    current = os.environ.get("DJANGO_SETTINGS_MODULE")
    if current:
        return current
    root = checkout_root()
    if root and os.path.isfile(os.path.join(root, "BioQueue", "settings.py")):
        return "BioQueue.settings"
    return "BioQueue.default_settings"

#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "BioQueue.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # The import can fail for a reason other than Django being missing.
        from importlib.util import find_spec

        if find_spec("django") is None:
            raise ImportError(
                "Couldn't import Django. Are you sure it's installed and "
                "available on your PYTHONPATH environment variable? Did you "
                "forget to activate a virtual environment?"
            ) from exc
        raise
    execute_from_command_line(sys.argv)

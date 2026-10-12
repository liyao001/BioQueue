"""Web process for ``bioqueue`` and ``bioqueue serve``.

Started as ``python -m BioQueue.serve runserver <bind>``. Django's
autoreloader re-executes that module. ``python -c`` has no script file,
so the reloader raises ``Script -c does not exist`` and the launcher
then stops the worker too.
"""
import os
import sys

from BioQueue.paths import django_settings_module


def main(argv=None):
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        os.environ["DJANGO_SETTINGS_MODULE"] = django_settings_module()
    argv = list(sys.argv if argv is None else argv)
    if len(argv) > 1 and argv[1] == "--reloader-args":
        from django.utils.autoreload import get_child_arguments

        sys.stdout.write("\n".join(get_child_arguments()))
        sys.stdout.write("\n")
        return 0
    from django.core.management import execute_from_command_line

    execute_from_command_line(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

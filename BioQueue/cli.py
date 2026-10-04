"""Personal BioQueue setup and startup.

    pip install bioqueue
    bioqueue init
    bioqueue
"""
import argparse
import getpass
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from configparser import ConfigParser

from BioQueue.paths import bundled_config_template, checkout_root, config_file, django_settings_module

DATA_SUBDIRS = ("logs", "outputs", "training", "batch_job", "file_comment")


def read_conf(path):
    parser = ConfigParser(interpolation=None)
    if os.path.isfile(path):
        parser.read(path)
    return parser


def conf_get(parser, section, key, default=""):
    if parser.has_option(section, key):
        return parser.get(section, key)
    return default


def update_ini(path, values):
    """Set keys in an ini file without dropping comments or other keys.

    ``values`` is ``{section: {key: value}}``. Only the keys you pass are
    written. A missing file is created.
    """
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines(keepends=True)
    else:
        lines = []
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    for section, keys in values.items():
        lines = _apply_section(lines, section, keys)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def _apply_section(lines, section, keys):
    header = "[%s]" % section
    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            break
    if start is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(header + "\n")
        for key, value in keys.items():
            lines.append("%s = %s\n" % (key, value))
        return lines

    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break

    pending = dict(keys)
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        name, sep, _rest = stripped.partition("=")
        if not sep:
            continue
        name = name.strip()
        if name in pending:
            lines[index] = "%s = %s\n" % (name, pending.pop(name))
    if pending:
        extra = ["%s = %s\n" % (key, value) for key, value in pending.items()]
        lines[end:end] = extra
    return lines


def _gb(nbytes):
    gigabyte = 1024 ** 3
    return max(1, int(round(nbytes / float(gigabyte))))


def machine_limits(data_dir):
    cpu = os.cpu_count() or 1
    try:
        import psutil

        memory = _gb(psutil.virtual_memory().total)
        disk = _gb(psutil.disk_usage(data_dir).total)
    except Exception:
        memory = 1
        disk = 1
    return cpu, memory, disk


def secret_key():
    return secrets.token_urlsafe(48)


def default_data_dir():
    from BioQueue.paths import data_dir

    return data_dir()


def is_initialized():
    parser = read_conf(config_file())
    return bool(conf_get(parser, "env", "workspace").strip())


def _assign(updates, current, section, key, value, override=False):
    if value is None:
        return
    if override or not conf_get(current, section, key).strip():
        updates.setdefault(section, {})[key] = str(value)


def prepare_install(data_dir, cpu=None, memory=None, disk=None, force_data=False, config_path=None):
    """Write config and folders. Returns a short description dict.

    Does not migrate or create an account. Existing non-empty config values
    stay unless a matching override is passed. An existing data folder path
    changes only when ``force_data`` is true.
    """
    path = config_path or config_file()
    if not os.path.isfile(path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copyfile(bundled_config_template(), path)
    current = read_conf(path)
    existing = conf_get(current, "env", "workspace").strip()
    data_dir = os.path.abspath(os.path.expanduser(data_dir))
    if existing and os.path.abspath(existing) != data_dir:
        if not force_data:
            raise SystemExit(
                "Data folder is already %s. Pass --data with --force to switch." % existing
            )
    elif existing:
        data_dir = os.path.abspath(existing)

    os.makedirs(data_dir, exist_ok=True)
    folders = {}
    for name in DATA_SUBDIRS:
        folder = os.path.join(data_dir, name)
        os.makedirs(folder, exist_ok=True)
        folders[name] = folder

    detected_cpu, detected_memory, detected_disk = machine_limits(data_dir)
    updates = {}
    moving = bool(force_data)
    _assign(updates, current, "env", "workspace", data_dir, override=moving or not existing)
    _assign(updates, current, "env", "log", folders["logs"], override=moving)
    _assign(updates, current, "env", "outputs", folders["outputs"], override=moving)
    _assign(updates, current, "env", "batch_job", folders["batch_job"], override=moving)
    _assign(updates, current, "ml", "trainstore", folders["outputs"], override=moving)
    _assign(updates, current, "env", "database", os.path.join(data_dir, "db.sqlite3"), override=moving)
    _assign(
        updates, current, "env", "cpu",
        cpu if cpu is not None else detected_cpu,
        override=cpu is not None,
    )
    _assign(
        updates, current, "env", "max_job",
        cpu if cpu is not None else detected_cpu,
        override=cpu is not None,
    )
    _assign(
        updates, current, "env", "memory",
        memory if memory is not None else detected_memory,
        override=memory is not None,
    )
    _assign(
        updates, current, "env", "disk_quota",
        disk if disk is not None else detected_disk,
        override=disk is not None,
    )
    _assign(updates, current, "env", "secret_key", secret_key())
    _assign(updates, current, "env", "feedback", "no")
    if updates:
        update_ini(path, updates)

    root = checkout_root()
    settings_py = os.path.join(root, "BioQueue", "settings.py") if root else ""
    created_settings = False
    if root and not os.path.isfile(settings_py):
        shutil.copyfile(os.path.join(root, "BioQueue", "settings-example.py"), settings_py)
        created_settings = True

    return {
        "data_dir": data_dir,
        "database": os.path.join(data_dir, "db.sqlite3"),
        "created_settings": created_settings,
        "settings_py": settings_py,
        "using_packaged_settings": not created_settings and not (settings_py and os.path.isfile(settings_py)),
    }


def _setup_django():
    root = checkout_root()
    if root and root not in sys.path:
        sys.path.insert(0, root)
    os.environ["DJANGO_SETTINGS_MODULE"] = django_settings_module()
    os.environ["BIOQUEUE_CUSTOM_CONF"] = config_file()
    import django

    django.setup()


def migrate_and_ensure_user(username, password):
    _setup_django()
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.core.management import call_command
    from django.db import connections

    call_command("migrate", interactive=False, verbosity=1)
    for name in ("normal", "worker", "viewer"):
        Group.objects.get_or_create(name=name)

    User = get_user_model()
    created = False
    if not User.objects.filter(username=username).exists():
        user = User.objects.create_superuser(username, "", password)
        user.groups.add(Group.objects.get(name="normal"))
        created = True
    connections.close_all()
    return created


def _prompt_account(username, password):
    if not username:
        default = getpass.getuser()
        if sys.stdin.isatty():
            typed = input("Account name [%s]: " % default).strip()
            username = typed or default
        else:
            username = default
    if not password:
        if sys.stdin.isatty():
            while True:
                password = getpass.getpass("Password: ")
                again = getpass.getpass("Password again: ")
                if password and password == again:
                    break
                print("Passwords did not match, or were empty.")
        else:
            password = secrets.token_urlsafe(12)
            print("Generated password for %s: %s" % (username, password))
    return username, password


def cmd_init(args):
    current = conf_get(read_conf(config_file()), "env", "workspace").strip()
    if args.data:
        data_dir = args.data
        force = args.force
    else:
        data_dir = current or default_data_dir()
        force = False
    info = prepare_install(
        data_dir,
        cpu=args.cpu,
        memory=args.memory,
        disk=args.disk,
        force_data=force,
    )
    print("Data folder: %s" % info["data_dir"])
    if info["using_packaged_settings"] or info["created_settings"]:
        print("Database: SQLite at %s" % info["database"])
    else:
        print("Keeping existing %s (database was not changed)." % info["settings_py"])

    if args.no_user:
        print("Skipped account creation.")
        return 0

    username, password = _prompt_account(args.username, args.password)
    created = migrate_and_ensure_user(username, password)
    if created:
        print("Account created: %s" % username)
    else:
        print("Account already exists: %s" % username)
    print("")
    print("Start BioQueue with:  bioqueue")
    print("Then open http://127.0.0.1:8000/ and sign in.")
    return 0


def _require_initialized():
    if not is_initialized():
        raise SystemExit("BioQueue is not set up yet. Run: bioqueue init")


def _child_env():
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = django_settings_module()
    env["BIOQUEUE_CUSTOM_CONF"] = config_file()
    return env


def cmd_worker(_args):
    _require_initialized()
    os.environ.update(_child_env())
    os.execv(sys.executable, [sys.executable, "-m", "worker3"])


def cmd_serve(args):
    _require_initialized()
    os.environ.update(_child_env())
    bind = "%s:%s" % (args.host, args.port)
    os.execv(
        sys.executable,
        [sys.executable, "-c", "from django.core.management import execute_from_command_line; execute_from_command_line(['bioqueue', 'runserver', '%s'])" % bind],
    )


def cmd_start(args):
    _require_initialized()
    bind = "%s:%s" % (args.host, args.port)
    print("Open http://%s:%s/  (Ctrl-C stops the worker and the web app)" % (args.host, args.port))
    env = _child_env()
    worker = subprocess.Popen([sys.executable, "-m", "worker3"], env=env)
    web = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from django.core.management import execute_from_command_line; execute_from_command_line(['bioqueue', 'runserver', '%s'])" % bind,
        ],
        env=env,
    )

    def stop(_signum=None, _frame=None):
        for proc in (worker, web):
            if proc.poll() is None:
                proc.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    code = 0
    try:
        while True:
            if worker.poll() is not None:
                code = worker.returncode or 0
                stop()
                break
            if web.poll() is not None:
                code = web.returncode or 0
                stop()
                break
            time.sleep(0.4)
    finally:
        stop()
        for proc in (worker, web):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return code


def cmd_up(args):
    """First run sets BioQueue up, then starts it. Later runs just start it."""
    if not is_initialized():
        print("First run: setting up BioQueue in %s" % (args.data or default_data_dir()))
        status = cmd_init(args)
        if status:
            return status
    return cmd_start(args)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="bioqueue",
        description="Set up and run BioQueue (web app and worker).",
        epilog="With no command, BioQueue sets itself up on first run and then starts.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="up",
        choices=("up", "init", "start", "worker", "serve"),
        help="up (default): init if needed, then start. init: set up only. start / worker / serve: run",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Web address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Web port (default: 8000)")
    parser.add_argument("--data", help="Data folder (default: ~/BioQueue). Used by init and first run")
    parser.add_argument("--username", help="First account name (default: your login name)")
    parser.add_argument("--password", help="First account password. Asked for when a terminal is attached")
    parser.add_argument("--cpu", type=int, help="CPU cores the worker may use (default: this machine)")
    parser.add_argument("--memory", type=int, help="Memory budget in GB (default: this machine)")
    parser.add_argument("--disk", type=int, help="Disk budget in GB (default: the data disk)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --data, switch the data folder even if one is already configured",
    )
    parser.add_argument(
        "--no-user",
        action="store_true",
        help="Init the folders and database config without creating an account",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    dispatch = {
        "up": cmd_up,
        "init": cmd_init,
        "start": cmd_start,
        "worker": cmd_worker,
        "serve": cmd_serve,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

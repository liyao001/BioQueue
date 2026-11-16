"""Scripts and assets stored beside a protocol.

The database remains the protocol record. These files are the pieces a step
runs or reads, kept under the data directory so export, share, and clone can
copy the folder with the steps.

A step refers to a file as ``{{Script:name}}`` or ``scripts/name``, and
``{{Asset:name}}`` or ``assets/name``. The worker rewrites those to the stored
path when the job runs. A Slurm submit packs each referenced ``scripts`` or
``assets`` directory into the batch script. The compute node unpacks that
directory before the step command, so helpers beside an entry script are
present even when the node cannot see the BioQueue data directory.
"""

import os
import re
import shutil

ROLES = ("scripts", "assets")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_FILES = 100
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,180}$")
_TOKEN_RE = re.compile(r"\{\{(Script|Asset):([^{}]+)\}\}", re.IGNORECASE)
_BARE_RE = re.compile(
    r"(?<![\w./-])((?:scripts|assets)/[A-Za-z0-9][A-Za-z0-9._+/-]{0,400})"
)


class ProtocolBundleError(ValueError):
    """User-facing failure while reading or writing protocol files."""


def files_root():
    from django.conf import settings

    configured = getattr(settings, "PROTOCOL_FILES_ROOT", "") or ""
    if configured:
        return os.path.realpath(configured)
    from BioQueue.paths import data_dir

    return os.path.realpath(os.path.join(data_dir(), "protocol_files"))


def _protocol_dirname(protocol_id):
    try:
        number = int(protocol_id)
    except (TypeError, ValueError):
        raise ProtocolBundleError("Unknown protocol.")
    if number < 1:
        raise ProtocolBundleError("Unknown protocol.")
    return str(number)


def protocol_dir(protocol_id):
    root = files_root()
    path = os.path.realpath(os.path.join(root, _protocol_dirname(protocol_id)))
    if path != root and not path.startswith(root + os.sep):
        raise ProtocolBundleError("Unknown protocol.")
    return path


def _role_dir(protocol_id, role):
    if role not in ROLES:
        raise ProtocolBundleError("Choose scripts or assets.")
    base = protocol_dir(protocol_id)
    path = os.path.realpath(os.path.join(base, role))
    if not path.startswith(base + os.sep):
        raise ProtocolBundleError("Choose scripts or assets.")
    return path


def clean_relative(name):
    """A relative path of safe segments, using forward slashes."""
    raw = (name or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/"):
        raise ProtocolBundleError("That file name is not allowed.")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or len(parts) > 8 or any(_SEGMENT.match(part) is None for part in parts):
        raise ProtocolBundleError("That file name is not allowed.")
    return "/".join(parts)


def resolve_file(protocol_id, role, relative):
    """Absolute path of a stored file, or None when it is not there."""
    rel = clean_relative(relative)
    directory = _role_dir(protocol_id, role)
    path = os.path.realpath(os.path.join(directory, *rel.split("/")))
    if path != directory and not path.startswith(directory + os.sep):
        raise ProtocolBundleError("That file name is not allowed.")
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    return path


def list_files(protocol_id):
    """``{"scripts": [{"name", "size"}], "assets": [...]}``."""
    listed = {role: [] for role in ROLES}
    for role in ROLES:
        directory = _role_dir(protocol_id, role)
        if os.path.islink(directory) or not os.path.isdir(directory):
            continue
        for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if _SEGMENT.match(name) and not os.path.islink(os.path.join(dirpath, name))
            ]
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                relative = os.path.relpath(full, directory).replace(os.sep, "/")
                try:
                    clean_relative(relative)
                except ProtocolBundleError:
                    continue
                listed[role].append({"name": relative, "size": os.path.getsize(full)})
        listed[role].sort(key=lambda item: item["name"])
    return listed


def _file_count(protocol_id):
    listed = list_files(protocol_id)
    return sum(len(items) for items in listed.values())


def write_file(protocol_id, role, relative, data):
    if not isinstance(data, (bytes, bytearray)):
        raise ProtocolBundleError("File contents must be bytes.")
    if len(data) > MAX_FILE_BYTES:
        raise ProtocolBundleError("File is too large (max 8 MB).")
    rel = clean_relative(relative)
    directory = _role_dir(protocol_id, role)
    dest = os.path.realpath(os.path.join(directory, *rel.split("/")))
    if dest != directory and not dest.startswith(directory + os.sep):
        raise ProtocolBundleError("That file name is not allowed.")
    replacing = os.path.isfile(dest) and not os.path.islink(dest)
    if not replacing and _file_count(protocol_id) >= MAX_FILES:
        raise ProtocolBundleError("This protocol already has {} files.".format(MAX_FILES))
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    real_parent = os.path.realpath(parent)
    if real_parent != directory and not real_parent.startswith(directory + os.sep):
        raise ProtocolBundleError("That file name is not allowed.")
    temporary = dest + ".tmpwrite"
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
        os.replace(temporary, dest)
    except OSError as exc:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise ProtocolBundleError("Could not store that file.") from exc
    return rel


def delete_file(protocol_id, role, relative):
    path = resolve_file(protocol_id, role, relative)
    if path is None:
        raise ProtocolBundleError("That file is not in the bundle.")
    directory = _role_dir(protocol_id, role)
    os.remove(path)
    parent = os.path.dirname(path)
    while parent.startswith(directory + os.sep):
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)


def delete_bundle(protocol_id):
    try:
        root = protocol_dir(protocol_id)
    except ProtocolBundleError:
        return
    if os.path.islink(root) or not os.path.isdir(root):
        return
    shutil.rmtree(root)


def copy_bundle(src_id, dest_id):
    """Copy scripts and assets onto another protocol. No-op when there are none."""
    listed = list_files(src_id)
    for role, items in listed.items():
        for item in items:
            path = resolve_file(src_id, role, item["name"])
            if path is None:
                continue
            with open(path, "rb") as handle:
                write_file(dest_id, role, item["name"], handle.read())


def expand_bundle_paths(text, protocol_id):
    """Rewrite script and asset references to stored absolute paths."""
    if not text:
        return text
    try:
        protocol_id = int(protocol_id)
    except (TypeError, ValueError):
        return text
    if protocol_id < 1:
        return text

    def token_sub(match):
        role = "scripts" if match.group(1).lower() == "script" else "assets"
        try:
            path = resolve_file(protocol_id, role, match.group(2).strip())
        except ProtocolBundleError:
            return match.group(0)
        return path if path else match.group(0)

    def bare_sub(match):
        relative = match.group(1)
        role, _, rest = relative.partition("/")
        try:
            path = resolve_file(protocol_id, role, rest)
        except ProtocolBundleError:
            return match.group(0)
        return path if path else match.group(0)

    rewritten = _TOKEN_RE.sub(token_sub, text)
    return _BARE_RE.sub(bare_sub, rewritten)

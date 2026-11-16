"""Build a job result tar and resolve it for download.

Creating an archive stores a queued FileArchive and returns immediately. A
background thread, and the worker's own kick, write the .tar.gz into the
owner's archives folder. The request must not wait on that tar: a large
result folder outlives the gateway and the browser only sees a 504.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import tarfile
import threading
import time

from .files import format_bytes, result_dir, user_root
from .services import (
    ARCHIVE_DONE,
    ARCHIVE_FAILED,
    ARCHIVE_QUEUED,
    ARCHIVE_WORKING,
    FileArchive,
    folder_defaults_for,
)

logger = logging.getLogger("BioQueue")

MAX_ARCHIVE_FILES = 100_000
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_BUILD_LOCK = threading.Lock()


class ArchiveBuildError(Exception):
    """User-facing reason an archive tar was not written."""


def archives_root_for(user, *, create=False):
    path = (folder_defaults_for(user).get("archives") or "").strip()
    if not path:
        return None
    if create:
        os.makedirs(path, exist_ok=True)
    if not os.path.isdir(path):
        return None
    return os.path.realpath(path)


def _inside(path, root):
    """True when path is root or a real file/dir inside root."""
    if not path or not root:
        return False
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    return path_real == root_real or path_real.startswith(root_real + os.sep)


def _lexical_under(path, root):
    path_abs = os.path.abspath(path)
    root_abs = os.path.abspath(root)
    return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)


def archive_filename(job, archive_id):
    raw = _NAME_RE.sub("-", (getattr(job, "job_name", None) or "job")).strip(".-_")
    raw = (raw or "job")[:40]
    return "job-{}-{}-{}.tar.gz".format(job.id, raw, archive_id)


def _arcname(job, original):
    """Tar path for a result file. Rejects anything that climbs out of results/."""
    root = result_dir(job)
    rel = ""
    if root and original and _lexical_under(original, root):
        rel = os.path.relpath(os.path.abspath(original), os.path.abspath(root))
        rel = rel.replace(os.sep, "/")
    if not rel or rel in (".", "..") or rel.startswith("../") or "/../" in rel:
        base = os.path.basename(original or "")
        if not base or base in (".", "..") or "/" in base or "\\" in base:
            return None
        rel = base
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "results/" + "/".join(parts)


def _regular_file_inside(full, bound, archives_root):
    """Real file path, or None when it is missing, special, or outside the job."""
    if not full:
        return None
    try:
        if not os.path.lexists(full):
            return None
        real = os.path.realpath(full)
    except OSError:
        return None
    if not os.path.isfile(real):
        return None
    if not _inside(real, bound):
        return None
    if archives_root and _inside(real, archives_root):
        return None
    return real


def _iter_result_files(job, bound, archives_root):
    root = result_dir(job)
    if not root or not os.path.isdir(root) or os.path.islink(root):
        return
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if not os.path.islink(os.path.join(dirpath, name))
        ]
        for name in filenames:
            full = os.path.join(dirpath, name)
            arc = _arcname(job, full)
            real = _regular_file_inside(full, bound, archives_root)
            if not arc or not real:
                continue
            count += 1
            if count > MAX_ARCHIVE_FILES:
                raise ArchiveBuildError(
                    "Too many files to archive (max {}).".format(MAX_ARCHIVE_FILES)
                )
            yield real, arc


def _log_members(job):
    try:
        from worker.bases import get_config

        log_dir = get_config("env", "log")
    except Exception:
        return []
    if not log_dir or not os.path.isdir(log_dir):
        return []
    root = os.path.realpath(log_dir)
    found = []
    for suffix, arc in ((".log", "logs/stdout.log"), (".err", "logs/stderr.log")):
        full = os.path.join(log_dir, "{}{}".format(job.id, suffix))
        if os.path.islink(full):
            continue
        try:
            real = os.path.realpath(full)
        except OSError:
            continue
        if os.path.isfile(real) and _inside(real, root):
            found.append((real, arc))
    return found


def _load_file_list(archive):
    try:
        data = json.loads(archive.files or "")
    except (TypeError, ValueError):
        raise ArchiveBuildError("Archive file list is invalid.")
    return data


def collect_members(archive):
    """(realpath, arcname) pairs for the tar. Logs are added for a whole-job archive."""
    job = archive.job
    if job is None:
        raise ArchiveBuildError("Archive is not attached to a job.")
    bound = user_root(job)
    if not bound:
        raise ArchiveBuildError("Job has no workspace folder.")
    bound = os.path.realpath(bound)
    archives_root = archives_root_for(archive.user, create=False)
    data = _load_file_list(archive)
    file_members = []
    seen = set()

    def add(real, arc):
        if not arc or arc in seen or arc.startswith("/") or ".." in arc.split("/"):
            return
        seen.add(arc)
        file_members.append((real, arc))

    if isinstance(data, dict) and data.get("scope") == "result":
        for real, arc in _iter_result_files(job, bound, archives_root):
            add(real, arc)
        explicit = False
    elif isinstance(data, list):
        explicit = True
        for raw in data:
            original = str(raw or "")
            real = _regular_file_inside(original, bound, archives_root)
            if not real:
                continue
            add(real, _arcname(job, original))
        if data and not file_members:
            raise ArchiveBuildError("No selected files could be archived.")
    else:
        raise ArchiveBuildError("Archive file list is invalid.")

    if not explicit:
        for real, arc in _log_members(job):
            add(real, arc)
    if not file_members:
        raise ArchiveBuildError("No result files to archive.")
    if len(file_members) > MAX_ARCHIVE_FILES:
        raise ArchiveBuildError(
            "Too many files to archive (max {}).".format(MAX_ARCHIVE_FILES)
        )
    return file_members


def _manifest_bytes(archive, members):
    job = archive.job
    protocol = getattr(job, "protocol", None)
    workspace = getattr(job, "workspace", None)
    try:
        from QueueDB.models import JobStatus

        status_label = str(JobStatus(job.status).label)
    except Exception:
        status_label = str(getattr(job, "status", ""))
    payload = {
        "archive_id": archive.id,
        "description": archive.description or "",
        "job_id": job.id,
        "job_name": job.job_name or "",
        "protocol": getattr(protocol, "name", "") or "",
        "protocol_ver": job.protocol_ver or "",
        "parameter": job.parameter or "",
        "input_file": job.input_file or "",
        "sample_sheet": job.sample_sheet or "",
        "comments": job.comments or "",
        "status": status_label,
        "result": job.result or "",
        "workspace": getattr(workspace, "name", "") or "",
        "created": job.create_time.isoformat() if job.create_time else "",
        "files": [arc for _real, arc in members],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def _mark_failed(archive, message):
    job_id = archive.job_id
    text = "Job #{}: {}".format(job_id, message) if job_id else str(message)
    FileArchive.objects.filter(pk=archive.pk).update(
        status=ARCHIVE_FAILED,
        comment=text[:500],
        job=None,
    )


def _write_archive(archive, members):
    root = archives_root_for(archive.user, create=True)
    if not root:
        raise ArchiveBuildError("Archives folder is not available.")
    filename = archive_filename(archive.job, archive.id)
    if os.path.basename(filename) != filename or not filename.endswith(".tar.gz"):
        raise ArchiveBuildError("Archive file name is invalid.")
    final = os.path.join(root, filename)
    if not _inside(os.path.dirname(final), root) and os.path.dirname(final) != root:
        raise ArchiveBuildError("Archive path escaped the archives folder.")
    partial = final + ".partial"
    try:
        with tarfile.open(partial, "w:gz") as tar:
            manifest = _manifest_bytes(archive, members)
            info = tarfile.TarInfo(name="bioqueue-job.json")
            info.size = len(manifest)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(manifest))
            for real, arc in members:
                if not arc or arc.startswith("/") or ".." in arc.split("/"):
                    continue
                tar.add(real, arcname=arc, recursive=False)
        os.replace(partial, final)
        digest = hashlib.md5()
        with open(final, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return final, digest.hexdigest()
    except Exception:
        for leftover in (partial, final):
            if os.path.lexists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
        raise


def build_archive(archive):
    """
    Claim a queued archive and write its tar.

    Returns (path, error). A second caller finds the finished file, or hears
    that a build is already in progress.
    """
    claimed = FileArchive.objects.filter(pk=archive.pk, status=ARCHIVE_QUEUED).update(
        status=ARCHIVE_WORKING
    )
    if not claimed:
        archive.refresh_from_db()
        if archive.status == ARCHIVE_DONE:
            path = resolve_archive_download(archive)
            if path:
                return path, None
        if archive.status == ARCHIVE_WORKING:
            return None, "Archive is already being created. Check Archives in a moment."
        return None, (archive.comment or "Archive could not be created.")
    try:
        archive.refresh_from_db()
        members = collect_members(archive)
        path, digest = _write_archive(archive, members)
    except ArchiveBuildError as exc:
        _mark_failed(archive, str(exc))
        return None, str(exc)
    except OSError as exc:
        logger.exception("Archive %s failed", archive.pk)
        message = str(exc) or "Could not create the archive."
        _mark_failed(archive, message)
        return None, message
    except Exception:
        logger.exception("Archive %s failed", archive.pk)
        message = "Could not create the archive."
        _mark_failed(archive, message)
        return None, message
    updated = FileArchive.objects.filter(pk=archive.pk, status=ARCHIVE_WORKING).update(
        status=ARCHIVE_DONE,
        archive_file=path,
        file_md5s=digest,
        comment="",
    )
    if not updated:
        try:
            os.remove(path)
        except OSError:
            pass
        return None, "Archive could not be saved."
    archive.status = ARCHIVE_DONE
    archive.archive_file = path
    archive.file_md5s = digest
    return path, None


def resolve_archive_download(archive):
    """Absolute tar path, or None when the record must not be served."""
    if archive is None or archive.status != ARCHIVE_DONE:
        return None
    raw = (archive.archive_file or "").strip()
    if not raw or raw == "ph":
        return None
    if os.path.islink(raw):
        return None
    root = archives_root_for(archive.user, create=False)
    if not root:
        return None
    try:
        full = os.path.realpath(raw)
    except OSError:
        return None
    if not full.endswith(".tar.gz"):
        return None
    if os.path.basename(full) != os.path.basename(raw):
        return None
    if not _inside(full, root) or full == root:
        return None
    if not os.path.isfile(full):
        return None
    return full


def archive_summary(archive):
    path = resolve_archive_download(archive)
    if not path:
        return {"ready": False, "name": "", "size_label": "", "path": ""}
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {
        "ready": True,
        "name": os.path.basename(path),
        "size_label": format_bytes(size),
        "path": path,
    }


def present_archive(archive):
    summary = archive_summary(archive)
    archive.ui3_ready = summary["ready"]
    archive.ui3_name = summary["name"]
    archive.ui3_size = summary["size_label"]
    return archive


def process_queued_archives(limit=1):
    """Build up to `limit` queued archives. Failures stay on the row and are not retried."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 1
    limit = max(1, min(limit, 10))
    ids = list(
        FileArchive.objects.filter(status=ARCHIVE_QUEUED)
        .order_by("pk")
        .values_list("pk", flat=True)[:limit]
    )
    built = 0
    for pk in ids:
        archive = (
            FileArchive.objects.filter(pk=pk, status=ARCHIVE_QUEUED)
            .select_related("job", "job__protocol", "job__workspace", "user", "protocol")
            .first()
        )
        if archive is None:
            continue
        _path, error = build_archive(archive)
        if error:
            logger.info("Archive %s: %s", pk, error)
        else:
            built += 1
    return built


def kick_archive_builder():
    """Build queued archives on a background thread, without blocking the caller.

    Tests set ``ARCHIVE_BUILD_ASYNC`` false so a request can assert the queued
    row and then call :func:`process_queued_archives` itself. A thread started
    inside a Django test cannot see that test's open transaction.
    """
    from django.conf import settings

    if not getattr(settings, "ARCHIVE_BUILD_ASYNC", True):
        return
    if not _BUILD_LOCK.acquire(blocking=False):
        return

    def _run():
        try:
            from django.db import close_old_connections, connections

            close_old_connections()
            try:
                for _ in range(100):
                    if not FileArchive.objects.filter(status=ARCHIVE_QUEUED).exists():
                        break
                    process_queued_archives(limit=1)
            finally:
                connections.close_all()
        except Exception:
            logger.exception("Archive build failed")
        finally:
            _BUILD_LOCK.release()

    threading.Thread(target=_run, name="bioqueue-archive", daemon=True).start()

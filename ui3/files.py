"""Job result file listing, preview, download, and delete (ui2-compatible traces)."""

from __future__ import annotations

import base64
import mimetypes
import os
import time

from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest


def configured_workspace_base():
    """Configured env.workspace, or None if missing."""
    try:
        from worker.bases import get_config

        base_dir = get_config("env", "workspace")
    except Exception:
        return None
    if base_dir is None:
        return None
    text = str(base_dir).strip()
    return text or None


def workspace_root_for(user):
    """Absolute workspace root for a user: {env.workspace}/{user_id}."""
    base_dir = configured_workspace_base() or os.getcwd()
    return os.path.join(base_dir, str(getattr(user, "id", "")))


def list_workspace_files(user, kind="uploads"):
    """
    List files under the user's workspace subfolder (uploads or refs).

    Returns [{name, file_size, file_create, full_path, size_label}, ...] sorted by name.
    """
    kind = (kind or "uploads").lower()
    if kind not in ("uploads", "refs"):
        kind = "uploads"
    user_root = os.path.join(workspace_root_for(user), kind)
    try:
        os.makedirs(user_root, exist_ok=True)
    except Exception:
        pass
    out = []
    if not os.path.isdir(user_root):
        return out
    for root, _dirs, files in os.walk(user_root):
        for file_name in files:
            try:
                full_path = os.path.join(root, file_name)
                rel = full_path.replace(user_root + os.sep, "").replace(user_root, "")
                size = os.path.getsize(full_path)
                out.append(
                    {
                        "name": rel,
                        "file_size": size,
                        "file_create": time.ctime(os.path.getctime(full_path)),
                        "full_path": full_path,
                        "size_label": format_bytes(size),
                    }
                )
            except Exception:
                continue
    out.sort(key=lambda x: (x.get("name") or "").lower())
    return out


TEXT_TYPES = {
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-sh",
}


def format_bytes(n):
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    value = float(n)
    while value >= 1024 and i < len(units) - 1:
        value /= 1024.0
        i += 1
    if value < 10 and i > 0:
        return "{:.1f} {}".format(value, units[i])
    return "{} {}".format(int(round(value)), units[i])


def user_root(job):
    return os.path.realpath(os.path.join(job.run_dir or "", str(job.user_id)))


def result_dir(job):
    folder = job.get_result() if hasattr(job, "get_result") else job.result
    if not folder:
        return None
    return os.path.join(user_root(job), folder)


def encode_trace(relative_path):
    return base64.b64encode(relative_path.encode()).decode()


def decode_trace(trace):
    try:
        return base64.b64decode(trace).decode()
    except Exception:
        return None


MAX_FILE_NAME = 255


def _is_under_root(path, root):
    root = os.path.realpath(root)
    path = os.path.abspath(path)
    return path == root or path.startswith(root + os.sep)


def resolve_job_file(job, trace):
    relative = decode_trace(trace)
    if not relative:
        return None
    root = user_root(job)
    full = os.path.realpath(os.path.join(root, relative))
    if full != root and not full.startswith(root + os.sep):
        return None
    if not os.path.isfile(full):
        return None
    return full


def resolve_listed_job_file(job, trace):
    """
    Resolve a listed result file without following the last symlink.

    Rename should change the name in the job folder, not the symlink target.
    """
    relative = decode_trace(trace)
    if not relative or os.path.isabs(relative):
        return None
    root = user_root(job)
    candidate = os.path.normpath(os.path.join(root, relative.replace("/", os.sep)))
    parent = os.path.realpath(os.path.dirname(candidate))
    full = os.path.join(parent, os.path.basename(candidate))
    if not _is_under_root(full, root):
        return None
    if not os.path.lexists(full):
        return None
    if os.path.isdir(full) and not os.path.islink(full):
        return None
    return full


def listed_display_name(job, trace):
    """Relative path inside the job result folder, matching list_job_files names."""
    relative = decode_trace(trace) or ""
    folder = job.get_result() if hasattr(job, "get_result") else job.result
    folder = (folder or "").rstrip("/\\")
    if folder and (relative == folder or relative.startswith(folder + "/") or relative.startswith(folder + os.sep)):
        return relative[len(folder) :].lstrip("/\\")
    return relative


def _validate_file_basename(new_name):
    name = (new_name or "").strip()
    if not name:
        return None, "New name is required."
    if len(name) > MAX_FILE_NAME:
        return None, "Name is too long (max {} characters).".format(MAX_FILE_NAME)
    if name in (".", ".."):
        return None, "Invalid file name."
    if "/" in name or "\\" in name or "\x00" in name:
        return None, "Name cannot contain path separators."
    return name, None


def _safe_rename(src, dst):
    if src == dst:
        return
    same_ignore_case = src.lower() == dst.lower()
    if same_ignore_case:
        tmp = src + ".__renametmp__"
        i = 0
        while os.path.lexists(tmp):
            i += 1
            tmp = src + ".__renametmp__{}".format(i)
        os.rename(src, tmp)
        os.rename(tmp, dst)
        return
    os.rename(src, dst)


def rename_job_file(job, trace, new_name):
    """
    Rename a listed job result file in its current directory.

    Returns (True, new_basename) or (False, error_message).
    """
    name, err = _validate_file_basename(new_name)
    if err:
        return False, err
    src = resolve_listed_job_file(job, trace)
    if not src:
        return False, "File not found."
    folder = result_dir(job)
    if not folder:
        return False, "Job has no result folder."
    parent = os.path.dirname(src)
    if not _is_under_root(parent, folder):
        return False, "File is outside the job result folder."
    dest = os.path.join(parent, name)
    dest_parent = os.path.realpath(os.path.dirname(dest))
    if not _is_under_root(dest_parent, folder):
        return False, "File is outside the job result folder."
    if dest == src:
        return True, name
    if os.path.lexists(dest):
        try:
            same = os.path.samefile(src, dest)
        except OSError:
            same = False
        if not same:
            return False, "A file named {} already exists.".format(name)
    try:
        _safe_rename(src, dest)
    except OSError as exc:
        return False, str(exc)
    return True, name


def list_job_files(job, max_files=50000):
    items = []
    folder = job.get_result() if hasattr(job, "get_result") else job.result
    if not folder:
        return items
    user_path = result_dir(job)
    if not user_path or not os.path.isdir(user_path):
        return items
    count = 0
    for root, _dirs, files in os.walk(user_path):
        for file_name in files:
            if file_name == ".snapshot.ini":
                continue
            if count >= max_files:
                return items
            try:
                full_path = os.path.join(root, file_name)
                rel = full_path.replace(user_path + os.sep, "").replace(user_path, "")
                items.append({
                    "name": rel,
                    "file_size": os.path.getsize(full_path),
                    "file_create": time.ctime(os.path.getctime(full_path)),
                    "trace": encode_trace(os.path.join(folder, rel)),
                    "is_link": os.path.islink(full_path),
                    "size_label": format_bytes(os.path.getsize(full_path)),
                })
                count += 1
            except Exception:
                continue
    return items


def _created_ts(value):
    try:
        return time.mktime(time.strptime(value, "%a %b %d %H:%M:%S %Y"))
    except Exception:
        return 0.0


def page_job_files(job, *, q="", sort="name", order="asc", limit=50, offset=0):
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    limit = max(1, min(1000, limit))
    offset = max(0, offset)
    items = list_job_files(job)
    needle = (q or "").strip().lower()
    if needle:
        items = [it for it in items if needle in str(it.get("name", "")).lower()]
    sort_field = (sort or "name").lower()
    reverse = (order or "asc").lower() == "desc"
    if sort_field == "size":
        items.sort(key=lambda x: int(x.get("file_size") or 0), reverse=reverse)
    elif sort_field == "created":
        items.sort(key=lambda x: _created_ts(x.get("file_create") or ""), reverse=reverse)
    else:
        items.sort(key=lambda x: (x.get("name") or "").lower(), reverse=reverse)
    total = len(items)
    start = min(offset, total)
    end = min(start + limit, total)
    return {
        "items": items[start:end],
        "total": total,
        "offset": start,
        "limit": limit,
        "has_more": end < total,
        "q": q or "",
        "sort": sort_field if sort_field in ("name", "size", "created") else "name",
        "order": "desc" if reverse else "asc",
        "next_offset": end,
    }


def delete_job_file(job, trace):
    path = resolve_job_file(job, trace)
    if not path:
        return False
    try:
        os.remove(path)
        return True
    except Exception:
        return False


def delete_job_files(job, traces, max_files=1000):
    """
    Delete listed result files by trace.

    Returns {"deleted": int, "failed": int, "requested": int}.
    """
    seen = []
    for raw in traces or []:
        trace = (raw or "").strip()
        if not trace or trace in seen:
            continue
        seen.append(trace)
        if len(seen) >= max_files:
            break
    deleted = 0
    failed = 0
    for trace in seen:
        if delete_job_file(job, trace):
            deleted += 1
        else:
            failed += 1
    return {"deleted": deleted, "failed": failed, "requested": len(seen)}


PROTECTED_WORKSPACE_FOLDERS = frozenset({"refs", "bin", "uploads", "archives", "OVERRIDE_UPLOAD"})


def delete_job_file_tree(job):
    """
    Remove the job result folder under the owner's workspace.

    Mirrors ui/views/Job.delete_job_file_tree but takes a Job instance:
    path = join(job.run_dir, str(job.user_id), job.result).
    """
    import shutil

    try:
        folder = job.result if job.result else None
        if not folder:
            return False
        user_dir = os.path.join(job.run_dir or "", str(job.user_id))
        job_path = os.path.join(user_dir, folder)
        if os.path.exists(job_path) and not os.path.samefile(user_dir, job_path):
            shutil.rmtree(job_path, ignore_errors=True)
            return True
    except Exception:
        return False
    return False


def job_result_relpath(job):
    folder = (job.result or "").replace("\\", "/").strip("/")
    if not folder or folder in (".", ".."):
        return None
    parts = [p for p in folder.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        return None
    return os.path.join(*parts)


def _lexical_join(root, rel):
    candidate = os.path.normpath(os.path.join(root, rel))
    parent = os.path.realpath(os.path.dirname(candidate))
    return os.path.join(parent, os.path.basename(candidate))


def _dest_prefix_conflict(dest, dest_root):
    dest = os.path.normpath(dest)
    dest_root = os.path.normpath(dest_root)
    rel = os.path.relpath(dest, dest_root)
    if rel.startswith("..") or os.path.isabs(rel):
        return True
    acc = dest_root
    for part in [p for p in rel.split(os.sep) if p and p != "."]:
        acc = os.path.join(acc, part)
        if os.path.lexists(acc):
            return True
    return False


def job_result_move_paths(job, to_user):
    """
    Return (src, dest, reason) for moving a job result folder to another user.

    reason is None when both paths are valid; otherwise a short skip code:
    none, missing, collision, invalid.
    """
    raw_result = (job.result or "").replace("\\", "/").strip()
    if not raw_result.strip("/"):
        return None, None, "none"
    folder = job_result_relpath(job)
    if not folder:
        return None, None, "invalid"
    raw_run = (job.run_dir or "").strip()
    if not raw_run or not os.path.isabs(raw_run):
        return None, None, "invalid"
    run_dir = os.path.realpath(raw_run)
    if not run_dir or not os.path.isdir(run_dir):
        return None, None, "invalid"
    src_root = os.path.realpath(os.path.join(run_dir, str(job.user_id)))
    dest_root = os.path.normpath(os.path.join(run_dir, str(getattr(to_user, "id", ""))))
    if not _is_under_root(src_root, run_dir) or not _is_under_root(dest_root, run_dir):
        return None, None, "invalid"
    src = _lexical_join(src_root, folder)
    dest = os.path.normpath(os.path.join(dest_root, folder))
    if not _is_under_root(src, src_root) or not _is_under_root(dest, dest_root):
        return None, None, "invalid"
    if src == dest:
        return src, dest, "none"
    if os.path.islink(src):
        return src, dest, "invalid"
    if not os.path.isdir(src):
        return src, dest, "missing"
    if os.path.lexists(dest) or _dest_prefix_conflict(dest, dest_root):
        return src, dest, "collision"
    return src, dest, None


def move_job_result_folder(job, to_user):
    """
    Move job.result from the current owner's folder to to_user's folder.

    Returns 'moved', 'missing', 'none', 'collision', or 'invalid'.
    Does not follow a final symlink. Uses rename when possible so dest
    cannot swallow src as a nested directory.
    """
    import errno
    import shutil

    src, dest, reason = job_result_move_paths(job, to_user)
    if reason:
        return reason
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.lexists(dest):
        return "collision"
    if os.path.islink(src):
        return "invalid"
    if not os.path.isdir(src):
        return "missing"
    try:
        os.rename(src, dest)
    except OSError as exc:
        if os.path.lexists(dest):
            return "collision"
        if getattr(exc, "errno", None) != errno.EXDEV:
            raise
        try:
            shutil.move(src, dest)
        except Exception:
            if os.path.lexists(src) and os.path.lexists(dest):
                shutil.rmtree(dest, ignore_errors=True)
            raise
    return "moved"


def traces_to_archive_paths(job, traces):
    """Resolve files-modal traces to (absolute paths, History tokens)."""
    paths = []
    tokens = []
    folder = (job.result or "").replace("\\", "/").strip("/")
    for trace in traces or []:
        trace = (trace or "").strip()
        if not trace:
            continue
        path = resolve_job_file(job, trace)
        if not path:
            continue
        rel = (decode_trace(trace) or os.path.basename(path)).replace("\\", "/")
        if folder and (rel == folder or rel.startswith(folder + "/")):
            rel = rel[len(folder):].lstrip("/")
        paths.append(path)
        tokens.append("{{{{History:{}-{}}}}}".format(job.id, rel))
    return paths, tokens


def history_tokens_to_archive_paths(user, raw, expected_job=None):
    """
    Parse {{History:id-rel}} tokens into archive paths.

    All tokens must belong to one writable job. Returns
    (job, paths, error_message).
    """
    from .services import HISTORY_TOKEN_RE, get_writable_job

    text = (raw or "").strip()
    if not text:
        return expected_job, [], "No files to archive."
    job = expected_job
    paths = []
    for hid_s, rel in HISTORY_TOKEN_RE.findall(text):
        rec = get_writable_job(user, int(hid_s))
        if rec is None:
            return expected_job, [], "Permission denied or job #{} not found.".format(hid_s)
        if job is None:
            job = rec
        elif job.id != rec.id:
            return expected_job, [], "Only files from the same job can be archived."
        root = result_dir(rec)
        if not root:
            return expected_job, [], "Job #{} has no result folder.".format(rec.id)
        rel = (rel or "").replace("\\", "/").lstrip("/")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            return expected_job, [], "Invalid file path in History token."
        root_real = os.path.realpath(root)
        full = os.path.realpath(os.path.join(root_real, *parts))
        if not _is_under_root(full, root_real):
            return expected_job, [], "File path is outside the job result folder."
        paths.append(full)
    if not paths:
        return expected_job, [], "No History:id-path tokens found."
    return job, paths, None


def clean_unlinked_job_folders(user):
    """
    Remove workspace subfolders that are not a live job result and not protected.

    Returns (detected, live_job_folders, failed).
    """
    import shutil

    from QueueDB.models import Job

    from .http import delegate_for

    if configured_workspace_base() is None:
        return None
    delegate = delegate_for(user)
    root = workspace_root_for(delegate)
    live = set(
        Job.objects.filter(user_id=delegate.id).exclude(result="").values_list("result", flat=True)
    )
    live.discard(None)
    detected = 0
    failed = 0
    if not os.path.isdir(root):
        return detected, len(live), failed
    try:
        names = os.listdir(root)
    except Exception:
        return detected, len(live), failed
    for name in names:
        if name in live or name in PROTECTED_WORKSPACE_FOLDERS:
            continue
        abs_path = os.path.join(root, name)
        if not os.path.isdir(abs_path):
            continue
        detected += 1
        try:
            if os.path.samefile(root, abs_path):
                failed += 1
                continue
            shutil.rmtree(abs_path)
        except Exception:
            failed += 1
    return detected, len(live), failed


def download_response(job, trace):
    path = resolve_job_file(job, trace)
    if not path:
        raise Http404("File not found")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=os.path.basename(path))


def preview_text(job, trace, max_bytes=2_000_000):
    """Read a job file as text for the preview modal (never returns FileResponse)."""
    path = resolve_job_file(job, trace)
    if not path:
        raise Http404("File not found")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(max_bytes)
    except Exception as exc:
        raise Http404(str(exc))


def preview_response(job, trace):
    path = resolve_job_file(job, trace)
    if not path:
        raise Http404("File not found")
    ctype, _ = mimetypes.guess_type(path)
    ctype = ctype or "application/octet-stream"
    # Prefer extension-based text mode so .bed/.sam/etc. are not FileResponse.
    if preview_mode_for(path, ctype) == "text" or any(
        ctype.startswith(prefix) or ctype == prefix.rstrip("/") for prefix in TEXT_TYPES
    ) or ctype.startswith("text/"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                body = fh.read(2_000_000)
        except Exception as exc:
            return HttpResponseBadRequest(str(exc))
        if not ctype.startswith("text/") and ctype not in (
            "application/json",
            "application/xml",
            "application/javascript",
        ):
            ctype = "text/plain"
        return HttpResponse(body, content_type="{}; charset=utf-8".format(ctype))
    response = FileResponse(open(path, "rb"), as_attachment=False, filename=os.path.basename(path))
    response["Content-Type"] = ctype
    response["Content-Disposition"] = 'inline; filename="{}"'.format(os.path.basename(path))
    return response


def preview_mode_for(name, ctype=""):
    lower = (name or "").lower()
    ctype = ctype or (mimetypes.guess_type(name or "")[0] or "")
    if ctype.startswith("image/") or lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return "img"
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml", "application/javascript") or lower.endswith(
        (".txt", ".log", ".err", ".csv", ".tsv", ".json", ".xml", ".yml", ".yaml", ".md", ".fa", ".fasta", ".fq", ".fastq", ".sam", ".bed", ".gtf", ".gff")
    ):
        return "text"
    if ctype == "application/pdf" or lower.endswith(".pdf"):
        return "iframe"
    if ctype in ("text/html", "application/xhtml+xml") or lower.endswith((".html", ".htm")):
        return "iframe"
    return "download"

"""BioQueue array parents: one non-executable job and one child per input.

The worker runs the children. When a child finishes, its result folder is
moved under the parent's. This module also folds child statuses back onto
the parent.
"""
from __future__ import annotations

import logging
import os
import shutil

from django.db.models import Count, Q
from django.utils import timezone

from QueueDB.models import Job, JobStatus

logger = logging.getLogger("BioQueue")

_OPEN = (JobStatus.WAITING, JobStatus.RUNNING, JobStatus.RESOURCELOCK)


def array_parent_status(statuses):
    """Status a parent should show for this set of child statuses."""
    statuses = list(statuses)
    if not statuses:
        return JobStatus.WAITING
    if any(status == JobStatus.RUNNING for status in statuses):
        return JobStatus.RUNNING
    if any(status == JobStatus.RESOURCELOCK for status in statuses):
        return JobStatus.RESOURCELOCK
    if any(status == JobStatus.WAITING for status in statuses):
        return JobStatus.WAITING
    if any(status == JobStatus.WRONG for status in statuses):
        return JobStatus.WRONG
    if any(status == JobStatus.INTERRUPTED for status in statuses):
        return JobStatus.INTERRUPTED
    if all(status == JobStatus.FINISHED for status in statuses):
        return JobStatus.FINISHED
    return JobStatus.WAITING


def _parent_event(previous, new_status):
    live = (JobStatus.RUNNING, JobStatus.RESOURCELOCK)
    if new_status in live and previous not in live:
        return "started"
    if new_status == JobStatus.FINISHED:
        return "finished"
    if new_status == JobStatus.WRONG:
        return "failed"
    if new_status == JobStatus.INTERRUPTED:
        return "interrupted"
    return None


def _result_parts(result):
    parts = [part for part in (result or "").replace("\\", "/").split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return None
    return parts


def child_result_segment(array_setting, job_id):
    """Folder name for one array child. A cluster range is not a folder name."""
    text = (array_setting or "").strip()
    if (
        text
        and text not in (".", "..")
        and "/" not in text
        and "\\" not in text
        and ".." not in text
    ):
        return text
    return str(job_id or "")


def child_result_name(parent_result, array_setting, job_id):
    parts = _result_parts(parent_result)
    segment = child_result_segment(array_setting, job_id)
    if not parts or not segment:
        return ""
    return "/".join(parts + [segment])


def array_child_result_name(job):
    """``parent_result/index`` for a child of a non-executable array parent."""
    parent_id = getattr(job, "parent_job_id", None)
    if not parent_id:
        return None
    try:
        parent = job.parent_job
    except Exception:
        return None
    if parent is None or getattr(parent, "is_executable", 1) != 0:
        return None
    name = child_result_name(parent.result, getattr(job, "array_setting", None), getattr(job, "id", None))
    return name or None


def _job_pk(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def sync_array_parent(job, *, mail_settings=None):
    """Write the parent's status from its children. Notify on a real transition.

    ``job`` may be a child or the array parent itself. Returns the new status,
    or None when ``job`` is not part of an array.
    """
    own_id = _job_pk(getattr(job, "id", None))
    executable = getattr(job, "is_executable", 1)
    if isinstance(executable, int) and not isinstance(executable, bool) and executable == 0 and own_id is not None:
        parent_id = own_id
    else:
        parent_id = _job_pk(getattr(job, "parent_job_id", None))
    if parent_id is None:
        return None
    parent = Job.objects.filter(pk=parent_id, is_executable=0).first()
    if parent is None:
        return None
    statuses = Job.objects.filter(parent_job_id=parent_id).values_list("status", flat=True)
    new_status = array_parent_status(statuses)
    previous = (
        Job.objects.filter(pk=parent_id, is_executable=0)
        .exclude(status=new_status)
        .values_list("status", flat=True)
        .first()
    )
    if previous is None:
        return new_status
    updated = Job.objects.filter(pk=parent_id, is_executable=0, status=previous).update(
        status=new_status,
        update_time=timezone.now(),
    )
    if not updated:
        return new_status
    event = _parent_event(previous, new_status)
    if event:
        try:
            from QueueDB.notifications import notify_job

            fresh = Job.objects.filter(pk=parent_id).first()
            if fresh is not None:
                notify_job(fresh, event, mail_settings=mail_settings)
        except Exception:
            pass
    return new_status


def result_abspath(user_folder, result_name):
    parts = _result_parts(result_name)
    if not parts:
        return None
    return os.path.join(user_folder, *parts)


def _abspath(path):
    return os.path.abspath(path) if path else ""


def _under(root, path):
    root_abs = _abspath(root)
    path_abs = _abspath(path)
    if not root_abs or not path_abs:
        return False
    return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)


def _same(left, right):
    return bool(left and right) and _abspath(left) == _abspath(right)


def _merge_tree(src, dest):
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(src):
        source = os.path.join(src, name)
        target = os.path.join(dest, name)
        if os.path.isdir(source) and not os.path.islink(source):
            _merge_tree(source, target)
            continue
        if os.path.lexists(target):
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
        shutil.move(source, target)


def _user_folder(job, parent):
    run_dir = (getattr(job, "run_dir", None) or getattr(parent, "run_dir", None) or "").strip()
    if not run_dir:
        return ""
    return os.path.join(os.path.abspath(run_dir), str(job.user_id))


def publish_child_outputs(child):
    """Move a finished array child's result folder under its parent.

    Returns the parent, or None when ``child`` is not an array task.
    The child's ``result`` is updated to ``{parent result}/{index}``.
    """
    child_id = _job_pk(getattr(child, "id", None)) or _job_pk(getattr(child, "job_id", None))
    if child_id is None:
        return None
    row = Job.objects.filter(pk=child_id).select_related("parent_job").first()
    if row is None:
        return None
    parent = row.parent_job if row.parent_job_id and getattr(row.parent_job, "is_executable", 1) == 0 else None
    if parent is None:
        return None
    dest_rel = child_result_name(parent.result, row.array_setting, row.id)
    if not dest_rel:
        return parent
    user_folder = _user_folder(row, parent)
    dest = result_abspath(user_folder, dest_rel) if user_folder else None
    src_rel = (row.result or "").replace("\\", "/").strip("/")
    src = result_abspath(user_folder, src_rel) if user_folder and src_rel else None
    parent_root = result_abspath(user_folder, parent.result) if user_folder else None
    if (
        dest
        and src
        and os.path.isdir(src)
        and not _same(src, dest)
        and _under(user_folder, src)
        and _under(user_folder, dest)
        and not (parent_root and (_same(src, parent_root) or _under(src, parent_root)))
    ):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.isdir(dest):
            _merge_tree(src, dest)
            shutil.rmtree(src, ignore_errors=True)
        else:
            shutil.move(src, dest)
    if (row.result or "").replace("\\", "/").strip("/") != dest_rel and dest and os.path.isdir(dest):
        Job.objects.filter(pk=row.id).update(result=dest_rel, update_time=timezone.now())
    return parent


def settle_finished_arrays(*, mail_settings=None):
    """Mark array parents whose children have all stopped, and publish outputs.

    Covers a parent left Waiting after its children finished in their own folders.
    """
    stuck = list(
        Job.objects.filter(is_executable=0, status__in=_OPEN)
        .annotate(
            n_children=Count("job"),
            n_open=Count("job", filter=Q(job__status__in=_OPEN)),
        )
        .filter(n_children__gt=0, n_open=0)
    )
    for parent in stuck:
        for child in Job.objects.filter(parent_job_id=parent.id):
            try:
                publish_child_outputs(child)
            except Exception:
                logger.exception("Failed to publish outputs for array task %s", child.id)
        try:
            sync_array_parent(parent, mail_settings=mail_settings)
        except Exception:
            logger.exception("Failed to update array parent %s", parent.id)

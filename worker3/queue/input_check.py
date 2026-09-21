"""Fail-fast checks for declared job input files.

History / CrossAccess / Uploaded tokens are expanded in Python (no remote size
probes). Existence is verified on the resolved local path. The synthetic step
is not part of the protocol list and must not change ``resume``.
"""
from __future__ import annotations

import os
import re

from worker3.step import _Step

_UNRESOLVED_TOKEN = re.compile(r"\{\{(?:Uploaded|History|CrossAccess):", re.IGNORECASE)
_REMOTE_SCHEME = re.compile(r"^(?:https?|ftp)://", re.IGNORECASE)


def non_empty_input_entries(job_input_files):
    """Return ``(1-based index, stripped path)`` for non-empty ``input_file`` slots."""
    entries = []
    for index, raw in enumerate(job_input_files or [], start=1):
        value = (raw or "").strip()
        if value:
            entries.append((index, value))
    return entries


def build_input_check_step(settings, n_slots=0):
    """Carrier step for preflight dependent_jobs; not a protocol resume slot."""
    del n_slots
    return _Step(
        software=_Step.SHELL_TAG,
        parameter="",
        specify_output="",
        md5_hex="input-preflight",
        env=None,
        force_local=1,
        version_check="",
        settings=settings,
    )


def is_remote_url(path):
    """True when *path* has an http(s)/ftp scheme, including localhost and uppercase."""
    return bool(_REMOTE_SCHEME.match((path or "").lstrip()))


def resolve_input_entry(raw, job):
    """Expand Uploaded / History / CrossAccess on a single ``input_file`` entry."""
    par = (raw or "").strip()
    if not par:
        return ""
    par, _ = _Step._upload_file_map(par, job.user_folder)
    par, _, _ = _Step._history_map(par, job.job_user)
    par, _, _ = _Step._cross_access_map(par, job.job_user)
    par, _ = _Step._upload_file_map(par, job.user_folder)
    return par.strip()


def bind_input_dependencies(step, job):
    """Attach History/CrossAccess parents without translating ``{{InputFile}}`` (no HTTP/FTP size GET)."""
    job_id = getattr(job, "job_id", None)
    for _, raw in non_empty_input_entries(job.job_input_files):
        if is_remote_url(raw):
            continue
        par = raw
        par, wait_h, _ = _Step._history_map(par, job.job_user)
        par, wait_c, _ = _Step._cross_access_map(par, job.job_user)
        for dep in wait_h.union(wait_c):
            if dep != job_id:
                step.add_dependent_jobs(dep)


def missing_local_inputs(job):
    """Resolved local paths (or original tokens) that do not exist on disk."""
    missing = []
    for _, raw in non_empty_input_entries(job.job_input_files):
        if is_remote_url(raw):
            continue
        resolved = resolve_input_entry(raw, job)
        if is_remote_url(resolved):
            continue
        if not resolved or _UNRESOLVED_TOKEN.search(resolved):
            missing.append(raw if not resolved else resolved)
            continue
        if not os.path.exists(resolved):
            missing.append(resolved)
    return missing

#!/usr/bin/env python
from __future__ import print_function
import inspect
import logging
import numbers
import os
import time

from django.utils import timezone

from QueueDB.models import Job, Training, _JS_RESOURCELOCK, _JS_RUNNING, _JS_WAITING
from worker.queue.constants import STEP_USER_INTERRUPTED

logger = logging.getLogger("BioQueue.cluster_support")


def _sync_job_status(job_id, status, wait_for=None):
    """Update Job.status for external-scheduler progress.

    Leave a status the user already set (interrupted, failed, finished).
    """
    try:
        fields = {"status": status, "update_time": timezone.now()}
        if wait_for is not None:
            fields["wait_for"] = wait_for
        owned = Job.objects.filter(
            id=job_id,
            status__in=(_JS_WAITING, _JS_RUNNING, _JS_RESOURCELOCK),
        ).update(**fields)
        return owned == 1
    except Exception as exc:
        logger.warning("cluster job %s status sync (%s): %s", job_id, status, exc)
        return False


def if_terminate(job_id):
    """
    Return True if this cluster submission should be cancelled.

    That is a stop flag, or a row the user already moved off Running
    (for example by resuming). On DB errors, returns False so we do not
    spuriously cancel cluster work.
    """
    try:
        job = Job.objects.get(id=job_id)
        # Resume clears ter and sets Waiting. This cluster job is the previous
        # run and must be cancelled before a new claim starts the step again.
        return bool(job.ter) or job.status not in (_JS_RUNNING, _JS_RESOURCELOCK)
    except Exception as e:
        logger.warning("if_terminate(%s): %s", job_id, e)
        return False


def get_cluster_models():
    """
    Get cluster modules
    :return: list, module names
    """
    models = []
    models_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'cluster_models')
    try:
        names = os.listdir(models_path)
    except OSError as e:
        logger.error("get_cluster_models: cannot list %s: %s", models_path, e)
        return models
    for model_name in names:
        if not model_name.endswith('.py') or model_name.startswith('_') or model_name.startswith('cluster'):
            continue
        models.append(model_name.replace('.py', ''))
    return models


def dispatch(cluster_type):
    """
    Load cluster module
    :param cluster_type: string
    :return: mixed, module or None
    """
    models = get_cluster_models()
    if cluster_type not in models:
        return None
    try:
        return __import__("worker.cluster_models." + cluster_type, fromlist=[cluster_type])
    except Exception as e:
        logger.error("dispatch(%r): %s", cluster_type, e)
        return None


def _with_extras(fn, *args, extras=None):
    """Pass extras= only when the backend accepts it. Do not swallow TypeError from the call."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    accepts_extras = "extras" in params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if extras is not None and accepts_extras:
        return fn(*args, extras=extras)
    return fn(*args)


def _maybe_fetch(cluster_model, cluster_id, extras):
    fetch = getattr(cluster_model, "fetch_results", None)
    if not callable(fetch):
        return True
    try:
        result = fetch(cluster_id, extras)
    except Exception:
        logger.exception("fetch_results failed for cluster job %s", cluster_id)
        return False
    if result is False:
        return False
    return True


def _store_scheduler_usage(cluster_model, cluster_id, trace_id, extras):
    """Persist scheduler telemetry without making telemetry failure fail the job."""
    query = getattr(cluster_model, "query_job_usage", None)
    if not callable(query):
        logger.warning(
            "cluster backend has no scheduler telemetry for training trace %s",
            trace_id,
        )
        return False
    try:
        usage = _with_extras(query, cluster_id, extras=extras)
        if not isinstance(usage, dict):
            raise ValueError("scheduler returned no usage payload")
        values = []
        for key in ("cpu", "mem", "vrt_mem"):
            value = usage.get(key)
            if not isinstance(value, numbers.Real):
                raise ValueError("scheduler usage %r is not numeric" % key)
            values.append(value)
        Training.objects.get(id=trace_id).update_cpu_mem(*values)
        return True
    except Exception as exc:
        logger.warning(
            "scheduler telemetry collection failed for trace %s: %s",
            trace_id,
            exc,
        )
        return False


def _poll_limit_seconds(extras):
    extras = extras or {}
    raw = extras.get("poll_max_seconds")
    try:
        if raw not in (None, ""):
            return max(60, int(raw))
    except (TypeError, ValueError):
        pass
    return 24 * 3600


def main(cluster_type, parameter, job_id, step_id, cpu, mem, vrt_mem, queue, workspace, log_path, wall_time='', learning=0, trace_id=0, extras=None):
    """
    Cluster support function
    :param cluster_type: string, cluster type, like TorquePBS
    :param parameter: string, job parameter
    :param job_id: int, job id
    :param step_id: int, step order
    :param cpu: int, cpu cores
    :param mem: string, allocate memory
    :param queue: string, queue name
    :param workspace: string, job path
    :param log_path: string, path to store job logs
    :param wall_time: string, CPU time limit for a job
    :param learning: int
    :param trace_id: int
    :param extras: dict, optional backend-specific overrides (GPU, array, remote, body)
    :return: int
    """
    cluster_model = dispatch(cluster_type)
    pending_tag = 0
    extras = dict(extras or {})
    extras["bq_job_id"] = job_id
    if not cluster_model:
        logger.error("Unknown cluster type: %r", cluster_type)
        return 1

    if extras.get("remote") and str(cluster_type or "").lower() != "slurm":
        logger.error(
            "Remote cluster execution is Slurm-only (got %r); refusing job %s",
            cluster_type,
            job_id,
        )
        return 1

    # Prefer extras.body so shell steps are inlined (not `bash /local/.bq_step_N.sh`)
    # for LSF / HTCondor / Torque as well as Slurm.
    submit_parameter = parameter
    body = extras.get("body")
    if isinstance(body, str) and body.strip():
        submit_parameter = body

    # Cluster jobs run the requested body directly. Resource learning comes
    # from the scheduler after completion; never embed this worker's Python or
    # ml_container.py path in a remote batch script.
    cluster_id = _with_extras(
        cluster_model.submit_job, submit_parameter, job_id, step_id, cpu, mem, vrt_mem, queue,
        log_path, wall_time, workspace, extras=extras)

    if not cluster_id:
        return 1

    # Keep the BioQueue job marked running while the external scheduler owns it.
    # Do not call Job.set_wait() here: that resets status to Waiting (0).
    _sync_job_status(job_id, _JS_RUNNING)

    unknown_streak = 0
    started = time.time()
    poll_limit = _poll_limit_seconds(extras)
    try:
        return _watch_cluster_job(
            cluster_model,
            cluster_type,
            cluster_id,
            job_id,
            learning,
            trace_id,
            extras,
            unknown_streak,
            started,
            poll_limit,
            pending_tag,
        )
    finally:
        _release_status_watch(cluster_model, cluster_id, extras)


def _release_status_watch(cluster_model, cluster_id, extras):
    """Stop asking about an id before a slow fetch. Safe to call twice."""
    release = getattr(cluster_model, "release_job_status", None)
    if not release or not cluster_id:
        return
    try:
        _with_extras(release, cluster_id, extras=extras)
    except Exception:
        logger.exception("release status watch for cluster job %s", cluster_id)


def _watch_cluster_job(
    cluster_model,
    cluster_type,
    cluster_id,
    job_id,
    learning,
    trace_id,
    extras,
    unknown_streak,
    started,
    poll_limit,
    pending_tag,
):
    while True:
        if time.time() - started > poll_limit:
            logger.error("cluster job %s exceeded poll window (%ss)", cluster_id, poll_limit)
            _release_status_watch(cluster_model, cluster_id, extras)
            _with_extras(cluster_model.cancel_job, cluster_id, extras=extras)
            _maybe_fetch(cluster_model, cluster_id, extras)
            return 1

        status_code = _with_extras(cluster_model.query_job_status, cluster_id, extras=extras)
        if status_code in (1, 2, 3):
            if status_code == 3:
                unknown_streak += 1
                if unknown_streak >= 10:
                    logger.error("cluster job %s vanished from scontrol/sacct", cluster_id)
                    _release_status_watch(cluster_model, cluster_id, extras)
                    _maybe_fetch(cluster_model, cluster_id, extras)
                    return 1
            else:
                unknown_streak = 0
            if status_code == 2 and pending_tag == 0:
                pending_tag = 1
                _sync_job_status(job_id, _JS_RESOURCELOCK, wait_for=5)

            if status_code == 1 and pending_tag == 1:
                pending_tag = 0
                _sync_job_status(job_id, _JS_RUNNING)

            if if_terminate(job_id):
                _release_status_watch(cluster_model, cluster_id, extras)
                _with_extras(cluster_model.cancel_job, cluster_id, extras=extras)
                _maybe_fetch(cluster_model, cluster_id, extras)
                break
            # Slurm blocks inside query_job_status until the shared poll is due.
            if str(cluster_type or "").lower() != "slurm":
                time.sleep(30)
        elif status_code == 0:
            _release_status_watch(cluster_model, cluster_id, extras)
            if learning == 1:
                _store_scheduler_usage(
                    cluster_model, cluster_id, trace_id, extras
                )
            if not _maybe_fetch(cluster_model, cluster_id, extras):
                return 1
            return 0
        else:
            _release_status_watch(cluster_model, cluster_id, extras)
            _maybe_fetch(cluster_model, cluster_id, extras)
            if if_terminate(job_id):
                return STEP_USER_INTERRUPTED
            return 1

    # User cancelled while job was queued/running on cluster.
    # Do not return 2: that is a normal process exit code.
    return STEP_USER_INTERRUPTED

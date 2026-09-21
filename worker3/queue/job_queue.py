"""In-memory job queue, DB fetch, scheduling, and step threads."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

import numpy as np
import psutil
from django.db.models import Q
from django.db import close_old_connections
from QueueDB.models import (
    Job,
    Reference,
    Slave,
    Training,
    _JS_WAITING,
    _JS_RESOURCELOCK,
    _JS_RUNNING,
    _JS_FINISHED,
    _JS_WRONG,
    _JS_INTERRUPTED,
)

from worker3 import bases
from worker3 import cluster_support
from worker3._bootstrap import PACKAGE_DIR
from worker3.queue.checkpoints import CheckPoints
from worker3.queue.process_runner import ProcessRunner
from worker3.queue.cluster_request import build_cluster_request, resolve_cluster_type
from worker3.queue.protocol import Protocol
from worker3.queue.task import Task
from worker3.queue.input_check import bind_input_dependencies, missing_local_inputs
from worker3.queue.constants import DEPENDENCY_WAIT_INTERVAL, PREDICT_BASE, PREDICT_LINEAR
from worker3.step import _Step

logger = logging.getLogger("BioQueue")

_ML_COLLECTOR = os.path.join(PACKAGE_DIR, "ml_collector.py")


def slave_key_from_settings(settings, override=None):
    """CLI override wins over ``env.slave`` / ``cluster.slave`` in config."""
    if override not in (None, ""):
        return str(override).strip()
    if not isinstance(settings, dict):
        return ""
    try:
        env = settings.get("env") or {}
        cluster = settings.get("cluster") or {}
        key = env.get("slave") or cluster.get("slave") or ""
    except Exception:
        return ""
    if key in (None, ""):
        return ""
    return str(key).strip()


SCHEDULE_GREEDY = "greedy"
SCHEDULE_FIFO = "fifo"
_VALID_SCHEDULES = (SCHEDULE_GREEDY, SCHEDULE_FIFO)


def normalize_schedule(value, default=SCHEDULE_GREEDY):
    if value in (None, ""):
        return default
    key = str(value).strip().lower()
    if key in _VALID_SCHEDULES:
        return key
    logger.warning("Unknown schedule %r, using %s", value, default)
    return default


def schedule_from_settings(settings, override=None):
    """CLI override wins over ``env.schedule`` in config. Default is greedy."""
    if override not in (None, ""):
        return normalize_schedule(override)
    if not isinstance(settings, dict):
        return SCHEDULE_GREEDY
    try:
        env = settings.get("env") or {}
        key = env.get("schedule") or ""
    except Exception:
        return SCHEDULE_GREEDY
    return normalize_schedule(key)


def normalize_predict_mode(value, default=PREDICT_LINEAR):
    if value in (None, ""):
        return default
    key = str(value).strip().lower()
    if key in (PREDICT_LINEAR, "size", "full"):
        return PREDICT_LINEAR
    if key in (PREDICT_BASE, "b", "intercept"):
        return PREDICT_BASE
    logger.warning("Unknown predict mode %r, using %s", value, default)
    return default


def predict_mode_from_settings(settings, override=None):
    """CLI override wins over ``ml.predict``. Default is linear (a + b * size)."""
    if override not in (None, ""):
        return normalize_predict_mode(override)
    if not isinstance(settings, dict):
        return PREDICT_LINEAR
    try:
        ml = settings.get("ml") or {}
        env = settings.get("env") or {}
        key = ml.get("predict") or env.get("predict") or ""
    except Exception:
        return PREDICT_LINEAR
    return normalize_predict_mode(key)


def lookup_slave(slave_key):
    if slave_key in (None, ""):
        return None
    key = str(slave_key).strip()
    qs = Slave.objects.filter(name=key)
    try:
        qs = Slave.objects.filter(Q(name=key) | Q(pk=int(key)))
    except (TypeError, ValueError):
        pass
    return qs.first()


def resolve_slave(slave_key):
    """Return the Slave row for a name or id, or raise ValueError."""
    if slave_key in (None, ""):
        return None
    found = lookup_slave(slave_key)
    if found is not None:
        return found
    available = list(Slave.objects.order_by("name").values_list("name", "id"))
    if available:
        hint = ", ".join("{} ({})".format(name, pk) for name, pk in available)
    else:
        hint = "(none)"
    raise ValueError("Unknown runner/slave {!r}. Known: {}".format(str(slave_key).strip(), hint))


def format_runner_list():
    rows = list(Slave.objects.order_by("name").values_list("id", "name", "comment"))
    if not rows:
        return "No runners (Slave records) found."
    lines = ["id\tname\tcomment"]
    for pk, name, comment in rows:
        summary = (comment or "").replace("\n", " ").strip()
        if len(summary) > 60:
            summary = summary[:57] + "..."
        lines.append("{}\t{}\t{}".format(pk, name, summary))
    return "\n".join(lines)


class JobQueue(object):
    def __init__(self, max_job, cpu_pool, memory_pool, disk_pool, work_dir, settings, n_retries=3, slave=None, schedule=None, predict=None):
        self._cpu_pool = cpu_pool
        self._memory_pool = memory_pool
        self._disk_pool = disk_pool
        self._workspace_root = work_dir
        self._max_concurrent_jobs = int(max_job) if max_job != "" else 0
        self._running_step_keys = set()
        self._job_resources = dict()
        self._active_step_count = 0
        self._queued_jobs = dict()
        self._lock = threading.RLock()
        self._is_queue_locked = 0
        self._failed_tasks = []
        self._db_fail_msg_tpl = "Cannot synchronize result to database for {job} ({operation})"
        self._slave_override = None if slave in (None, "") else str(slave).strip()
        self._schedule_override = None if schedule in (None, "") else str(schedule).strip()
        self._predict_override = None if predict in (None, "") else str(predict).strip()
        self._settings = self._with_predict_mode(settings)
        self._n_retries = 1
        self.n_retries = n_retries
        super(JobQueue, self).__init__()

    def dequeue(self, job, is_error=0):
        """
        Pop a job out of the queue and finish the following steps

        1.
        Parameters
        ----------
        job :

        Returns
        -------

        """
        with self._lock:
            if is_error == 2:
                job.db_obj.status = _JS_INTERRUPTED
                job.db_obj.ter = 0
            elif is_error:
                job.db_obj.status = _JS_WRONG
                job.db_obj.ter = 0
            else:
                job.db_obj.status = _JS_FINISHED
            self._save_job_with_retries(
                job.db_obj,
                operation="dequeue",
                on_failure=lambda: self._record_failed_task(self.dequeue, job, is_error),
            )
            try:
                self.remove_resources(job.job_id)
                if not is_error:
                    job.snapshot()
                bases.save_output_dict(job.file_map, job.job_id)
            except Exception as e:
                logger.exception(e)
            finally:
                self._queued_jobs.pop(job.job_id, None)

    def enqueue(self, job):
        """
        Put a job into queue and finish the following tasks

        1. create workdir if it's not exists
        2. initialize dict of job parameters
        3. push job into queue

        Parameters
        ----------
        job : Task
            A job instance

        Returns
        -------

        """
        job.prepare_workspace()
        job.initialize_job_parameters(ref_dict=self._get_user_references(job._user))

        with self._lock:
            self._queued_jobs[job.job_id] = job

    def refresh_runtime_settings(self, settings):
        """
        Refresh hot-reloadable runtime options from config.
        """
        if not self._usable_runtime_settings(settings):
            logger.warning("Invalid settings object, keeping previous value")
            return

        try:
            new_max_job = int(settings["env"]["max_job"]) if settings["env"]["max_job"] != "" else 0
        except (KeyError, TypeError, ValueError):
            logger.warning("Invalid env.max_job in settings, keeping previous value")
            return

        self._settings = self._with_predict_mode(settings)
        if new_max_job != self._max_concurrent_jobs:
            logger.info(
                "Updating max_job from %s to %s",
                self._max_concurrent_jobs,
                new_max_job,
            )
            self._max_concurrent_jobs = new_max_job

    @staticmethod
    def _usable_runtime_settings(settings):
        if not isinstance(settings, dict):
            return False
        try:
            env = settings["env"]
            cluster = settings["cluster"]
            if env["max_job"] != "":
                int(env["max_job"])
            env["workspace"]
            env["log"]
            cluster["type"]
        except (KeyError, TypeError, ValueError):
            return False
        return True

    def _with_predict_mode(self, settings):
        if not isinstance(settings, dict):
            return settings
        merged = dict(settings)
        ml = dict(merged.get("ml") or {})
        ml["predict"] = predict_mode_from_settings(merged, override=self._predict_override)
        merged["ml"] = ml
        return merged

    @property
    def slave_key(self):
        return slave_key_from_settings(self._settings, override=self._slave_override)

    @property
    def schedule_policy(self):
        return schedule_from_settings(self._settings, override=self._schedule_override)

    @property
    def predict_mode(self):
        return predict_mode_from_settings(self._settings, override=self._predict_override)

    def clean_dead_jobs(self):
        # Crash recovery for jobs this worker could have owned. A pinned runner
        # only fails jobs assigned to that runner. An unpinned worker only
        # sweeps unassigned jobs — never cluster jobs bound to another Slave.
        #
        # RESOURCELOCK is not a crash: the step never started. Put those back
        # to WAITING so a restart can continue at the same resume point.
        try:
            djs = Job.objects.filter(Q(status=_JS_RUNNING) | Q(status=_JS_RESOURCELOCK))
            key = self.slave_key
            if key:
                runner_filter = Q(slave__name=key)
                try:
                    runner_filter = runner_filter | Q(slave_id=int(key))
                except (TypeError, ValueError):
                    pass
                djs = djs.filter(runner_filter)
            else:
                djs = djs.filter(slave__isnull=True)
            for j in djs:
                if j.status == _JS_RESOURCELOCK:
                    logger.info(
                        "Job %s (%s) was waiting for resources; returning it to WAITING",
                        j.job_name,
                        j.id,
                    )
                    j.status = _JS_WAITING
                    j.save()
                    continue
                logger.warning(
                    "The status of job %s (%s) is %s, now BioQueue marks it as failed.",
                    j.job_name,
                    j.id,
                    j.get_status_display(),
                )
                j.status = _JS_WRONG
                j.save()
        except Exception as e:
            logger.exception(e)

    def queued_jobs_snapshot(self):
        """Shallow copy of the in-memory job id -> Task map for one scheduler tick."""
        return self._queued_jobs.copy()

    def get_queue(self):
        """Deprecated: use :meth:`queued_jobs_snapshot`."""
        return self.queued_jobs_snapshot()

    @property
    def scheduled_resources_sorted(self):
        """Per-job resource estimates for the scheduler, sorted for greedy dispatch."""
        return sorted(
            self._job_resources.items(),
            key=lambda x: x[1]["cpu"] if x[1]["cpu"] is not None else 100,
        )

    @property
    def get_resources(self):
        """Deprecated: use :attr:`scheduled_resources_sorted`."""
        return self.scheduled_resources_sorted

    @property
    def max_concurrent_jobs(self):
        """Maximum waiting jobs to pull from the DB per tick (from config ``env.max_job``)."""
        return self._max_concurrent_jobs

    @property
    def MAX_JOB(self):
        """Deprecated: use :attr:`max_concurrent_jobs`."""
        return self._max_concurrent_jobs

    @property
    def WORK_DIR(self):
        """Deprecated: worker workspace root path; prefer internal :attr:`_workspace_root` usage."""
        return self._workspace_root

    def set_resources(self, job, value):
        self._job_resources[job] = value

    def collect_schedulable_resources(self, job_table):
        sorted_jobs = {k: job_table[k] for k in sorted(job_table)}
        for job_id, job_obj in sorted_jobs.items():
            now_step = job_obj.get_current_step()
            if now_step is None or now_step.is_running:
                continue
            self.set_resources(job_id, now_step.resources)

    def _can_schedule_job(self, job_obj, resource, step_key):
        return not (
            job_obj.status > 0
            or step_key in self.running_table
            or resource["order"] > job_obj.resume
            or job_obj.steps[job_obj.resume].is_running
        )

    def _launch_step_thread(self, job_obj):
        # Mark the step running before the thread starts so one scheduler tick
        # cannot pick the same job twice.
        try:
            step_key = (job_obj.job_id, job_obj.resume)
            with self._lock:
                self._running_step_keys.add(step_key)
                if job_obj.resume < len(job_obj.steps):
                    job_obj.steps[job_obj.resume].is_running = 1
        except Exception:
            logger.exception("Failed to mark step running before launch")
        new_thread = threading.Thread(target=self.run_step, args=(job_obj,), daemon=True)
        new_thread.start()

    def _checkpoint_reason_for_resource(
        self,
        resource,
        host_cpu_available,
        host_memory_available,
        host_disk_free,
        budget_cpu,
        budget_memory,
        budget_disk,
    ):
        if self._resource_exceeds(resource.get("cpu"), host_cpu_available, budget_cpu):
            return CheckPoints.CPU
        if self._resource_exceeds(resource.get("mem"), host_memory_available, budget_memory):
            return CheckPoints.MEMORY
        if "disk" in resource and self._resource_exceeds(
            resource.get("disk"), host_disk_free, budget_disk
        ):
            return CheckPoints.DISK
        return None

    def _dispatch_resource_items(self):
        if self.schedule_policy == SCHEDULE_FIFO:
            return sorted(self._job_resources.items(), key=lambda item: item[0])
        return self.scheduled_resources_sorted

    def _with_resource_defaults(self, resource):
        """Replace unknown (None) cpu/mem/disk with conservative env defaults.

        Unknown steps used to lock the whole queue. Defaults let them share the
        worker with jobs that already have estimates.
        """
        resource = dict(resource or {})
        env = (self._settings or {}).get("env") or {}
        cluster = (self._settings or {}).get("cluster") or {}
        if resource.get("cpu") is None:
            try:
                resource["cpu"] = int(float(env.get("cpu") or cluster.get("cpu") or 1)) * 100
            except (TypeError, ValueError):
                resource["cpu"] = 100
        if resource.get("mem") is None:
            mem = env.get("memory") or cluster.get("mem") or ""
            try:
                resource["mem"] = int(float(mem))
            except (TypeError, ValueError):
                resource["mem"] = 1024 * 1024 * 1024
        if resource.get("disk") is None:
            resource["disk"] = 0
        for key in ("cpu", "mem", "disk"):
            value = resource.get(key)
            if value is None:
                continue
            try:
                if float(value) < 0:
                    resource[key] = 0
            except (TypeError, ValueError):
                resource[key] = 0
        return resource

    @staticmethod
    def _cap_to_budget(
        resource,
        budget_cpu,
        budget_memory,
        budget_disk,
        available_cpu=None,
        available_memory=None,
        available_disk=None,
    ):
        """If a forecast exceeds this machine, cap it. Waiting forever is a bad estimate.

        Ceiling is 95% of min(budget, currently available) so OS overhead cannot
        keep a capped job below the available check forever.
        """
        resource = dict(resource or {})
        for key, budget, available in (
            ("cpu", budget_cpu, available_cpu),
            ("mem", budget_memory, available_memory),
            ("disk", budget_disk, available_disk),
        ):
            required = resource.get(key)
            if required is None or budget in (None, 0):
                continue
            try:
                required_n = float(required)
                budget_n = float(budget)
            except (TypeError, ValueError):
                continue
            if required_n > budget_n > 0:
                ceiling = budget_n
                try:
                    if available is not None:
                        avail_n = float(available)
                        if avail_n > 0:
                            ceiling = min(ceiling, avail_n)
                except (TypeError, ValueError):
                    pass
                capped = ceiling * 0.95
                logger.warning(
                    "Capping %s forecast %s to 95%% of usable %s (budget %s)",
                    key,
                    required_n,
                    ceiling,
                    budget_n,
                )
                resource[key] = capped
        return resource

    def _write_back_resources(self, job_obj, job_id, resource):
        self.set_resources(job_id, resource)
        try:
            step = job_obj.steps[job_obj.resume]
            if isinstance(getattr(step, "resources", None), dict):
                step.resources.update(resource)
        except Exception:
            logger.exception("Failed to write capped resources back to job %s", job_id)

    def pick_next_job(
        self,
        job_table,
        host_cpu_available,
        host_memory_available,
        host_disk_free,
        budget_cpu,
        budget_memory,
        budget_disk,
    ):
        fifo = self.schedule_policy == SCHEDULE_FIFO
        biggest_cpu = None
        biggest_job = None

        for job_id, resource in self._dispatch_resource_items():
            job_obj = job_table.get(job_id)
            if job_obj is None:
                continue
            step_key = (job_id, job_obj.resume)
            resource = self._with_resource_defaults(resource)
            resource = self._cap_to_budget(
                resource,
                budget_cpu,
                budget_memory,
                budget_disk,
                available_cpu=host_cpu_available,
                available_memory=host_memory_available,
                available_disk=host_disk_free,
            )
            self._write_back_resources(job_obj, job_id, resource)

            if not self._can_schedule_job(job_obj, resource, step_key):
                continue

            checkpoint_reason = self._checkpoint_reason_for_resource(
                resource=resource,
                host_cpu_available=host_cpu_available,
                host_memory_available=host_memory_available,
                host_disk_free=host_disk_free,
                budget_cpu=budget_cpu,
                budget_memory=budget_memory,
                budget_disk=budget_disk,
            )
            if checkpoint_reason is not None:
                job_obj.set_checkpoint_info(checkpoint_reason)
                if fifo:
                    return None, False
                continue
            if fifo:
                return job_obj, False
            cpu = resource.get("cpu")
            if cpu is None:
                cpu = 0
            if biggest_cpu is None or biggest_cpu < cpu:
                biggest_cpu = cpu
                biggest_job = job_obj

        return biggest_job, False

    def remove_resources(self, job):
        if job in self._job_resources:
            del self._job_resources[job]

    @property
    def running_jobs(self):
        return len(self._queued_jobs)

    @property
    def running_steps(self):
        return self._active_step_count

    @property
    def running_table(self):
        return self._running_step_keys

    @property
    def is_queue_locked(self):
        with self._lock:
            return self._is_queue_locked

    @is_queue_locked.setter
    def is_queue_locked(self, value):
        with self._lock:
            self._is_queue_locked = bool(value)

    @property
    def n_retries(self):
        return self._n_retries

    @n_retries.setter
    def n_retries(self, value):
        try:
            if int(value) > 0:
                self._n_retries = int(value)
            else:
                self._n_retries = 1
        except (TypeError, ValueError):
            self._n_retries = 1

    def _record_failed_task(self, fn, *args):
        with self._lock:
            self._failed_tasks.append((fn, args))

    def retry_failed_tasks(self):
        """Re-run DB operations that failed after exhausting retries on a previous tick."""
        with self._lock:
            pending = self._failed_tasks
            self._failed_tasks = []
        for fn, args in pending:
            try:
                fn(*args)
            except Exception:
                logger.exception("Retry of failed task %s raised", getattr(fn, "__name__", fn))

    def _save_job_with_retries(self, job_obj, operation, on_failure=None):
        for attempt in range(self.n_retries):
            try:
                job_obj.save()
                return True
            except Exception as e:
                logger.warning(self._db_fail_msg_tpl.format(job=getattr(job_obj, "id", "unknown"), operation=operation))
                logger.warning(e)
                if attempt + 1 < self.n_retries:
                    time.sleep(1)
        if on_failure is not None:
            on_failure()
        return False

    def _get_user_references(self, user):
        """

        Parameters
        ----------
        user_id :

        Returns
        -------

        @ todo: there's a conflict between user's ref and global ref, keep user's
        @ todo: cache queries?
        """
        results = Reference.objects.filter(Q(user=user) | Q(user=None)).order_by("user_id")
        refs = {}
        for ref in results:
            refs[ref.name] = ref.path
        return refs

    def _update_resource_pool(self, resource_dict, direction=1):
        """
        Update resource pool

        Parameters
        ----------
        cpu :
        mem :
        disk :

        Returns
        -------

        """
        with self._lock:
            if resource_dict["cpu"] is not None:
                self._cpu_pool += resource_dict["cpu"] * direction
            if resource_dict["mem"] is not None:
                self._memory_pool += resource_dict["mem"] * direction
            if resource_dict["disk"] is not None:
                self._disk_pool += resource_dict["disk"] * direction
        return self._cpu_pool, self._memory_pool, self._disk_pool

    def _parse_api_job(self, job_db_obj):
        protocol = Protocol(poj=job_db_obj.protocol, settings=self._settings)
        p_ver = job_db_obj.protocol_ver
        if p_ver != protocol.ver:
            logger.warning(
                "Job {job_id} is trying to use an outdated protocol (pid: {pid}, asked version: {av}, real version: {rv})".format(
                    job_id=job_db_obj.id, pid=job_db_obj.protocol.id, av=p_ver, rv=protocol.ver))
        return Task(job_obj=job_db_obj, protocol=protocol, settings=self._settings)

    def _slave_match_filter(self):
        key = self.slave_key
        if key in (None, ""):
            return None
        runner = lookup_slave(key)
        if runner is not None:
            return Q(slave=runner)
        match = Q(slave__name=key)
        try:
            match = match | Q(slave_id=int(key))
        except (TypeError, ValueError):
            pass
        return match

    def _apply_slave_filter(self, qs):
        slave_filter = self._slave_match_filter()
        if slave_filter is None:
            return qs.filter(slave__isnull=True)
        return qs.filter(slave_filter)

    def _waiting_job_queryset(self):
        qs = Job.objects.filter(status=_JS_WAITING, locked=0, is_executable=1)
        return self._apply_slave_filter(qs)

    def _claim_waiting_job(self, job):
        qs = Job.objects.filter(
            id=job.id,
            status=_JS_WAITING,
            locked=0,
            is_executable=1,
        )
        return self._apply_slave_filter(qs).update(status=_JS_RUNNING) == 1

    def fetch_jobs(self, n_jobs=None):
        if n_jobs is None:
            n_jobs = self._max_concurrent_jobs - self.running_jobs
        try:
            n_jobs = int(n_jobs)
        except (TypeError, ValueError):
            logger.error("Invalid n_jobs=%r when fetching jobs", n_jobs)
            return
        if n_jobs <= 0:
            return
        try:
            jobs = list(self._waiting_job_queryset().order_by("id")[:n_jobs])
        except Exception as e:
            jobs = None
            logger.error("Error occurred when fetching new jobs from the database")
            logger.error(e)

        if jobs is not None and len(jobs) > 0:
            for job in jobs:
                if job.id in self._queued_jobs:
                    continue
                if not self._claim_waiting_job(job):
                    continue
                try:
                    t_job = self._parse_api_job(job_db_obj=job)
                    # Keep the in-memory Task.status at WAITING for scheduling, but
                    # sync the ORM instance so later save() calls do not revert the claim.
                    job.status = _JS_RUNNING
                    self.enqueue(t_job)
                except Exception:
                    logger.exception("Failed to enqueue claimed job %s; returning it to WAITING", job.id)
                    try:
                        Job.objects.filter(id=job.id, status=_JS_RUNNING).update(status=_JS_WAITING)
                    except Exception:
                        logger.exception("Failed to unclaim job %s", job.id)

    def query_job_status(self, job_id):
        for _ in range(self.n_retries):
            try:
                return Job.objects.get(id=job_id).status
            except Exception as e:
                logger.warning(f"Failed to query dependent job status for job id {job_id}")
                logger.warning(e)
                time.sleep(1)
        return None

    def forecast_step(self, step, job=None):
        """
        Before the running of a step
        :param job_id: int, job id
        :param step_order: int, step order
        :param resources: dictionary, resources required by the step
        :return: If system resources is not enough for the step, it will return False, otherwise, it returns True
        """
        rollback = 0
        cluster = self._settings.get("cluster") or {}
        # Slave.cluster_manager can imply Slurm even when cluster.type is empty.
        on_cluster = bool(resolve_cluster_type(cluster, job) or cluster.get("type"))

        if not on_cluster:
            # for running on local machine
            if step.resources is not None and step.resources["cpu"] is not None and np.isnan(step.resources["cpu"]):
                return False
            new_cpu, new_mem, new_disk = self._update_resource_pool(step.resources, -1)

            if new_cpu < 0 or new_mem < 0 or new_disk < 0:
                rollback = 1

        if not rollback:
            return True
        else:
            if not on_cluster:
                self._update_resource_pool(step.resources)
            return False

    @staticmethod
    def kill_proc(proc):
        """
        Kill a process and its children processes
        :param proc: Process class defined in psutil
        :return: None
        """
        try:
            children = proc.children()
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            gone, still_alive = psutil.wait_procs(children, timeout=3)
            for p in still_alive:
                p.kill()
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

    @staticmethod
    def _coerce_int(value, default=1):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _reap_process(self, proc, timeout=30):
        if proc is None:
            return
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                JobQueue.kill_proc(psutil.Process(proc.pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                return
            except Exception:
                logger.exception("Failed to stop auxiliary process pid %s", getattr(proc, "pid", None))

    @staticmethod
    def _append_job_log(path, text):
        if not text.endswith("\n"):
            text = text + "\n"
        try:
            with open(path, "a") as fh:
                fh.write(text)
        except OSError:
            logger.exception("Failed to write job log %s", path)

    def _fail_input_check(self, job_obj, log_file, errlog_file, message):
        logger.error("Job %s input check failed: %s", job_obj.job_id, message.strip())
        self._append_job_log(log_file, message)
        self._append_job_log(errlog_file, message)
        self.dequeue(job_obj, is_error=1)

    def _run_input_preflight(self, job_obj, log_file, errlog_file):
        """Validate declared inputs before protocol step 0. Returns False if the job was failed."""
        if getattr(job_obj, "resume", 0) != 0:
            return True
        step = getattr(job_obj, "input_check_step", None)
        if not isinstance(step, _Step):
            return True
        bind_input_dependencies(step, job_obj)
        n_inputs = len([raw for raw in (job_obj.job_input_files or []) if (raw or "").strip()])
        self._append_job_log(
            log_file,
            "Checking {n} input file(s) before launch.\n".format(n=n_inputs),
        )
        if len(step.dependent_jobs) > 0 and not self._dependencies_are_ready(job_obj, step):
            ids = ", ".join(str(dep) for dep in sorted(step.dependent_jobs))
            self._fail_input_check(
                job_obj,
                log_file,
                errlog_file,
                "Input check failed: History/CrossAccess parent job is not runnable ({ids}).".format(
                    ids=ids
                ),
            )
            return False
        missing = missing_local_inputs(job_obj)
        if missing:
            lines = ["Input check failed: missing file(s):"] + ["  " + path for path in missing]
            self._fail_input_check(job_obj, log_file, errlog_file, "\n".join(lines))
            return False
        return True

    def _dependencies_are_ready(self, job_obj, step_obj):
        terminal_fail = {_JS_WRONG, _JS_INTERRUPTED}
        for sd in step_obj.dependent_jobs:
            while True:
                dep_status = self.query_job_status(job_id=sd)
                if dep_status == _JS_FINISHED:
                    break
                if dep_status is None or dep_status in terminal_fail:
                    logger.error(
                        "Dependent job %s is not runnable (status=%s); failing %s",
                        sd,
                        dep_status,
                        job_obj.job_id,
                    )
                    return False
                job_obj.set_checkpoint_info(checkpoint=CheckPoints.DEPENDENCE)
                time.sleep(DEPENDENCY_WAIT_INTERVAL)
        return True

    @staticmethod
    def _resource_exceeds(required, available, total):
        """
        Check if a required resource exceeds currently available/total values.
        None means "unknown/unlimited" and should not block scheduling.
        """
        if required is None:
            return False
        return required > available or required > total

    def finish_step(self, job, is_error=0):
        """

        Parameters
        ----------
        job : Task

        is_error :

        Returns
        -------

        """
        resource = job.steps[job.resume].resources
        self._update_resource_pool(resource)

        if is_error:
            # step went wrong or job got terminated
            try:
                if resource.get("trace") is not None:
                    try:
                        training = Training.objects.get(id=resource['trace'])
                        training.delete()
                    except Exception as e:
                        logger.exception(e)
                self.dequeue(job, is_error=is_error)
            except Exception as e:
                logger.exception(e)
        else:
            try:
                job.resume += 1
                job.db_obj.resume = job.resume
                logger.info(f"Synchronizing resume info {job.resume} for job {job.job_id} to the database")
                job.db_obj.save()
            except Exception as e:
                logger.error(f"Failed to update step status record for {job.job_id} ({job.resume}), details:")
                logger.exception(e)

            job.update_job_file_mapping()
            if "trace" in resource and resource["trace"] is not None:
                try:
                    training = Training.objects.get(id=resource['trace'])
                    training.output = job.output_size
                    training.lock = 0
                    training.save()
                except Exception as e:
                    logger.error(f"Failed to update training record ({resource['trace']}) for {job.job_id} ({job.resume}), details:")
                    logger.exception(e)

            if job.resume >= len(job.steps):
                self.dequeue(job)

    def _run_step_cluster(self, job, stdout_to, stderr_to):
        # for cluster
        step_obj = job.steps[job.resume]
        cluster = self._settings.get("cluster") or {}
        cluster_cpu_cap = self._coerce_int(cluster.get("cpu"), default=1)
        if step_obj.resources['cpu'] is None:
            allocate_cpu = cluster_cpu_cap
        else:
            from math import ceil
            predict_cpu = int(ceil(round(step_obj.resources['cpu']) / 100))
            if predict_cpu > cluster_cpu_cap or predict_cpu == 0:
                allocate_cpu = cluster_cpu_cap
            else:
                allocate_cpu = predict_cpu
        if 'mem' not in step_obj.resources or step_obj.resources['mem'] is None:
            allocate_mem = cluster.get("mem")
        else:
            allocate_mem = bases.bytes_to_readable(step_obj.resources['mem'])
        if 'vrt_mem' not in step_obj.resources or step_obj.resources['vrt_mem'] is None:
            allocate_vrt = cluster.get("vrt")
        else:
            allocate_vrt = bases.bytes_to_readable(step_obj.resources['vrt_mem'])

        queue_name = cluster.get("new_queue", "")
        walltime = cluster.get("walltime", "")
        body = None
        if getattr(step_obj, "is_shell", False):
            script_path = step_obj.write_shell_script(job.run_folder, job.resume)
            cluster_cmd = "bash %s" % script_path
            try:
                with open(script_path) as script_handle:
                    body = script_handle.read()
            except OSError:
                body = None
        else:
            cluster_cmd = " ".join(step_obj.command)
            body = cluster_cmd

        request = build_cluster_request(
            job,
            step_obj,
            cluster,
            allocate_cpu,
            allocate_mem,
            allocate_vrt,
            queue_name,
            walltime,
        )
        extras = request["extras"]
        extras["body"] = body
        extras["fetch_dest"] = job.run_folder
        extras["fetch_log"] = stdout_to
        extras["fetch_err"] = stderr_to
        cluster_type = request.get("cluster_type") or resolve_cluster_type(cluster, job) or cluster.get("type")
        allocate_cpu = request["cpu"]
        allocate_mem = request["mem"]
        allocate_vrt = request["vrt"]
        queue_name = request["queue"]
        walltime = request["walltime"]

        if "trace" in step_obj.resources:
            return_code = cluster_support.main(cluster_type, cluster_cmd,
                                               job.job_id, job.resume, allocate_cpu, allocate_mem, allocate_vrt,
                                               queue_name, job.run_folder,
                                               stdout_to, walltime, 1, step_obj.resources["trace"], extras=extras)
        else:
            return_code = cluster_support.main(cluster_type, cluster_cmd,
                                               job.job_id, job.resume, allocate_cpu, allocate_mem, allocate_vrt,
                                               queue_name, job.run_folder,
                                               stdout_to, walltime, extras=extras)

        return return_code

    def _run_step_local(self, job, stdout_to, stderr_to):
        """

        Parameters
        ----------
        job : Task
            Task object
        stdout_to : str

        stderr_to : str


        Returns
        -------

        """
        # for local environment or cloud
        logger.info("Now run {job_id} - {step_id}".format(job_id=job.job_id, step_id=job.resume))
        logger.info("Resource pool: CPU {cpu}, Memory {mem}, Disk {disk}".format(cpu=self._cpu_pool,
                                                                                 mem=self._memory_pool,
                                                                                 disk=self._disk_pool))
        runner = ProcessRunner(n_retries=self.n_retries, kill_process_fn=JobQueue.kill_proc)

        if os.path.exists(self._settings["env"]["log"]):
            with open(stdout_to, "a") as log_file_handler:
                with open(stderr_to, "a") as err_file_handler:
                    learn_process = None
                    try:
                        step_obj = job.steps[job.resume]
                        logger.info(step_obj.command)
                        runner.record_version(step_obj=step_obj, job=job)
                        step_process = runner.spawn_step(
                            step_obj=step_obj,
                            run_folder=job.run_folder,
                            log_file_handler=log_file_handler,
                            err_file_handler=err_file_handler,
                            step_index=job.resume,
                        )
                        if "learn" in step_obj.resources and step_obj.resources["learn"] == 1:
                            training = Training(step_hash=step_obj._md5_hex, input=job.input_size, lock=1)
                            training.save()
                            trace_id = training.id
                            step_obj.resources["trace"] = trace_id
                            learn_process = subprocess.Popen(
                                [sys.executable, _ML_COLLECTOR,
                                 "-p", str(step_process.pid), "-n",
                                 step_obj.md5_hex,
                                 "-j", str(trace_id)],
                                shell=False, stdout=None,
                                stderr=subprocess.STDOUT)
                        rc = runner.wait_for_completion(step_process=step_process, job_id=job.job_id)
                        logger.info("Now job {job_id} - {step_id} finished ({rc})".format(job_id=job.job_id,
                                                                                          step_id=job.resume,
                                                                                          rc=rc))
                        return rc
                    except Exception as e:
                        logger.info(
                            "Job {job_id} - {step_id} failed".format(job_id=job.job_id, step_id=job.resume))
                        logger.exception(e)
                        log_file_handler.write(str(e)+"\n")
                        return 1
                    finally:
                        self._reap_process(learn_process)
        return 1

    def run_step(self, job_obj):
        close_old_connections()
        current_job_id = job_obj.job_id
        step_obj = job_obj.steps[job_obj.resume]
        step_key = (current_job_id, job_obj.resume)
        step_started = False
        reserved = False
        finished = False
        with self._lock:
            step_obj.is_running = 1
            self._running_step_keys.add(step_key)

        try:
            if not os.path.exists(self._settings["env"]["log"]):
                logger.error("Cannot access {path}".format(path=self._settings["env"]["log"]))
                self.finish_step(job_obj, is_error=1)
                return

            if not os.path.exists(job_obj.run_folder):
                raise IOError("Cannot write content to {dest}".format(dest=job_obj.run_folder))

            log_file = os.path.join(self._settings["env"]["log"], "{job_id}.log".format(job_id=job_obj.job_id))
            errlog_file = os.path.join(self._settings["env"]["log"], "{job_id}.err".format(job_id=job_obj.job_id))

            if not self._run_input_preflight(job_obj, log_file, errlog_file):
                finished = True
                return

            recheck = self.forecast_step(step_obj, job_obj)
            reserved = recheck is True

            if not reserved:
                return

            if len(step_obj.dependent_jobs) > 0 and not self._dependencies_are_ready(job_obj, step_obj):
                self.finish_step(job_obj, is_error=1)
                finished = True
                return

            with self._lock:
                self._active_step_count += 1
                step_started = True
            try:
                job_obj.db_obj.status = _JS_RUNNING
                job_obj.db_obj.resume = job_obj.resume
                self._save_job_with_retries(job_obj.db_obj, operation="update step status")
            except Exception as e:
                logger.warning(f"Unexpected failure while preparing DB state for {current_job_id}")
                logger.warning(e)

            cluster_type = resolve_cluster_type(self._settings.get("cluster") or {}, job_obj)
            if cluster_type and not step_obj.force_local:
                rc = self._run_step_cluster(job_obj, log_file, errlog_file)
            else:
                logger.info(f"Projected resource usage: {step_obj.resources}")
                rc = self._run_step_local(job_obj, log_file, errlog_file)

            if rc == 2:
                self.finish_step(job_obj, is_error=2)
            elif rc != 0:
                self.finish_step(job_obj, is_error=1)
            else:
                self.finish_step(job_obj, is_error=0)
            finished = True
        except Exception as e:
            logger.error("Error triggered by job {job_id} step {step_id}".format(job_id=current_job_id,
                                                                                 step_id=job_obj.resume))
            logger.exception(e)
            if reserved and not finished:
                try:
                    self.finish_step(job_obj, is_error=1)
                except Exception:
                    logger.exception("Failed to fail job %s after step error", current_job_id)
                    try:
                        self._update_resource_pool(step_obj.resources)
                    except Exception:
                        logger.exception("Failed to restore resource pool for job %s", current_job_id)
        finally:
            close_old_connections()
            with self._lock:
                self._running_step_keys.discard(step_key)
                if step_started and self._active_step_count > 0:
                    self._active_step_count -= 1
                step_obj.is_running = 0
            self.is_queue_locked = False

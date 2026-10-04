"""Blocking main loop: load config, poll DB, dispatch one step per tick."""
import logging
import time

from django.db import connections
from django.db.utils import DatabaseError, InterfaceError, OperationalError

from worker import bases
from worker.queue.constants import MAX_MAIN_LOOP_BACKOFF, PREDICT_BASE, SCHEDULER_LOOP_INTERVAL
from worker.queue.job_queue import (
    JobQueue,
    predict_mode_from_settings,
    resolve_slave,
    schedule_from_settings,
    slave_key_from_settings,
)

logger = logging.getLogger("BioQueue")


def validate_worker_settings(settings):
    required_paths = [
        ("env", "workspace"),
        ("env", "log"),
        ("env", "max_job"),
        ("cluster", "type"),
    ]
    for section, key in required_paths:
        if section not in settings or key not in settings[section]:
            logger.error(f"Invalid settings: missing '{section}.{key}'")
            return 0
    cluster_type = settings.get("cluster", {}).get("type")
    if cluster_type:
        for key in ("cpu", "mem", "vrt", "new_queue", "walltime"):
            if key not in settings["cluster"]:
                logger.error(f"Invalid settings: missing 'cluster.{key}'")
                return 0
    return 1


check_settings = validate_worker_settings


def run_worker_main(n_retries=3, slave=None, schedule=None, predict=None):
    logger.info("Initiating BioQueue worker")
    settings = bases.get_all_config()
    assert validate_worker_settings(settings), "Settings is not valid"
    cli_slave = None if slave in (None, "") else str(slave).strip()
    slave_key = slave_key_from_settings(settings, override=cli_slave)
    try:
        runner = resolve_slave(slave_key)
    except ValueError:
        logger.exception("Invalid runner/slave %r", slave_key)
        raise
    if runner is not None:
        logger.info("Worker bound to runner %s (id=%s)", runner.name, runner.id)
    policy = schedule_from_settings(settings, override=schedule)
    logger.info("Dispatch policy: %s", policy)
    predict_mode = predict_mode_from_settings(settings, override=predict)
    if predict_mode == PREDICT_BASE:
        logger.info("Resource prediction: base (intercept only)")
    else:
        logger.info("Resource prediction: linear (intercept + slope * size)")
    # check configuration
    initial_cpu_budget, initial_memory_budget, initial_disk_budget, _initial_vrt_budget = bases.get_init_resource()
    job_queue = JobQueue(
        max_job=settings["env"]["max_job"],
        cpu_pool=initial_cpu_budget,
        memory_pool=initial_memory_budget,
        disk_pool=initial_disk_budget,
        work_dir=settings["env"]["workspace"],
        settings=settings,
        n_retries=n_retries,
        slave=runner.name if cli_slave and runner is not None else cli_slave,
        schedule=schedule,
        predict=predict,
    )
    job_queue.clean_dead_jobs()
    consecutive_failures = 0

    while True:
        try:
            settings = bases.get_all_config()
            job_queue.refresh_runtime_settings(settings)
            host_cpu_available = bases.get_cpu_available()
            host_memory_available, _host_vrt_available = bases.get_memo_usage_available()
            host_disk_free = bases.get_disk_free(settings["env"]["workspace"])

            job_queue.retry_failed_tasks()
            job_queue.fetch_jobs()
            job_table = job_queue.queued_jobs_snapshot()
            job_queue.collect_schedulable_resources(job_table)

            if job_queue.is_queue_locked:
                time.sleep(1)
                continue

            while True:
                biggest_job, queue_locked = job_queue.pick_next_job(
                    job_table=job_table,
                    host_cpu_available=host_cpu_available,
                    host_memory_available=host_memory_available,
                    host_disk_free=host_disk_free,
                    budget_cpu=initial_cpu_budget,
                    budget_memory=initial_memory_budget,
                    budget_disk=initial_disk_budget,
                )
                if queue_locked:
                    break
                if biggest_job is None:
                    break
                job_queue._launch_step_thread(biggest_job)
                try:
                    res = biggest_job.steps[biggest_job.resume].resources or {}
                except Exception:
                    res = {}
                host_cpu_available -= res.get("cpu") or 0
                host_memory_available -= res.get("mem") or 0
                host_disk_free -= res.get("disk") or 0
            consecutive_failures = 0
            time.sleep(SCHEDULER_LOOP_INTERVAL)
        except Exception as e:
            logger.exception(e)
            consecutive_failures += 1
            backoff_seconds = min(MAX_MAIN_LOOP_BACKOFF, 2 ** min(consecutive_failures, 6))
            if isinstance(e, (DatabaseError, OperationalError, InterfaceError)):
                logger.warning("Database error detected, closing Django connections before retry")
                try:
                    connections.close_all()
                except Exception:
                    logger.exception("Failed to close Django DB connections cleanly")
            logger.warning(f"Worker loop backing off for {backoff_seconds}s (failure #{consecutive_failures})")
            time.sleep(backoff_seconds)


# Drop-in name for code that expects ``main`` from the legacy monolith
main = run_worker_main

"""Run one dummy echo job through JobQueue against a file-backed SQLite DB."""
from __future__ import annotations

import os
import shutil
import sys
from configparser import ConfigParser
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = Path(__file__).resolve().parent
_TESTDATA = _PACKAGE_DIR / ".testdata"


def _prepare_testdata():
    if _TESTDATA.exists():
        shutil.rmtree(_TESTDATA)
    workspace = _TESTDATA / "workspace"
    log_dir = _TESTDATA / "log"
    outputs = _TESTDATA / "outputs"
    workspace.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    outputs.mkdir(parents=True)

    conf_path = _TESTDATA / "custom.conf"
    config = ConfigParser()
    config["env"] = {
        "workspace": str(workspace),
        "log": str(log_dir),
        "outputs": str(outputs),
        "max_job": "4",
        "cpu": "2",
        "memory": "1024",
        "disk_quota": "1024",
    }
    config["ml"] = {
        "confidence_weight_disk": "1",
        "confidence_weight_mem": "1",
        "confidence_weight_cpu": "0.8",
        "threshold": "0.5",
    }
    config["cluster"] = {"type": "", "cpu": "1", "mem": "1G", "vrt": "1G", "walltime": ""}
    with conf_path.open("w") as fh:
        config.write(fh)

    os.environ["BIOQUEUE_CUSTOM_CONF"] = str(conf_path)
    os.environ["DJANGO_SETTINGS_MODULE"] = "worker.sqlite_settings"
    return workspace, log_dir


def main() -> int:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    workspace, log_dir = _prepare_testdata()

    import worker._bootstrap  # noqa: F401
    import worker.sqlite_settings  # noqa: F401
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", run_syncdb=True, interactive=False, verbosity=0)

    from QueueDB.models import Job, JobStatus

    from worker.queue.job_queue import JobQueue
    from worker.testing import ECHO_MARKER, disable_ml_collector, seed_echo_job, worker_settings

    job = seed_echo_job(str(workspace))
    job_id = job.id
    settings = worker_settings(str(workspace), str(log_dir))
    queue = JobQueue(
        max_job=4,
        cpu_pool=10000,
        memory_pool=10 * 1024 ** 3,
        disk_pool=10 * 1024 ** 3,
        work_dir=str(workspace),
        settings=settings,
        n_retries=1,
    )
    queue.fetch_jobs()
    queued = queue.queued_jobs_snapshot()
    if job_id not in queued:
        print("smoke: job was not fetched into the queue", file=sys.stderr)
        return 1

    task = queued[job_id]
    disable_ml_collector(task)
    queue.set_resources(job_id, task.steps[0].resources)
    queue.run_step(task)

    job = Job.objects.get(id=job_id)
    log_path = log_dir / "{}.log".format(job_id)
    log_text = log_path.read_text() if log_path.exists() else ""
    if job.status != JobStatus.FINISHED:
        print(
            "smoke: expected FINISHED, got {} (log={!r})".format(job.status, log_text),
            file=sys.stderr,
        )
        return 1
    if ECHO_MARKER not in log_text:
        print("smoke: marker missing from log: {!r}".format(log_text), file=sys.stderr)
        return 1

    print("smoke: job {} finished; log contains {}".format(job_id, ECHO_MARKER))
    return 0


if __name__ == "__main__":
    sys.exit(main())

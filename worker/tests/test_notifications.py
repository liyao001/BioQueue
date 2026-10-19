"""Worker call sites for job notification hooks."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from worker.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    try:
        from django.test import TestCase

        from QueueDB.models import JobStatus
        from QueueDB.protocol_template import ProtocolTemplateError
        from worker.queue.job_queue import JobQueue
        from worker.testing import disable_ml_collector, seed_echo_job, worker_settings
    except Exception as _import_err:  # pragma: no cover - env-specific
        _DJANGO_OK, _DJANGO_ERR = False, _import_err
        TestCase = unittest.TestCase  # type: ignore
        JobQueue = None  # type: ignore
else:
    TestCase = unittest.TestCase  # type: ignore
    JobQueue = None  # type: ignore


def _queue(**overrides):
    if JobQueue is None:
        raise unittest.SkipTest("worker django deps unavailable: %s" % _DJANGO_ERR)
    settings = {"cluster": {"type": ""}, "env": {"max_job": 4}, "mail": {"mail_host": "smtp.lab"}}
    settings.update(overrides.pop("settings", {}))
    kwargs = dict(
        max_job=4,
        cpu_pool=10000,
        memory_pool=1024,
        disk_pool=2048,
        work_dir=".",
        settings=settings,
        n_retries=1,
    )
    kwargs.update(overrides)
    return JobQueue(**kwargs)


class DequeueNotifyTests(unittest.TestCase):
    def _job(self):
        job = MagicMock()
        job.job_id = 7
        job.db_obj.id = 7
        return job

    def test_dequeue_notifies_terminal_outcomes(self):
        queue = _queue()
        expected = ((0, "finished"), (1, "failed"), (2, "interrupted"))
        for is_error, event in expected:
            job = self._job()
            with patch.object(queue, "_save_job_with_retries", return_value=True), patch.object(
                queue, "remove_resources"
            ), patch("worker.queue.job_queue.bases.save_output_dict"), patch(
                "worker.queue.job_queue.notify_job"
            ) as notify:
                queue.dequeue(job, is_error=is_error)
            notify.assert_called_once_with(job.db_obj, event, mail_settings={"mail_host": "smtp.lab"})

    def test_dequeue_skips_notify_when_save_fails(self):
        queue = _queue()
        job = self._job()
        with patch.object(queue, "_save_job_with_retries", return_value=False), patch.object(
            queue, "remove_resources"
        ), patch("worker.queue.job_queue.bases.save_output_dict"), patch(
            "worker.queue.job_queue.notify_job"
        ) as notify:
            queue.dequeue(job, is_error=1)
        notify.assert_not_called()


class WorkerStatusNotifyTests(TestCase):
    def setUp(self):
        if not _DJANGO_OK:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)
        self.tmp = tempfile.mkdtemp(prefix="worker-notify-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log_dir = Path(self.tmp) / "log"
        self.log_dir.mkdir()

    def _live_queue(self):
        return JobQueue(
            max_job=4,
            cpu_pool=10000,
            memory_pool=10 * 1024 ** 3,
            disk_pool=10 * 1024 ** 3,
            work_dir=self.tmp,
            settings=worker_settings(self.tmp, str(self.log_dir)),
            n_retries=1,
        )

    def test_template_failure_notifies_failed(self):
        job = seed_echo_job(self.tmp, job_name="broken")
        queue = self._live_queue()
        with patch.object(queue, "_parse_api_job", side_effect=ProtocolTemplateError("bad template")), patch(
            "worker.queue.job_queue.notify_job"
        ) as notify:
            queue.fetch_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WRONG)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], "failed")

    def test_crash_recovery_notifies_failed(self):
        job = seed_echo_job(self.tmp, job_name="orphaned")
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status"])
        queue = self._live_queue()
        with patch("worker.queue.job_queue.notify_job") as notify:
            queue.clean_dead_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WRONG)
        self.assertEqual(notify.call_args.args[1], "failed")

    def test_successful_run_notifies_started_and_finished(self):
        job = seed_echo_job(self.tmp, job_name="echo-job")
        queue = self._live_queue()
        with patch("worker.queue.job_queue.notify_job") as notify:
            queue.fetch_jobs()
            task = queue.queued_jobs_snapshot()[job.id]
            disable_ml_collector(task)
            queue.run_step(task)
        events = [call.args[1] for call in notify.call_args_list]
        self.assertEqual(events, ["started", "finished"])

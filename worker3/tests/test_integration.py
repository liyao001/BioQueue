import os
import shutil
import tempfile
import unittest
from configparser import ConfigParser
from pathlib import Path
from unittest.mock import patch

from worker3.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    try:
        from django.contrib.auth.models import User
        from django.test import TestCase

        from QueueDB.models import Job, JobStatus, Slave
        from worker3.queue.job_queue import JobQueue
        from worker3.testing import ECHO_MARKER, disable_ml_collector, seed_echo_job, worker_settings
    except Exception as _import_err:  # pragma: no cover - env-specific
        _DJANGO_OK, _DJANGO_ERR = False, _import_err
        TestCase = unittest.TestCase  # type: ignore
else:
    TestCase = unittest.TestCase  # type: ignore


class EchoJobIntegrationTests(TestCase):
    def setUp(self):
        if not _DJANGO_OK:
            self.skipTest("worker3 django deps unavailable: %s" % _DJANGO_ERR)
        self.tmp = tempfile.mkdtemp(prefix="worker3-it-")
        self.log_dir = Path(self.tmp) / "log"
        self.outputs = Path(self.tmp) / "outputs"
        self.log_dir.mkdir()
        self.outputs.mkdir()
        conf_path = Path(self.tmp) / "custom.conf"
        config = ConfigParser()
        config["env"] = {"workspace": self.tmp, "log": str(self.log_dir), "outputs": str(self.outputs)}
        with conf_path.open("w") as fh:
            config.write(fh)
        os.environ["BIOQUEUE_CUSTOM_CONF"] = str(conf_path)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _queue(self, **kwargs):
        options = dict(
            max_job=4,
            cpu_pool=10000,
            memory_pool=10 * 1024 ** 3,
            disk_pool=10 * 1024 ** 3,
            work_dir=self.tmp,
            settings=worker_settings(self.tmp, str(self.log_dir)),
            n_retries=1,
        )
        options.update(kwargs)
        return JobQueue(**options)

    def test_fetch_and_run_echo_job(self):
        job = seed_echo_job(self.tmp, job_name="echo-job")
        queue = self._queue()

        queue.fetch_jobs()
        snapshot = queue.queued_jobs_snapshot()
        self.assertIn(job.id, snapshot)

        task = snapshot[job.id]
        disable_ml_collector(task)
        queue.run_step(task)

        job = Job.objects.get(id=job.id)
        self.assertEqual(job.status, JobStatus.FINISHED)
        self.assertEqual(job.result, "{}v0".format(job.id))
        self.assertEqual(job.version, 0)
        self.assertTrue((Path(self.tmp) / str(job.user_id) / job.result).is_dir())
        log_text = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn(ECHO_MARKER, log_text)
        self.assertIn("echo-job", log_text)
        self.assertEqual(User.objects.filter(username="worker3").count(), 1)

    def test_fetch_jobs_skips_locked_and_non_executable(self):
        locked = seed_echo_job(self.tmp, job_name="locked-job")
        locked.locked = 1
        locked.save()
        blocked = seed_echo_job(self.tmp, job_name="blocked-job")
        blocked.is_executable = 0
        blocked.save()
        ready = seed_echo_job(self.tmp, job_name="ready-job")

        queue = self._queue()
        queue.fetch_jobs()
        snapshot = queue.queued_jobs_snapshot()
        self.assertNotIn(locked.id, snapshot)
        self.assertNotIn(blocked.id, snapshot)
        self.assertIn(ready.id, snapshot)
        self.assertEqual(Job.objects.get(id=locked.id).status, JobStatus.WAITING)
        self.assertEqual(Job.objects.get(id=blocked.id).status, JobStatus.WAITING)

    def test_fetch_jobs_claims_a_job_once(self):
        job = seed_echo_job(self.tmp, job_name="claimed-once")
        first = self._queue()
        second = self._queue()
        first.fetch_jobs()
        second.fetch_jobs()
        claimed = list(first.queued_jobs_snapshot()) + list(second.queued_jobs_snapshot())
        self.assertEqual(claimed, [job.id])
        task = first.queued_jobs_snapshot()[job.id]
        self.assertEqual(task.status, JobStatus.WAITING)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RUNNING)

    def test_fetch_jobs_unclaims_when_enqueue_fails(self):
        job = seed_echo_job(self.tmp, job_name="unclaim-me")
        queue = self._queue()
        with patch("worker3.queue.job_queue.logger"), patch.object(
            queue, "_parse_api_job", side_effect=RuntimeError("bad protocol")
        ):
            queue.fetch_jobs()
        self.assertEqual(queue.queued_jobs_snapshot(), {})
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WAITING)

    def test_resume_loads_prior_outputs(self):
        from worker3.queue.task import Task

        job = seed_echo_job(self.tmp, job_name="resume-job")
        job.resume = 1
        job.save()
        prior = {
            Task._FILE_MAP_KEY_LAST_OUTPUT_STRING: "prior.fq",
            Task._FILE_MAP_KEY_OUTPUTS: ["prior.fq"],
            Task._FILE_MAP_KEY_OUTPUT_DICT: {0: ["prior.fq"]},
            Task._FILE_MAP_KEY_OUTPUT_DICT_SUFFIX: {},
            Task._FILE_MAP_KEY_NEW_FILES: ["prior.fq"],
            Task._FILE_MAP_KEY_LAST_OUTPUT: ["prior.fq"],
            Task._FILE_MAP_KEY_LAST_OUTPUT_SUFFIX: {},
        }
        queue = self._queue()
        with patch("worker3.queue.task.bases.load_output_dict", return_value=prior):
            queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        self.assertEqual(task.last_output_string, "prior.fq")
        self.assertEqual(task.outputs, ["prior.fq"])

    def test_update_job_file_mapping_advances_last_output(self):
        job = seed_echo_job(self.tmp, job_name="map-job")
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        run = Path(task.run_folder)
        run.mkdir(parents=True, exist_ok=True)
        first = run / "a.txt"
        first.write_text("a")
        task.update_job_file_mapping()
        self.assertIn(str(first), task.last_output_string)
        self.assertIn(str(first), task.last_output)
        second = run / "b.txt"
        second.write_text("b")
        task.update_job_file_mapping()
        self.assertIn("b.txt", task.last_output_string)
        self.assertNotIn("a.txt", task.last_output_string)

    def test_pinned_worker_skips_other_runners_and_unassigned(self):
        mine = Slave.objects.create(name="node-mine", comment="")
        other = Slave.objects.create(name="node-other", comment="")
        assigned = seed_echo_job(self.tmp, job_name="on-mine")
        assigned.slave = mine
        assigned.save()
        foreign = seed_echo_job(self.tmp, job_name="on-other")
        foreign.slave = other
        foreign.save()
        unassigned = seed_echo_job(self.tmp, job_name="free")

        queue = self._queue(slave="node-mine")
        queue.fetch_jobs()
        snapshot = queue.queued_jobs_snapshot()
        self.assertIn(assigned.id, snapshot)
        self.assertNotIn(unassigned.id, snapshot)
        self.assertNotIn(foreign.id, snapshot)
        self.assertEqual(Job.objects.get(id=unassigned.id).status, JobStatus.WAITING)
        self.assertEqual(Job.objects.get(id=foreign.id).status, JobStatus.WAITING)

    def test_unpinned_worker_skips_assigned_jobs(self):
        runner = Slave.objects.create(name="node-mine", comment="")
        assigned = seed_echo_job(self.tmp, job_name="on-mine")
        assigned.slave = runner
        assigned.save()
        unassigned = seed_echo_job(self.tmp, job_name="free")

        queue = self._queue()
        queue.fetch_jobs()
        snapshot = queue.queued_jobs_snapshot()
        self.assertNotIn(assigned.id, snapshot)
        self.assertIn(unassigned.id, snapshot)
        self.assertEqual(Job.objects.get(id=assigned.id).status, JobStatus.WAITING)

    def test_unpinned_clean_dead_jobs_skips_assigned_runners(self):
        runner = Slave.objects.create(name="node-mine", comment="")
        assigned = seed_echo_job(self.tmp, job_name="running-on-mine")
        assigned.slave = runner
        assigned.status = JobStatus.RUNNING
        assigned.save()
        orphan = seed_echo_job(self.tmp, job_name="orphan")
        orphan.status = JobStatus.RUNNING
        orphan.save()

        queue = self._queue()
        queue.clean_dead_jobs()
        self.assertEqual(Job.objects.get(id=assigned.id).status, JobStatus.RUNNING)
        self.assertEqual(Job.objects.get(id=orphan.id).status, JobStatus.WRONG)

    def test_clean_dead_jobs_releases_resource_lock(self):
        locked = seed_echo_job(self.tmp, job_name="resource-wait")
        locked.status = JobStatus.RESOURCELOCK
        locked.resume = 4
        locked.save()
        running = seed_echo_job(self.tmp, job_name="orphan-running")
        running.status = JobStatus.RUNNING
        running.save()

        queue = self._queue()
        queue.clean_dead_jobs()
        locked = Job.objects.get(id=locked.id)
        self.assertEqual(locked.status, JobStatus.WAITING)
        self.assertEqual(locked.resume, 4)
        self.assertEqual(Job.objects.get(id=running.id).status, JobStatus.WRONG)

    def test_pinned_worker_accepts_runner_id(self):
        runner = Slave.objects.create(name="by-id", comment="")
        job = seed_echo_job(self.tmp, job_name="id-job")
        job.slave = runner
        job.save()
        queue = self._queue(slave=str(runner.id))
        queue.fetch_jobs()
        self.assertIn(job.id, queue.queued_jobs_snapshot())

    def test_resolve_slave_unknown(self):
        from worker3.queue.job_queue import format_runner_list, resolve_slave

        Slave.objects.create(name="known-node", comment="lab")
        with self.assertRaises(ValueError) as ctx:
            resolve_slave("missing-node")
        self.assertIn("known-node", str(ctx.exception))
        listing = format_runner_list()
        self.assertIn("known-node", listing)

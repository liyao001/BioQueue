import os
import json
import shutil
import tempfile
import unittest
from configparser import ConfigParser
from pathlib import Path
from unittest.mock import patch

from worker.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    try:
        from django.contrib.auth.models import User
        from django.test import TestCase

        from QueueDB.models import Job, JobStatus, Slave
        from worker.queue.job_queue import JobQueue
        from worker.testing import ECHO_MARKER, disable_ml_collector, seed_echo_job, worker_settings
    except Exception as _import_err:  # pragma: no cover - env-specific
        _DJANGO_OK, _DJANGO_ERR = False, _import_err
        TestCase = unittest.TestCase  # type: ignore
else:
    TestCase = unittest.TestCase  # type: ignore


class EchoJobIntegrationTests(TestCase):
    def setUp(self):
        if not _DJANGO_OK:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)
        self.tmp = tempfile.mkdtemp(prefix="worker-it-")
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

    def _template_job(self, document, inputs="", sheet="", parameter=""):
        job = seed_echo_job(self.tmp, input_file=inputs)
        job.protocol.template = json.dumps(document)
        job.protocol.save(update_fields=["template"])
        job.sample_sheet = sheet
        job.parameter = parameter
        job.save()
        return job

    def test_template_normalizes_slots_and_runs_defaults(self):
        paths = []
        for name in ("a", "b", "c", "d"):
            path = Path(self.tmp) / name
            path.write_text(name)
            paths.append(str(path))
        document = {"samples": {"group": 2}, "pipeline": [{"map": "samples", "steps": [{
            "software": "echo", "parameter": "{{sample.r1}} {{sample.r2}} umi={{UMI_LEN||6}}"
        }]}]}
        job = self._template_job(document, " {} ;; {};{};{};".format(*paths), parameter="UMI_LEN=;")
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        self.assertEqual(task.job_input_files, paths)
        for _ in task.steps:
            disable_ml_collector(task)
            queue.run_step(task)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FINISHED)
        log = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn("{} {} umi=6".format(*paths[:2]), log)
        self.assertIn("{} {} umi=6".format(*paths[2:]), log)

    def test_template_block_environment_reaches_worker_command(self):
        from QueueDB.models import VirtualEnvironment

        path = Path(self.tmp) / "input.fq"
        path.write_text("sample")
        job = self._template_job({
            "blocks": {"process": {"steps": [{
                "software": "__SHELL__", "parameter": "echo {{sample.name}}",
                "env": "analysis", "force_local": True, "gpu_step": True,
            }]}},
            "pipeline": [{"map": "samples", "steps": [{"call": "process"}]}],
        }, inputs=str(path))
        environment = VirtualEnvironment.objects.create(
            user=job.user, name="analysis", value="analysis", ve_type="conda",
            activation_command="source /opt/conda.sh",
        )
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        step = task.steps[0]
        self.assertEqual(step._env, environment)
        self.assertTrue(step._force_local)
        self.assertTrue(step._gpu_step)
        step.translate_step_to_runnable(task)
        self.assertIn("source /opt/conda.sh && conda activate analysis", step.shell_script)
        self.assertIn("echo rep1", step.shell_script)
        self.assertIn("conda deactivate", step.shell_script)

    def test_template_sheet_files_reach_global_input_command(self):
        path = Path(self.tmp) / "sample.fq"
        path.write_text("sample")
        job = self._template_job(
            {"pipeline": [{"software": "echo", "parameter": "{{InputFile}} umi={{UMI_LEN||6}}"}]},
            sheet=json.dumps([{"r1": str(path)}]), parameter="UMI_LEN=8;",
        )
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        self.assertEqual(task.job_input_files, [str(path)])
        self.assertIsNotNone(task.input_check_step)
        disable_ml_collector(task)
        queue.run_step(task)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FINISHED)
        log = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn("{} umi=8".format(path), log)

    def test_template_sheet_missing_input_fails_before_first_command(self):
        job = self._template_job(
            {"pipeline": [{"software": "echo", "parameter": "should-not-run"}]},
            sheet=json.dumps([{"r1": str(Path(self.tmp) / "missing.fq")}]),
        )
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        disable_ml_collector(task)
        queue.run_step(task)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WRONG)
        log = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn("Input check failed", log)
        self.assertNotIn("should-not-run", log)

    def test_template_sheet_failed_parent_fails_before_first_command(self):
        parent = seed_echo_job(self.tmp, job_name="failed-parent")
        parent.status = JobStatus.WRONG
        parent.result = "failed-result"
        parent.save()
        job = self._template_job(
            {"pipeline": [{"software": "echo", "parameter": "should-not-run"}]},
            sheet=json.dumps([{"r1": "{{{{History:{}-out.fq}}}}".format(parent.id)}]),
        )
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        disable_ml_collector(task)
        queue.run_step(task)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WRONG)
        log = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn("parent job is not runnable", log)
        self.assertNotIn("should-not-run", log)

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
        self.assertEqual(User.objects.filter(username="worker").count(), 1)

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
        with patch("worker.queue.job_queue.logger"), patch.object(
            queue, "_parse_api_job", side_effect=RuntimeError("bad protocol")
        ):
            queue.fetch_jobs()
        self.assertEqual(queue.queued_jobs_snapshot(), {})
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WAITING)

    def test_resume_loads_prior_outputs(self):
        from worker.queue.task import Task

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
        with patch("worker.queue.task.bases.load_output_dict", return_value=prior):
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
        from worker.queue.job_queue import format_runner_list, resolve_slave

        Slave.objects.create(name="known-node", comment="lab")
        with self.assertRaises(ValueError) as ctx:
            resolve_slave("missing-node")
        self.assertIn("known-node", str(ctx.exception))
        listing = format_runner_list()
        self.assertIn("known-node", listing)

    def test_missing_input_fails_before_protocol_step(self):
        missing = str(Path(self.tmp) / "does-not-exist.fq")
        job = seed_echo_job(self.tmp, job_name="missing-input", input_file=missing)
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        self.assertIsNotNone(task.input_check_step)
        queue.run_step(task)
        job = Job.objects.get(id=job.id)
        self.assertEqual(job.status, JobStatus.WRONG)
        self.assertEqual(job.resume, 0)
        log_text = (self.log_dir / "{}.log".format(job.id)).read_text()
        err_text = (self.log_dir / "{}.err".format(job.id)).read_text()
        self.assertNotIn(ECHO_MARKER, log_text)
        self.assertIn("Checking 1 input file(s) before launch.", log_text)
        self.assertIn("missing file", err_text.lower())
        self.assertIn("does-not-exist.fq", err_text)

    def test_present_input_allows_protocol_to_run(self):
        present = Path(self.tmp) / "ok.fq"
        present.write_text("ok")
        job = seed_echo_job(self.tmp, job_name="ok-input", input_file=str(present))
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        disable_ml_collector(task)
        queue.run_step(task)
        job = Job.objects.get(id=job.id)
        self.assertEqual(job.status, JobStatus.FINISHED)
        log_text = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn("Checking 1 input file(s) before launch.", log_text)
        self.assertIn(ECHO_MARKER, log_text)

    def test_failed_history_parent_fails_child_without_running_protocol(self):
        parent = seed_echo_job(self.tmp, job_name="hist-parent")
        parent.status = JobStatus.WRONG
        parent.result = "{}v0".format(parent.id)
        parent.save()
        token = "{{History:%d-out.txt}}" % parent.id
        child = seed_echo_job(self.tmp, job_name="hist-child", input_file=token)
        queue = self._queue()
        queue.fetch_jobs()
        snapshot = queue.queued_jobs_snapshot()
        self.assertIn(child.id, snapshot)
        task = snapshot[child.id]
        queue.run_step(task)
        child = Job.objects.get(id=child.id)
        self.assertEqual(child.status, JobStatus.WRONG)
        self.assertEqual(child.resume, 0)
        log_text = (self.log_dir / "{}.log".format(child.id)).read_text()
        err_text = (self.log_dir / "{}.err".format(child.id)).read_text()
        self.assertNotIn(ECHO_MARKER, log_text)
        self.assertIn("parent job is not runnable", err_text)

    def test_resume_skips_input_check(self):
        missing = str(Path(self.tmp) / "still-missing.fq")
        job = seed_echo_job(
            self.tmp,
            job_name="resume-skip-check",
            input_file=missing,
            resume=1,
            n_steps=2,
        )
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        self.assertIsNone(task.input_check_step)
        disable_ml_collector(task)
        queue.run_step(task)
        job = Job.objects.get(id=job.id)
        self.assertEqual(job.status, JobStatus.FINISHED)
        log_text = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertIn(ECHO_MARKER, log_text)
        self.assertNotIn("Checking ", log_text)

    def test_later_step_does_not_recheck_inputs(self):
        present = Path(self.tmp) / "ok.fq"
        present.write_text("ok")
        job = seed_echo_job(
            self.tmp,
            job_name="two-step-input",
            input_file=str(present),
            n_steps=2,
        )
        queue = self._queue()
        queue.fetch_jobs()
        task = queue.queued_jobs_snapshot()[job.id]
        self.assertIsNotNone(task.input_check_step)
        disable_ml_collector(task)
        queue.run_step(task)
        job = Job.objects.get(id=job.id)
        self.assertEqual(job.resume, 1)
        self.assertNotEqual(job.status, JobStatus.WRONG)
        disable_ml_collector(task)
        queue.run_step(task)
        job = Job.objects.get(id=job.id)
        self.assertEqual(job.status, JobStatus.FINISHED)
        log_text = (self.log_dir / "{}.log".format(job.id)).read_text()
        self.assertEqual(log_text.count("Checking 1 input file(s) before launch."), 1)

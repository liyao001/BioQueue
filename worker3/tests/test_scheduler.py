import unittest
from unittest.mock import MagicMock, patch

from worker3.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    try:
        from worker3.queue.checkpoints import CheckPoints
        from worker3.queue.job_queue import JobQueue
        from worker3.queue.scheduler import validate_worker_settings
    except Exception as _import_err:  # pragma: no cover - env-specific
        _DJANGO_OK, _DJANGO_ERR = False, _import_err
        CheckPoints = None  # type: ignore
        JobQueue = None  # type: ignore
        validate_worker_settings = None  # type: ignore
else:
    CheckPoints = None  # type: ignore
    JobQueue = None  # type: ignore
    validate_worker_settings = None  # type: ignore



def _queue(**overrides):
    if JobQueue is None:
        raise unittest.SkipTest("worker3 django deps unavailable: %s" % _DJANGO_ERR)
    settings = {"cluster": {"type": ""}, "env": {"max_job": 4}}
    settings.update(overrides.pop("settings", {}))
    kwargs = dict(
        max_job=4,
        cpu_pool=100,
        memory_pool=1024,
        disk_pool=2048,
        work_dir=".",
        settings=settings,
        n_retries=1,
    )
    kwargs.update(overrides)
    return JobQueue(**kwargs)


class FakeStep(object):
    def __init__(self, cpu, mem, disk, order=0):
        self.is_running = False
        self.resources = {"cpu": cpu, "mem": mem, "disk": disk, "order": order}


class FakeJob(object):
    def __init__(self, job_id, cpu, mem, disk, status=0, resume=0):
        self.job_id = job_id
        self.status = status
        self.resume = resume
        self.steps = [FakeStep(cpu, mem, disk, order=resume)]
        self.checkpoints = []

    def set_checkpoint_info(self, checkpoint):
        self.checkpoints.append(checkpoint)


class ValidateSettingsTests(unittest.TestCase):
    def setUp(self):
        if validate_worker_settings is None:
            self.skipTest("worker3 django deps unavailable: %s" % _DJANGO_ERR)

    def test_valid_settings(self):
        ok = validate_worker_settings(
            {
                "env": {"workspace": "/tmp", "log": "/tmp/log", "max_job": 2},
                "cluster": {"type": ""},
            }
        )
        self.assertEqual(ok, 1)

    def test_missing_section(self):
        with patch("worker3.queue.scheduler.logger"):
            self.assertEqual(validate_worker_settings({"env": {"workspace": "/tmp"}}), 0)

    def test_cluster_type_requires_allocation_keys(self):
        with patch("worker3.queue.scheduler.logger"):
            self.assertEqual(
                validate_worker_settings(
                    {
                        "env": {"workspace": "/tmp", "log": "/tmp/log", "max_job": 2},
                        "cluster": {"type": "LSF"},
                    }
                ),
                0,
            )


class ResourceCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.queue = _queue()

    def test_none_required_does_not_block(self):
        self.assertFalse(self.queue._resource_exceeds(None, 10, 20))

    def test_exceeds_available(self):
        self.assertTrue(self.queue._resource_exceeds(15, 10, 20))

    def test_exceeds_budget(self):
        self.assertTrue(self.queue._resource_exceeds(25, 30, 20))

    def test_checkpoint_reason_cpu(self):
        reason = self.queue._checkpoint_reason_for_resource(
            resource={"cpu": 90, "mem": 100, "disk": 100},
            host_cpu_available=50,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertEqual(reason, CheckPoints.CPU)

    def test_checkpoint_reason_memory(self):
        reason = self.queue._checkpoint_reason_for_resource(
            resource={"cpu": 10, "mem": 900, "disk": 100},
            host_cpu_available=50,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertEqual(reason, CheckPoints.MEMORY)

    def test_checkpoint_reason_none_when_within_limits(self):
        reason = self.queue._checkpoint_reason_for_resource(
            resource={"cpu": 10, "mem": 100, "disk": 100},
            host_cpu_available=50,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertIsNone(reason)

    def test_cap_impossible_forecast_to_usable_budget(self):
        with patch("worker3.queue.job_queue.logger"):
            capped = self.queue._cap_to_budget(
                {"cpu": 10, "mem": 10 ** 18, "disk": 0},
                budget_cpu=100,
                budget_memory=1000,
                budget_disk=1000,
                available_cpu=100,
                available_memory=800,
                available_disk=1000,
            )
        self.assertEqual(capped["cpu"], 10)
        self.assertAlmostEqual(capped["mem"], 800 * 0.95)

    def test_negative_defaults_clamp_to_zero(self):
        cleaned = self.queue._with_resource_defaults({"cpu": -60, "mem": -60, "disk": 0})
        self.assertEqual(cleaned["cpu"], 0)
        self.assertEqual(cleaned["mem"], 0)
        self.assertEqual(cleaned["disk"], 0)


class PickNextJobTests(unittest.TestCase):
    def setUp(self):
        self.queue = _queue()
        self.queue._launch_step_thread = MagicMock()

    def _register(self, job):
        self.queue._queued_jobs[job.job_id] = job
        self.queue.set_resources(job.job_id, job.steps[0].resources)

    def test_picks_largest_cpu_that_fits(self):
        small = FakeJob(1, cpu=20, mem=10, disk=10)
        large = FakeJob(2, cpu=50, mem=10, disk=10)
        too_big = FakeJob(3, cpu=90, mem=10, disk=10)
        self._register(small)
        self._register(large)
        self._register(too_big)

        picked, locked = self.queue.pick_next_job(
            job_table=self.queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertFalse(locked)
        self.assertIs(picked, large)
        self.assertEqual(too_big.checkpoints, [CheckPoints.CPU])

    def test_fifo_picks_oldest_that_is_ready(self):
        queue = _queue(schedule="fifo")
        queue._launch_step_thread = MagicMock()
        older_small = FakeJob(1, cpu=20, mem=10, disk=10)
        newer_large = FakeJob(2, cpu=50, mem=10, disk=10)
        for job in (older_small, newer_large):
            queue._queued_jobs[job.job_id] = job
            queue.set_resources(job.job_id, job.steps[0].resources)
        picked, locked = queue.pick_next_job(
            job_table=queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertFalse(locked)
        self.assertIs(picked, older_small)

    def test_fifo_oversized_head_blocks_later_jobs(self):
        queue = _queue(schedule="fifo")
        queue._launch_step_thread = MagicMock()
        head = FakeJob(1, cpu=90, mem=10, disk=10)
        later = FakeJob(2, cpu=20, mem=10, disk=10)
        for job in (head, later):
            queue._queued_jobs[job.job_id] = job
            queue.set_resources(job.job_id, job.steps[0].resources)
        picked, locked = queue.pick_next_job(
            job_table=queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertFalse(locked)
        self.assertIsNone(picked)
        self.assertEqual(head.checkpoints, [CheckPoints.CPU])
        self.assertEqual(later.checkpoints, [])
        queue._launch_step_thread.assert_not_called()

    def test_fifo_skips_already_running_head(self):
        queue = _queue(schedule="fifo")
        running = FakeJob(1, cpu=10, mem=10, disk=10, status=1)
        waiting = FakeJob(2, cpu=20, mem=10, disk=10)
        for job in (running, waiting):
            queue._queued_jobs[job.job_id] = job
            queue.set_resources(job.job_id, job.steps[0].resources)
        picked, locked = queue.pick_next_job(
            job_table=queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertFalse(locked)
        self.assertIs(picked, waiting)

    def test_unknown_resources_do_not_lock_queue(self):
        job = FakeJob(1, cpu=None, mem=None, disk=None)
        self._register(job)

        picked, locked = self.queue.pick_next_job(
            job_table=self.queue.queued_jobs_snapshot(),
            host_cpu_available=500,
            host_memory_available=2 * 1024 ** 3,
            host_disk_free=2 * 1024 ** 3,
            budget_cpu=800,
            budget_memory=4 * 1024 ** 3,
            budget_disk=4 * 1024 ** 3,
        )
        self.assertFalse(locked)
        self.assertIs(picked, job)
        self.queue._launch_step_thread.assert_not_called()
        self.assertFalse(self.queue.is_queue_locked)

    def test_unknown_resources_do_not_block_siblings(self):
        unknown = FakeJob(1, cpu=None, mem=None, disk=None)
        known = FakeJob(2, cpu=20, mem=10, disk=10)
        self._register(unknown)
        self._register(known)
        picked, locked = self.queue.pick_next_job(
            job_table=self.queue.queued_jobs_snapshot(),
            host_cpu_available=500,
            host_memory_available=2 * 1024 ** 3,
            host_disk_free=2 * 1024 ** 3,
            budget_cpu=800,
            budget_memory=4 * 1024 ** 3,
            budget_disk=4 * 1024 ** 3,
        )
        self.assertFalse(locked)
        self.assertIs(picked, unknown)
        self.assertEqual(known.checkpoints, [])

    def test_skips_running_status(self):
        job = FakeJob(1, cpu=10, mem=10, disk=10, status=1)
        self._register(job)
        picked, locked = self.queue.pick_next_job(
            job_table=self.queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertIsNone(picked)
        self.assertFalse(locked)

    def test_impossible_mem_forecast_is_capped_and_picked(self):
        job = FakeJob(1, cpu=10, mem=10 ** 18, disk=10)
        self._register(job)
        with patch("worker3.queue.job_queue.logger"):
            picked, locked = self.queue.pick_next_job(
                job_table=self.queue.queued_jobs_snapshot(),
                host_cpu_available=60,
                host_memory_available=500,
                host_disk_free=500,
                budget_cpu=100,
                budget_memory=1000,
                budget_disk=1000,
            )
        self.assertFalse(locked)
        self.assertIs(picked, job)
        self.assertEqual(job.checkpoints, [])
        self.assertAlmostEqual(job.steps[0].resources["mem"], 500 * 0.95)

    def test_negative_forecast_does_not_block(self):
        job = FakeJob(1, cpu=-60, mem=-60, disk=0)
        self._register(job)
        picked, locked = self.queue.pick_next_job(
            job_table=self.queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertFalse(locked)
        self.assertIs(picked, job)
        self.assertEqual(job.steps[0].resources["cpu"], 0)
        self.assertEqual(job.steps[0].resources["mem"], 0)

    def test_real_oversize_still_waits_when_host_is_busy(self):
        job = FakeJob(1, cpu=90, mem=10, disk=10)
        self._register(job)
        picked, locked = self.queue.pick_next_job(
            job_table=self.queue.queued_jobs_snapshot(),
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertIsNone(picked)
        self.assertFalse(locked)
        self.assertEqual(job.checkpoints, [CheckPoints.CPU])


class JobQueueMaintenanceTests(unittest.TestCase):
    def test_cli_slave_override_survives_settings_refresh(self):
        queue = _queue(slave="node-1")
        self.assertEqual(queue.slave_key, "node-1")
        queue.refresh_runtime_settings(
            {
                "env": {"max_job": "4", "workspace": "/ws", "log": "/log"},
                "cluster": {"type": ""},
            }
        )
        self.assertEqual(queue.slave_key, "node-1")

    def test_cli_schedule_override_survives_settings_refresh(self):
        queue = _queue(schedule="fifo")
        self.assertEqual(queue.schedule_policy, "fifo")
        queue.refresh_runtime_settings(
            {
                "env": {"max_job": "4", "workspace": "/ws", "log": "/log", "schedule": "greedy"},
                "cluster": {"type": ""},
            }
        )
        self.assertEqual(queue.schedule_policy, "fifo")

    def test_cli_predict_override_survives_settings_refresh(self):
        queue = _queue(predict="base")
        self.assertEqual(queue.predict_mode, "base")
        self.assertEqual(queue._settings["ml"]["predict"], "base")
        queue.refresh_runtime_settings(
            {
                "env": {"max_job": "4", "workspace": "/ws", "log": "/log"},
                "cluster": {"type": ""},
                "ml": {"predict": "linear"},
            }
        )
        self.assertEqual(queue.predict_mode, "base")
        self.assertEqual(queue._settings["ml"]["predict"], "base")

    def test_predict_from_config_when_unpinned(self):
        queue = _queue(settings={"cluster": {"type": ""}, "env": {"max_job": 4}, "ml": {"predict": "base"}})
        self.assertEqual(queue.predict_mode, "base")

    def test_schedule_from_config_when_unpinned(self):
        queue = _queue(settings={"cluster": {"type": ""}, "env": {"max_job": 4, "schedule": "fifo"}})
        self.assertEqual(queue.schedule_policy, "fifo")

    def test_slave_key_from_config_when_unpinned(self):
        queue = _queue(settings={"cluster": {"type": "", "slave": "from-conf"}, "env": {"max_job": 4}})
        self.assertEqual(queue.slave_key, "from-conf")

    def test_refresh_runtime_settings_updates_settings_and_max_job(self):
        queue = _queue()
        queue.refresh_runtime_settings(
            {
                "env": {"max_job": "8", "workspace": "/ws", "log": "/log"},
                "cluster": {"type": "LSF"},
            }
        )
        self.assertEqual(queue.max_concurrent_jobs, 8)
        self.assertEqual(queue._settings["cluster"]["type"], "LSF")

    def test_refresh_runtime_settings_keeps_previous_on_invalid(self):
        queue = _queue()
        previous = queue._settings
        with patch("worker3.queue.job_queue.logger"):
            queue.refresh_runtime_settings({"env": {}})
            queue.refresh_runtime_settings(None)
        self.assertIs(queue._settings, previous)
        self.assertEqual(queue.max_concurrent_jobs, 4)

    def test_record_failed_task_while_holding_lock(self):
        queue = _queue()
        with queue._lock:
            queue._record_failed_task(lambda: None)
        self.assertEqual(len(queue._failed_tasks), 1)

    def test_dequeue_missing_queue_entry(self):
        queue = _queue()

        class FakeDb(object):
            status = 0
            ter = 0

            def save(self):
                return None

        class FakeTask(object):
            job_id = 99
            db_obj = FakeDb()
            file_map = {}

            def snapshot(self):
                return None

        with patch("worker3.queue.job_queue.bases.save_output_dict"):
            queue.dequeue(FakeTask())

    def test_coerce_int_from_config_string(self):
        queue = _queue()
        self.assertEqual(queue._coerce_int("8"), 8)
        self.assertEqual(queue._coerce_int("nope", default=2), 2)
        self.assertTrue(queue._coerce_int("4") > queue._coerce_int("2"))

    def test_dependencies_fail_on_wrong_status(self):
        queue = _queue()
        from QueueDB.models import _JS_FINISHED, _JS_INTERRUPTED, _JS_WRONG

        step = FakeStep(1, 1, 1)
        step.dependent_jobs = {17}
        job = FakeJob(1, 1, 1, 1)
        with patch.object(queue, "query_job_status", return_value=_JS_WRONG), patch(
            "worker3.queue.job_queue.logger"
        ):
            self.assertFalse(queue._dependencies_are_ready(job, step))
        with patch.object(queue, "query_job_status", return_value=_JS_INTERRUPTED), patch(
            "worker3.queue.job_queue.logger"
        ):
            self.assertFalse(queue._dependencies_are_ready(job, step))
        with patch.object(queue, "query_job_status", return_value=None), patch(
            "worker3.queue.job_queue.logger"
        ):
            self.assertFalse(queue._dependencies_are_ready(job, step))
        with patch.object(queue, "query_job_status", return_value=_JS_FINISHED):
            self.assertTrue(queue._dependencies_are_ready(job, step))

    def test_run_step_releases_resources_after_exception(self):
        queue = _queue(
            settings={
                "cluster": {"type": ""},
                "env": {"max_job": 4, "log": "/tmp", "workspace": "/tmp"},
            }
        )
        step = FakeStep(10, 10, 10)
        step.dependent_jobs = []
        step.force_local = True
        job = FakeJob(1, 10, 10, 10)
        job.steps = [step]
        job.run_folder = "/tmp"
        job.db_obj = MagicMock()
        cpu_before = queue._cpu_pool

        def _forecast(step_obj, job_obj=None):
            queue._update_resource_pool(step_obj.resources, -1)
            return True

        with patch("os.path.exists", return_value=True), patch.object(
            queue, "forecast_step", side_effect=_forecast
        ), patch.object(queue, "_run_step_local", side_effect=RuntimeError("boom")), patch.object(
            queue, "finish_step"
        ) as finish, patch("worker3.queue.job_queue.logger"):
            queue.run_step(job)
        finish.assert_called_once_with(job, is_error=1)
        self.assertEqual(queue._cpu_pool, cpu_before - 10)

    def test_run_step_cluster_coerces_cpu_cap(self):
        queue = _queue(
            settings={
                "cluster": {
                    "type": "LSF",
                    "cpu": "4",
                    "mem": "1G",
                    "vrt": "1G",
                    "new_queue": "normal",
                    "walltime": "01:00",
                },
                "env": {"max_job": 4},
            }
        )
        step = FakeStep(900, None, None)
        step.command = ["echo", "hi"]
        job = FakeJob(7, 900, None, None)
        job.steps = [step]
        job.run_folder = "/tmp"
        fake_cluster = MagicMock()
        fake_cluster.main.return_value = 0
        with patch("worker3.queue.job_queue.cluster_support") as fake_cluster:
            fake_cluster.main.return_value = 0
            rc = queue._run_step_cluster(job, "/tmp/out", "/tmp/err")
        self.assertEqual(rc, 0)
        args = fake_cluster.main.call_args[0]
        self.assertEqual(args[0], "LSF")
        self.assertEqual(args[4], 4)

    def test_pick_next_job_skips_stale_resource_id(self):
        queue = _queue()
        queue.set_resources(99, {"cpu": 10, "mem": 10, "disk": 10, "order": 0})
        picked, locked = queue.pick_next_job(
            job_table={},
            host_cpu_available=60,
            host_memory_available=500,
            host_disk_free=500,
            budget_cpu=100,
            budget_memory=1000,
            budget_disk=1000,
        )
        self.assertIsNone(picked)
        self.assertFalse(locked)

    def test_fetch_jobs_skips_non_positive_limit(self):
        queue = _queue()
        with patch("worker3.queue.job_queue.Job") as job_model:
            queue.fetch_jobs(n_jobs=0)
            queue.fetch_jobs(n_jobs=-3)
            job_model.objects.filter.assert_not_called()

    def test_save_retries_call_on_failure_once(self):
        queue = _queue(n_retries=3)
        failures = []

        class Boom(object):
            id = 7

            def save(self):
                raise RuntimeError("db down")

        with patch("worker3.queue.job_queue.time.sleep"), patch("worker3.queue.job_queue.logger"):
            ok = queue._save_job_with_retries(Boom(), "update", on_failure=lambda: failures.append(1))
        self.assertFalse(ok)
        self.assertEqual(failures, [1])

    def test_retry_failed_tasks_runs_and_clears(self):
        queue = _queue()
        seen = []
        queue._failed_tasks.append((lambda value: seen.append(value), (42,)))
        queue.retry_failed_tasks()
        self.assertEqual(seen, [42])
        self.assertEqual(queue._failed_tasks, [])

    def test_finish_step_error_skips_null_trace(self):
        queue = _queue()
        step = FakeStep(1, 1, 1)
        step.resources["trace"] = None
        job = FakeJob(1, 1, 1, 1)
        job.steps = [step]
        job.db_obj = MagicMock()
        job.file_map = {}
        job.snapshot = MagicMock()
        with patch("worker3.queue.job_queue.Training") as training, patch(
            "worker3.queue.job_queue.bases.save_output_dict"
        ), patch.object(queue, "dequeue"):
            queue.finish_step(job, is_error=1)
        training.objects.get.assert_not_called()

    def test_dequeue_interrupted_on_error_two(self):
        queue = _queue()
        from QueueDB.models import _JS_INTERRUPTED

        class FakeDb(object):
            status = 0
            ter = 1

            def save(self):
                return None

        class FakeTask(object):
            job_id = 99
            db_obj = FakeDb()
            file_map = {}

            def snapshot(self):
                return None

        task = FakeTask()
        with patch("worker3.queue.job_queue.bases.save_output_dict"):
            queue.dequeue(task, is_error=2)
        self.assertEqual(task.db_obj.status, _JS_INTERRUPTED)
        self.assertEqual(task.db_obj.ter, 0)

    def test_launch_marks_step_running_before_thread(self):
        queue = _queue()
        job = FakeJob(1, 10, 10, 10)
        with patch("worker3.queue.job_queue.threading.Thread") as thread:
            thread.return_value.start = lambda: None
            queue._launch_step_thread(job)
        self.assertTrue(job.steps[0].is_running)
        self.assertIn((1, 0), queue.running_table)

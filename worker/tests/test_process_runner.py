import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from worker.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    from worker.queue.process_runner import ProcessRunner
else:
    ProcessRunner = None  # type: ignore


class ProcessRunnerTests(unittest.TestCase):
    def setUp(self):
        if ProcessRunner is None:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)

    def test_spawn_step_uses_shell_when_command_has_pipe(self):
        step = MagicMock()
        step.is_shell = False
        step.command = ["cat", "a", "|", "wc"]
        log_fh = MagicMock()
        err_fh = MagicMock()

        with patch("worker.queue.process_runner.bases.check_shell_sig", return_value=1), patch(
            "worker.queue.process_runner.subprocess.Popen"
        ) as popen:
            popen.return_value = "proc"
            result = ProcessRunner.spawn_step(step, "/tmp/run", log_fh, err_fh)

        self.assertEqual(result, "proc")
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0], "cat a | wc")
        self.assertTrue(kwargs["shell"])
        self.assertEqual(kwargs["cwd"], "/tmp/run")
        self.assertTrue(kwargs["executable"].endswith("bash"))

    def test_spawn_step_uses_bash_for_source(self):
        step = MagicMock()
        step.is_shell = False
        step.command = ["source", "/opt/conda/etc/profile.d/conda.sh", "&&", "conda", "activate", "reg"]
        with patch("worker.queue.process_runner.bases.check_shell_sig", return_value=0), patch(
            "worker.queue.process_runner.subprocess.Popen"
        ) as popen:
            popen.return_value = "proc"
            ProcessRunner.spawn_step(step, "/tmp/run", MagicMock(), MagicMock())
        args, kwargs = popen.call_args
        self.assertTrue(kwargs["shell"])
        self.assertTrue(kwargs["executable"].endswith("bash"))

    def test_spawn_step_avoids_shell_for_plain_argv(self):
        step = MagicMock()
        step.is_shell = False
        step.command = ["echo", "hi"]

        with patch("worker.queue.process_runner.bases.check_shell_sig", return_value=0), patch(
            "worker.queue.process_runner.subprocess.Popen"
        ) as popen:
            popen.return_value = "proc"
            ProcessRunner.spawn_step(step, "/tmp/run", MagicMock(), MagicMock())

        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["echo", "hi"])
        self.assertFalse(kwargs["shell"])

    def test_spawn_step_writes_and_runs_shell_script(self):
        run_dir = tempfile.mkdtemp(prefix="bq-shell-")
        step = MagicMock()
        step.is_shell = True

        def _write(folder, index):
            path = os.path.join(folder, ".bq_step_{}.sh".format(index))
            with open(path, "w") as fh:
                fh.write("#!/usr/bin/env bash\necho ok\n")
            return path

        step.write_shell_script.side_effect = _write
        with patch("worker.queue.process_runner.subprocess.Popen") as popen:
            popen.return_value = "proc"
            ProcessRunner.spawn_step(step, run_dir, MagicMock(), MagicMock(), step_index=3)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][1], os.path.join(run_dir, ".bq_step_3.sh"))
        self.assertTrue(str(args[0][0]).endswith("bash"))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["cwd"], run_dir)

    def test_process_exit_code_two_is_returned_as_is(self):
        proc = MagicMock()
        proc.poll.return_value = 2
        proc.returncode = 2
        proc.pid = 1
        runner = ProcessRunner(n_retries=1, kill_process_fn=lambda proc_info: None)
        self.assertEqual(runner.wait_for_completion(proc, job_id=1), 2)

    def test_terminate_flag_returns_interrupt_sentinel(self):
        from types import SimpleNamespace

        from worker.queue.constants import STEP_USER_INTERRUPTED

        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 42
        killed = []
        runner = ProcessRunner(n_retries=1, kill_process_fn=lambda proc_info: killed.append(proc_info))
        db_job = SimpleNamespace(ter=1)
        with patch("worker.queue.process_runner.psutil.pids", return_value=[42]), patch(
            "worker.queue.process_runner.psutil.Process",
            return_value=SimpleNamespace(is_running=lambda: True),
        ), patch("worker.queue.process_runner.close_old_connections"), patch(
            "worker.queue.process_runner.Job"
        ) as job_model:
            job_model.objects.get.return_value = db_job
            rc = runner.wait_for_completion(proc, job_id=7)
        self.assertEqual(rc, STEP_USER_INTERRUPTED)
        self.assertEqual(len(killed), 1)

    def test_resume_to_waiting_stops_the_live_process(self):
        from types import SimpleNamespace

        from QueueDB.models import _JS_RUNNING, _JS_WAITING
        from worker.queue.constants import STEP_USER_INTERRUPTED

        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 42
        killed = []
        runner = ProcessRunner(n_retries=1, kill_process_fn=lambda proc_info: killed.append(proc_info))
        released = SimpleNamespace(ter=0, status=_JS_WAITING)
        with patch("worker.queue.process_runner.psutil.pids", return_value=[42]), patch(
            "worker.queue.process_runner.psutil.Process",
            return_value=SimpleNamespace(is_running=lambda: True),
        ), patch("worker.queue.process_runner.close_old_connections"), patch(
            "worker.queue.process_runner.Job"
        ) as job_model:
            job_model.objects.get.return_value = released
            rc = runner.wait_for_completion(proc, job_id=7)
        self.assertEqual(rc, STEP_USER_INTERRUPTED)
        self.assertEqual(len(killed), 1)

        proc.poll.side_effect = [None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        killed.clear()
        with patch("worker.queue.process_runner.psutil.pids", return_value=[42]), patch(
            "worker.queue.process_runner.psutil.Process",
            return_value=SimpleNamespace(is_running=lambda: True),
        ), patch("worker.queue.process_runner.close_old_connections"), patch(
            "worker.queue.process_runner.Job"
        ) as job_model:
            job_model.objects.get.return_value = SimpleNamespace(ter=0, status=_JS_RUNNING)
            rc = runner.wait_for_completion(proc, job_id=7)
        self.assertEqual(rc, 0)
        self.assertEqual(killed, [])

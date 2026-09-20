"""Local subprocess execution and version probes for a single step."""
import logging
import shutil
import subprocess
import time

from worker3 import bases
import psutil
from django.db import close_old_connections
from QueueDB.models import Job

from worker3.queue.constants import VERSION_CHECK_TIMEOUT, TERMINATION_POLL_INTERVAL

logger = logging.getLogger("BioQueue")


def _bash_executable():
    return shutil.which("bash") or "/bin/bash"


def _needs_shell(command):
    if bases.check_shell_sig(command):
        return True
    if command and command[0] in ("source", "."):
        return True
    return False


class ProcessRunner(object):
    def __init__(self, n_retries, kill_process_fn):
        self._n_retries = n_retries
        self._kill_process_fn = kill_process_fn

    def record_version(self, step_obj, job):
        if step_obj.version_check == "":
            return
        p = subprocess.Popen(
            step_obj.version_check,
            shell=True,
            executable=_bash_executable(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            ver, _ = p.communicate(timeout=VERSION_CHECK_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._kill_process_fn(psutil.Process(p.pid))
            logger.warning(f"Version check timed out for job {job.job_id}, step {job.resume}")
            ver = b""
        ver = ver.decode("utf-8", errors="replace")
        job.update_snapshot("version", str(job.resume), ver)

    @staticmethod
    def spawn_step(step_obj, run_folder, log_file_handler, err_file_handler, step_index=0):
        if getattr(step_obj, "is_shell", False):
            script_path = step_obj.write_shell_script(run_folder, step_index)
            logger.info("Running shell step via %s", script_path)
            return subprocess.Popen(
                [_bash_executable(), script_path],
                shell=False,
                stdout=log_file_handler,
                stderr=err_file_handler,
                cwd=run_folder,
            )
        if _needs_shell(step_obj.command):
            return subprocess.Popen(
                ' '.join(step_obj.command),
                shell=True,
                executable=_bash_executable(),
                stdout=log_file_handler,
                stderr=err_file_handler,
                cwd=run_folder
            )
        return subprocess.Popen(
            step_obj.command,
            shell=False,
            stdout=log_file_handler,
            stderr=err_file_handler,
            cwd=run_folder
        )

    def wait_for_completion(self, step_process, job_id):
        process_id = step_process.pid
        while step_process.poll() is None:
            if process_id in psutil.pids():
                proc_info = psutil.Process(process_id)
                if proc_info.is_running():
                    terminate_requested = False
                    for _ in range(self._n_retries):
                        try:
                            close_old_connections()
                            db_job = Job.objects.get(id=job_id)
                            terminate_requested = bool(db_job.ter)
                            break
                        except Exception as e:
                            logger.warning(f"Failed to retrieve job (id: {job_id}) status from the database")
                            logger.exception(e)
                            time.sleep(1)
                    if terminate_requested:
                        self._kill_process_fn(proc_info)
                        return 2
            try:
                step_process.wait(timeout=TERMINATION_POLL_INTERVAL)
            except subprocess.TimeoutExpired:
                continue
        return step_process.returncode

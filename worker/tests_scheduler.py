import os
import sys
import unittest

# Run from repo root: python -m unittest worker.tests_scheduler
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from worker.bioqueue import CheckPoints, JobQueue
except ImportError as _import_err:
    CheckPoints = None  # type: ignore
    JobQueue = None  # type: ignore
    _IMPORT_ERROR = _import_err
else:
    _IMPORT_ERROR = None


class JobQueueSchedulerTests(unittest.TestCase):
    def setUp(self):
        if JobQueue is None:
            self.skipTest("worker deps unavailable: %s" % _IMPORT_ERROR)
        self.queue = JobQueue(
            max_job=1,
            cpu_pool=100,
            memory_pool=1024,
            disk_pool=2048,
            work_dir=".",
            settings={"cluster": {"type": ""}, "env": {"max_job": 1}},
            n_retries=1,
        )

    def test_checkpoint_reason_cpu(self):
        reason = self.queue._checkpoint_reason_for_resource(
            resource={"cpu": 90, "mem": 100, "disk": 100},
            cpu_indeed=50,
            mem_indeed=500,
            disk_indeed=500,
            cpu_pool=100,
            memory_pool=1000,
            disk_pool=1000,
        )
        self.assertEqual(reason, CheckPoints.CPU)

    def test_checkpoint_reason_memory(self):
        reason = self.queue._checkpoint_reason_for_resource(
            resource={"cpu": 10, "mem": 900, "disk": 100},
            cpu_indeed=50,
            mem_indeed=500,
            disk_indeed=500,
            cpu_pool=100,
            memory_pool=1000,
            disk_pool=1000,
        )
        self.assertEqual(reason, CheckPoints.MEMORY)

    def test_checkpoint_reason_none_when_within_limits(self):
        reason = self.queue._checkpoint_reason_for_resource(
            resource={"cpu": 10, "mem": 100, "disk": 100},
            cpu_indeed=50,
            mem_indeed=500,
            disk_indeed=500,
            cpu_pool=100,
            memory_pool=1000,
            disk_pool=1000,
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()

import importlib
import os
import sys
import unittest


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_strips_package_dir_so_stdlib_queue_imports(self):
        package_dir = os.path.realpath(
            os.path.abspath(os.path.dirname(importlib.import_module("worker3").__file__))
        )
        sys.path.insert(0, package_dir)
        sys.modules.pop("queue", None)

        import worker3._bootstrap as bootstrap

        importlib.reload(bootstrap)

        abs_paths = [os.path.realpath(os.path.abspath(p or os.getcwd())) for p in sys.path]
        self.assertNotIn(package_dir, abs_paths)

        sys.modules.pop("queue", None)
        stdlib_queue = importlib.import_module("queue")
        self.assertTrue(hasattr(stdlib_queue, "Queue"))
        self.assertFalse(hasattr(stdlib_queue, "JobQueue"))

    def test_bootstrap_does_not_put_legacy_worker_on_path(self):
        import worker3._bootstrap as bootstrap

        importlib.reload(bootstrap)
        worker_legacy = os.path.realpath(
            os.path.join(
                os.path.dirname(importlib.import_module("worker3").__file__),
                "..",
                "worker",
            )
        )
        abs_paths = [os.path.realpath(os.path.abspath(p or os.getcwd())) for p in sys.path]
        self.assertNotIn(worker_legacy, abs_paths)

    def test_vendored_bases_is_not_the_top_level_bases_module(self):
        sys.modules.pop("bases", None)
        import worker3.bases as bases_mod

        self.assertTrue(hasattr(bases_mod, "get_all_config"))
        self.assertTrue(hasattr(bases_mod, "check_shell_sig"))
        self.assertIsNone(sys.modules.get("bases"))


class LazyQueuePackageTests(unittest.TestCase):
    def test_checkpoints_import_does_not_need_job_queue(self):
        from worker3.queue.checkpoints import CheckPoints

        self.assertEqual(int(CheckPoints.CPU), 3)
        self.assertEqual(int(CheckPoints.DEPENDENCE), 6)

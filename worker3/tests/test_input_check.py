import os
import tempfile
import unittest
from unittest.mock import MagicMock

from worker3.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    from worker3.queue.input_check import (
        bind_input_dependencies,
        build_input_check_step,
        is_remote_url,
        missing_local_inputs,
        non_empty_input_entries,
        resolve_input_entry,
    )
else:
    build_input_check_step = None  # type: ignore


def _settings():
    return {
        "env": {"workspace": "/tmp", "cpu": "2"},
        "cluster": {"type": ""},
    }


def _job(run_folder, inputs):
    job = MagicMock()
    job.job_id = 7
    job.job_name = "check-job"
    job.last_output_string = ""
    job.outputs = []
    job.newfiles = []
    job.user_options = {}
    job.output_dict = {}
    job.job_input_files = inputs
    job.user_folder = run_folder
    job.output_dict_suffix = {}
    job.last_output_suffix = {}
    job.job_user = MagicMock()
    job.job_user.id = 1
    job.run_folder = run_folder
    return job


class InputCheckHelperTests(unittest.TestCase):
    def setUp(self):
        if build_input_check_step is None:
            self.skipTest("worker3 django deps unavailable: %s" % _DJANGO_ERR)

    def test_non_empty_skips_blank_slots(self):
        self.assertEqual(
            non_empty_input_entries(["a.fq", "", "   ", "b.fq"]),
            [(1, "a.fq"), (4, "b.fq")],
        )
        self.assertEqual(non_empty_input_entries([""]), [])
        self.assertEqual(non_empty_input_entries(";".split(";")), [])

    def test_build_step_is_force_local_shell(self):
        step = build_input_check_step(_settings(), 2)
        self.assertTrue(step.is_shell)
        self.assertEqual(step.force_local, 1)

    def test_missing_local_path(self):
        folder = tempfile.mkdtemp(prefix="bq-in-")
        missing = os.path.join(folder, "no-such.fq")
        job = _job(folder, [missing])
        self.assertEqual(missing_local_inputs(job), [missing])

    def test_existing_local_path(self):
        folder = tempfile.mkdtemp(prefix="bq-in-")
        present = os.path.join(folder, "ok.fq")
        with open(present, "w") as fh:
            fh.write("ok")
        job = _job(folder, [present, ""])
        self.assertEqual(missing_local_inputs(job), [])

    def test_skips_http_urls(self):
        self.assertTrue(is_remote_url("http://example.com/a.fq"))
        self.assertTrue(is_remote_url("https://example.com/a.fq"))
        self.assertTrue(is_remote_url("HTTP://example.com/a.fq"))
        self.assertTrue(is_remote_url("http://localhost/a.fq"))
        self.assertTrue(is_remote_url("ftp://fileserver/run.fq"))
        self.assertFalse(is_remote_url("/tmp/a.fq"))
        folder = tempfile.mkdtemp(prefix="bq-in-")
        job = _job(
            folder,
            [
                "http://example.com/a.fq",
                "HTTP://example.com/b.fq",
                "http://localhost/c.fq",
                "ftp://fileserver/run.fq",
            ],
        )
        self.assertEqual(missing_local_inputs(job), [])

    def test_unresolved_upload_is_missing(self):
        folder = tempfile.mkdtemp(prefix="bq-in-")
        job = _job(folder, ["{{Uploaded:not-here.fq}}"])
        missing = missing_local_inputs(job)
        self.assertEqual(len(missing), 1)
        self.assertIn("Uploaded", missing[0])

    def test_resolve_plain_path_unchanged(self):
        folder = tempfile.mkdtemp(prefix="bq-in-")
        job = _job(folder, ["/tmp/a.fq"])
        self.assertEqual(resolve_input_entry("/tmp/a.fq", job), "/tmp/a.fq")

    def test_bind_dependencies_skips_remote_urls(self):
        folder = tempfile.mkdtemp(prefix="bq-in-")
        job = _job(folder, ["ftp://fileserver/run.fq", "http://localhost/a.fq"])
        step = build_input_check_step(_settings())
        bind_input_dependencies(step, job)
        self.assertEqual(step.dependent_jobs, set())

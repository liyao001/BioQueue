import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from worker3.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    from worker3.step import _Step
else:
    _Step = None  # type: ignore


def _settings():
    return {
        "env": {"workspace": "/tmp", "cpu": "2"},
        "cluster": {"type": ""},
    }


def _job(run_folder):
    job = MagicMock()
    job.job_id = 7
    job.job_name = "shell-job"
    job.last_output_string = "prev.fq"
    job.outputs = ["prev.fq"]
    job.newfiles = []
    job.user_options = {}
    job.output_dict = {}
    job.job_input_files = []
    job.user_folder = run_folder
    job.output_dict_suffix = {}
    job.last_output_suffix = {}
    job.job_user = MagicMock()
    job.job_user.id = 1
    job.run_folder = run_folder
    return job


class ShellStepTests(unittest.TestCase):
    def setUp(self):
        if _Step is None:
            self.skipTest("worker3 django deps unavailable: %s" % _DJANGO_ERR)

    def test_is_shell_from_software_name(self):
        step = _Step("__SHELL__", "echo hi", "", "h", None, 0, "", _settings())
        self.assertTrue(step.is_shell)
        normal = _Step("echo", "hi", "", "h", None, 0, "", _settings())
        self.assertFalse(normal.is_shell)
        substring = _Step("my__SHELL__tool", "a", "", "h", None, 0, "", _settings())
        self.assertFalse(substring.is_shell)

    def test_keeps_multiline_script_and_placeholders(self):
        run_folder = tempfile.mkdtemp(prefix="bq-step-")
        body = "echo {{Job}}\nfor f in {{Workspace}}/*.txt; do\n  cat \"$f\"\ndone\n"
        step = _Step("__SHELL__", body, "", "h", None, 0, "", _settings())
        step.translate_step_to_runnable(_job(run_folder))
        self.assertIn("echo 7", step.shell_script)
        self.assertIn("for f in %s/*.txt" % run_folder, step.shell_script)
        self.assertIn('cat "$f"', step.shell_script)
        self.assertNotIn("__SHELL__", step.shell_script)
        path = step.write_shell_script(run_folder, 0)
        text = open(path).read()
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("echo 7", text)
        self.assertEqual(os.path.basename(path), ".bq_step_0.sh")

    def test_conda_wrap_uses_newlines_for_shell_steps(self):
        env = MagicMock()
        env.ve_type = "conda"
        env.value = "reg"
        env.activation_command = "source /opt/conda.sh"
        step = _Step("__SHELL__", "python run.py", "", "h", env, 0, "", _settings())
        run_folder = tempfile.mkdtemp(prefix="bq-step-")
        step.translate_step_to_runnable(_job(run_folder))
        self.assertTrue(step.shell_script.startswith("source /opt/conda.sh && conda activate reg\n"))
        self.assertIn("\npython run.py", step.shell_script)
        self.assertTrue(step.shell_script.rstrip().endswith("conda deactivate"))

    def test_output_placeholder_keeps_colon(self):
        step = _Step("echo", "{{Output:1-1}}", "", "h", None, 0, "", _settings())
        mapped = _Step._output_file_map("use {{Output:1-1}}", {1: ["/tmp/a.fq"]})
        self.assertEqual(mapped, "use /tmp/a.fq")
        untouched = _Step._output_file_map("use {{Output:2-1}}", {1: ["/tmp/a.fq"]})
        self.assertEqual(untouched, "use {{Output:2-1}}")

    def test_parent_wait_includes_resourcelock(self):
        from QueueDB.models import _JS_FINISHED, _JS_INTERRUPTED, _JS_RESOURCELOCK, _JS_RUNNING, _JS_WRONG

        self.assertEqual(_Step._parent_job_wait_state(_JS_FINISHED), "ready")
        self.assertEqual(_Step._parent_job_wait_state(_JS_RESOURCELOCK), "wait")
        self.assertEqual(_Step._parent_job_wait_state(_JS_RUNNING), "wait")
        self.assertEqual(_Step._parent_job_wait_state(_JS_WRONG), "fail")
        self.assertEqual(_Step._parent_job_wait_state(_JS_INTERRUPTED), "fail")

    def test_sanitize_prediction_clamps_negatives_and_nan(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", _settings())
        cleaned = step._sanitize_prediction(
            {"cpu": -60.0, "mem": -60.0, "disk": 0.0, "vrt_mem": float("nan")}
        )
        self.assertEqual(cleaned["cpu"], 0)
        self.assertEqual(cleaned["mem"], 0)
        self.assertEqual(cleaned["disk"], 0)
        self.assertEqual(cleaned["vrt_mem"], 0)

    def test_sanitize_prediction_keeps_unknown(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", _settings())
        cleaned = step._sanitize_prediction(
            {"cpu": None, "mem": None, "disk": None, "vrt_mem": None}
        )
        self.assertIsNone(cleaned["cpu"])
        self.assertIsNone(cleaned["mem"])

    def test_predict_uses_current_folder_size_not_running_sum(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", _settings())
        job = MagicMock()
        job.run_folder = "/tmp"
        job.input_size = 100
        job.output_size = 0
        predicted = {"cpu": 10, "mem": 20, "disk": 0, "vrt_mem": 20}
        with patch("worker3.step.bases.get_folder_content", return_value=[]), patch(
            "worker3.step.bases.get_folder_size", return_value=50
        ), patch.object(step, "get_training_items", return_value=11), patch.object(
            step, "_predict_factory", return_value=dict(predicted)
        ) as factory:
            out = step.predict_resources_needed(job)
        factory.assert_called_once_with(in_size=50, training_num=11)
        self.assertEqual(job.input_size, 50)
        self.assertEqual(job._folder_size_before, 50)
        self.assertEqual(out["cpu"], 10)
        self.assertEqual(out["learn"], 0)

    def test_predict_caps_cpu_to_env(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", _settings())
        job = MagicMock()
        job.run_folder = "/tmp"
        job.input_size = 0
        with patch("worker3.step.bases.get_folder_content", return_value=[]), patch(
            "worker3.step.bases.get_folder_size", return_value=10
        ), patch.object(step, "get_training_items", return_value=11), patch.object(
            step,
            "_predict_factory",
            return_value={"cpu": 50000, "mem": 1, "disk": 0, "vrt_mem": 1},
        ):
            out = step.predict_resources_needed(job)
        self.assertEqual(out["cpu"], 2 * 95)

    def _ml_settings(self, predict="linear"):
        settings = _settings()
        settings["ml"] = {
            "predict": predict,
            "confidence_weight_disk": "1",
            "confidence_weight_mem": "1",
            "confidence_weight_cpu": "1",
        }
        return settings

    def _equation_rows(self):
        from QueueDB.models import _PD_CPU, _PD_DISK, _PD_MEM, _PD_VRTMEM

        def eq(intercept, slope, kind):
            item = MagicMock()
            item.a = str(intercept)
            item.b = str(slope)
            item.type = kind
            return item

        return [
            eq(100, 5, _PD_DISK),
            eq(200, 7, _PD_MEM),
            eq(300, 9, _PD_CPU),
            eq(400, 11, _PD_VRTMEM),
        ]

    def test_predict_factory_linear_scales_with_size(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", self._ml_settings("linear"))
        with patch("worker3.step.Prediction") as pred:
            pred.objects.filter.return_value = self._equation_rows()
            out = step._predict_factory(in_size=1000, training_num=20)
        self.assertEqual(out["disk"], 100 + 5 * 1000)
        self.assertEqual(out["mem"], 200 + 7 * 1000)
        self.assertEqual(out["cpu"], 300 + 9 * 1000)
        self.assertEqual(out["vrt_mem"], 400 + 11 * 1000)

    def test_predict_factory_base_uses_intercept_only(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", self._ml_settings("base"))
        with patch("worker3.step.Prediction") as pred:
            pred.objects.filter.return_value = self._equation_rows()
            out = step._predict_factory(in_size=1000, training_num=20)
        self.assertEqual(out["disk"], 100)
        self.assertEqual(out["mem"], 200)
        self.assertEqual(out["cpu"], 300)
        self.assertEqual(out["vrt_mem"], 400)

    def test_predict_factory_base_live_regression_ignores_slope(self):
        step = _Step("echo", "hi", "", "h", None, 0, "", self._ml_settings("base"))
        with patch("worker3.step.Prediction") as pred, patch.object(
            step, "_regression_factory", return_value=(2, 10, 3, 20, 4, 30, 5, 40)
        ), patch("worker3.step.logger"):
            pred.objects.filter.return_value = []
            out = step._predict_factory(in_size=100, training_num=11)
        self.assertEqual(out["disk"], 10)
        self.assertEqual(out["mem"], 20)
        self.assertEqual(out["cpu"], 30)
        self.assertEqual(out["vrt_mem"], 40)

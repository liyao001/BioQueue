"""CPU prior parsed from a step command. The parser itself needs no database."""
import unittest
from unittest.mock import MagicMock, patch

from worker.cpu_prior import (
    configured_cpu_budget_units,
    estimate_cpu_units,
    user_cpu_prior_units,
)
from worker.tests.harness import setup_django

_DJANGO_OK, _DJANGO_ERR = setup_django()

if _DJANGO_OK:
    from worker.step import _Step
else:
    _Step = None  # type: ignore


class CpuPriorParserTests(unittest.TestCase):
    def test_keyword_table(self):
        cases = [
            ("echo hello", None),
            ("fastqc {{InputFile}}", None),
            ("bwa mem --threads 8 ref.fa reads.fq", 800),
            ("bwa mem --threads=8 ref.fa reads.fq", 800),
            ("bwa mem --threads='8' ref.fa reads.fq", 800),
            ('bwa mem --threads="8" ref.fa reads.fq', 800),
            ("STAR --genomeDir /idx --runThreadN 16 --readFilesIn a.fq", 1600),
            ("STAR --runThreadN=16 --readFilesIn a.fq", 1600),
            ("STAR --runThreadN16 --readFilesIn a.fq", None),
            ("tool --workers 4 --threads 8 in.fq", 800),
            ("tool --threads 0 --workers 4", 400),
            ("tool --threads 0", None),
            ("tool --threads -1", None),
            ("tool --threads /data/sample_8.fq", None),
            ("tool --umi_len=8 -i in.fq", None),
            ("samtools sort -@ 8 -m 2G in.bam", 800),
            ("samtools sort -@8 in.bam", 800),
            ("samtools view -c -h in.bam", None),
            ("samtools sort -T /tmp/prefix -@ 4 in.bam", 400),
            ("make -j8", 800),
            ("make -j 8", 800),
            ("make -j", None),
            ("java -jar app.jar -t 8", None),
            ("head -n 8 file.txt", None),
            ("macs2 callpeak -t treatment -c control -p 1e-5", None),
            ("macs2 callpeak -p 8", None),
            ("echo -t 8", None),
            ("echo -w 8", None),
            ("echo -p 8", None),
            ("bwa mem -t 8 ref.fa reads.fq", 800),
            ("bwa mem -t8 ref.fa reads.fq", 800),
            ("minimap2 -t 4 ref.fa reads.fq", 400),
            ("bowtie2 -p 8 -x idx -U reads.fq", 800),
            ("hisat2 -p 2 -x idx -U reads.fq", 200),
            ("fastp -i in.fq -w 8 -o out.fq", 800),
            ("fastp -w8 -i in.fq", 800),
            ("fastp -q 20 -i in.fq", None),
            ("featureCounts -T 4 -a genes.gtf -o counts.txt in.bam", 400),
            ("iqtree -s aln.fa -T 2", 200),
            ("blastn -num_threads 8 -query q.fa -db nt", 800),
            ("OMP_NUM_THREADS=8 bwa mem ref.fa reads.fq", 800),
            ("export OMP_NUM_THREADS=4\nbwa mem ref.fa reads.fq", 400),
            ("tool --processes=3 --cpus 2", 300),
            ("megahit -1 a.fq -2 b.fq --num-cpu-threads 6", 600),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(estimate_cpu_units(command, budget_units=3200), expected)

    def test_software_name_enables_short_flag_in_the_parameter(self):
        self.assertEqual(
            estimate_cpu_units("mem -t 8 ref.fa reads.fq", software="bwa"),
            800,
        )
        self.assertEqual(
            estimate_cpu_units("mem -t 8 ref.fa reads.fq", software="/opt/bin/bwa"),
            800,
        )
        self.assertIsNone(estimate_cpu_units("mem -t 8 ref.fa reads.fq", software="echo"))

    def test_later_command_does_not_reuse_an_earlier_tools_short_flag(self):
        command = "bowtie2 -p 2 -x idx reads.fq && macs2 callpeak -t treat -c ctrl -p 8"
        self.assertEqual(estimate_cpu_units(command, software="bowtie2"), 200)

    def test_pipeline_uses_the_max_concurrent_count(self):
        command = "bwa mem -t 4 ref.fa reads.fq | samtools sort -@ 8 -o out.bam"
        self.assertEqual(estimate_cpu_units(command, software="bwa"), 800)

    def test_shell_body(self):
        body = "\n".join(
            [
                "export OMP_NUM_THREADS=4",
                "bwa mem -t 8 ref.fa in.fq > out.sam",
            ]
        )
        self.assertEqual(
            estimate_cpu_units(body, software="__SHELL__"),
            800,
        )

    def test_placeholder_default_and_job_parameter(self):
        self.assertEqual(
            estimate_cpu_units("bwa mem -t {{threads||8}} ref.fa reads.fq", software="bwa"),
            800,
        )
        self.assertIsNone(
            estimate_cpu_units("bwa mem -t {{threads}} ref.fa reads.fq", software="bwa")
        )
        self.assertEqual(
            estimate_cpu_units(
                "bwa mem -t {{threads}} ref.fa reads.fq",
                parameters={"threads": "16"},
                software="bwa",
            ),
            1600,
        )
        self.assertEqual(
            estimate_cpu_units(
                "bwa mem -t {{nt}} ref.fa reads.fq",
                parameters={"nt": "8"},
                software="bwa",
            ),
            800,
        )
        self.assertIsNone(
            estimate_cpu_units("echo hello", parameters={"threads": "8"})
        )
        self.assertIsNone(
            estimate_cpu_units("fastqc {{InputFile}}", parameters={"jobs": "1000"}, budget_units=1600)
        )
        self.assertIsNone(
            estimate_cpu_units(
                "fastp --umi_len={{UMI_LEN||6}} -i in.fq",
                parameters={"UMI_LEN": "8"},
                software="fastp",
            )
        )
        self.assertIsNone(
            estimate_cpu_units(
                "bwa mem -t {{threads||8}} ref.fa",
                parameters={"threads": "/data/not-a-count"},
                software="bwa",
            )
        )

    def test_threadn_and_nproc_use_the_budget(self):
        self.assertEqual(
            estimate_cpu_units("STAR --runThreadN {{ThreadN}}", budget_units=1400),
            1400,
        )
        self.assertEqual(
            estimate_cpu_units("{{Genome}} {{ThreadN}} {{InputFile}}", budget_units=1400),
            1400,
        )
        self.assertIsNone(
            estimate_cpu_units("align.sh --cores {{ ThreadN }}", budget_units=800)
        )
        self.assertIsNone(
            estimate_cpu_units("align.sh {{threadn}}", budget_units=1600)
        )
        self.assertEqual(
            estimate_cpu_units("tool {{ThreadN||8}} in.fq", budget_units=1400),
            800,
        )
        self.assertEqual(
            estimate_cpu_units(
                "tool {{ThreadN}} in.fq",
                parameters={"ThreadN": "4"},
                budget_units=1400,
            ),
            400,
        )
        self.assertEqual(
            estimate_cpu_units("bwa mem --threads $(nproc) ref.fa reads.fq", budget_units=1400),
            1400,
        )
        self.assertEqual(
            estimate_cpu_units("make -j $(nproc --all)", budget_units=1400),
            1400,
        )
        self.assertIsNone(estimate_cpu_units("bwa mem --threads $(nproc) ref.fa reads.fq"))
        self.assertIsNone(estimate_cpu_units("nproc"))

    def test_short_flag_default_and_continuations_match_the_running_command(self):
        self.assertEqual(
            estimate_cpu_units("bwa mem -t {{ncpu||8}} ref.fa reads.fq", software="bwa"),
            800,
        )
        self.assertEqual(
            estimate_cpu_units(
                "bwa mem -t {{ncpu||4}} ref.fa reads.fq",
                parameters={"ncpu": "8"},
                software="bwa",
            ),
            800,
        )
        self.assertEqual(
            estimate_cpu_units("samtools sort -@ {{ncpu||8}} in.bam"),
            800,
        )
        self.assertEqual(
            estimate_cpu_units("bowtie2 \\\n-p 8 -x idx -U reads.fq", software="bowtie2"),
            800,
        )
        self.assertEqual(
            estimate_cpu_units("STAR --runThreadN \\\n16 --readFilesIn a.fq"),
            1600,
        )
        self.assertIsNone(estimate_cpu_units("squeue -j 123456"))
        self.assertIsNone(estimate_cpu_units("scancel -j 99999", budget_units=1600))
        self.assertEqual(
            estimate_cpu_units("bowtie2 -p 2 -x idx r.fq | macs2 callpeak -p 8", software="bowtie2"),
            200,
        )
        self.assertEqual(
            estimate_cpu_units("# OMP_NUM_THREADS=32\nbwa mem -t 2 ref.fa reads.fq", software="bwa"),
            200,
        )
        self.assertIsNone(estimate_cpu_units('echo "--threads 32"'))
        self.assertEqual(
            estimate_cpu_units('bwa mem --threads "8" ref.fa reads.fq', software="bwa"),
            800,
        )

    def test_absurd_count_is_capped_to_the_budget(self):
        self.assertEqual(
            estimate_cpu_units("bwa mem --threads 99999 ref.fa", software="bwa", budget_units=1400),
            1400,
        )
        self.assertEqual(
            estimate_cpu_units("bwa mem --threads 8 ref.fa", software="bwa", budget_units=1400),
            800,
        )

    def test_configured_budget_is_the_smaller_machine_or_cluster_cap(self):
        self.assertEqual(
            configured_cpu_budget_units({"env": {"cpu": "14"}, "cluster": {"type": ""}}),
            1400,
        )
        self.assertEqual(
            configured_cpu_budget_units(
                {"env": {"cpu": "14"}, "cluster": {"type": "Slurm", "cpu": "4"}}
            ),
            400,
        )
        self.assertEqual(
            configured_cpu_budget_units({"env": {}, "cluster": {"type": "Slurm", "cpu": "8"}}),
            800,
        )
        self.assertIsNone(configured_cpu_budget_units({"env": {}, "cluster": {"type": ""}}))

    def test_user_prior_is_cpu_units_and_unset_when_non_positive(self):
        self.assertIsNone(user_cpu_prior_units(-1))
        self.assertIsNone(user_cpu_prior_units(0))
        self.assertIsNone(user_cpu_prior_units(None))
        self.assertEqual(user_cpu_prior_units(100), 100)
        self.assertEqual(user_cpu_prior_units(400, budget_units=1400), 400)
        self.assertEqual(user_cpu_prior_units(999999, budget_units=1400), 1400)


def _predict_settings(cpu="16", cluster_type="", cluster_cpu=""):
    return {
        "env": {"workspace": "/tmp", "cpu": str(cpu), "memory": str(8 * 1024 ** 3)},
        "cluster": {"type": cluster_type, "cpu": str(cluster_cpu)},
        "ml": {
            "predict": "base",
            "confidence_weight_disk": "1",
            "confidence_weight_mem": "1",
            "confidence_weight_cpu": "1",
        },
    }


class _Job(object):
    def __init__(self, options=None, raw_parameter=None):
        self.run_folder = "/tmp"
        self.input_size = 0
        self.output_size = 0
        self.user_options = options
        self._parameter = raw_parameter


class CpuPriorPredictionTests(unittest.TestCase):
    def setUp(self):
        if _Step is None:
            self.skipTest("worker django deps unavailable: %s" % _DJANGO_ERR)

    def _predict(self, step, job, training_num=0, equations=None, fitted=None):
        training = MagicMock()
        training.id = 1
        equations = [] if equations is None else equations
        patches = [
            patch("worker.step.bases.get_folder_content", return_value=[]),
            patch("worker.step.bases.get_folder_size", return_value=50),
            patch.object(step, "get_training_items", return_value=training_num),
            patch("worker.step.Prediction") ,
            patch("worker.step.Training", return_value=training),
            patch("worker.step.logger"),
        ]
        if fitted is not None:
            patches.append(patch.object(step, "_regression_factory", return_value=fitted))
        started = [item.start() for item in patches]
        try:
            started[3].objects.filter.return_value = equations
            return step.predict_resources_needed(job)
        finally:
            for item in patches:
                item.stop()

    def test_no_keyword_leaves_cpu_unknown_for_the_one_core_fallback(self):
        step = _Step("fastqc", "{{InputFile}}", "", "h", None, 0, "", _predict_settings())
        out = self._predict(step, _Job())
        self.assertIsNone(out["cpu"])

    def test_threadn_token_reserves_the_configured_cores(self):
        step = _Step(
            "align",
            "{{Genome}} {{ThreadN}} {{InputFile}}",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="16"),
        )
        out = self._predict(step, _Job())
        self.assertEqual(out["cpu"], 1600)

        cluster = _Step(
            "align",
            "-@ {{ThreadN}} {{InputFile}}",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="16", cluster_type="Slurm", cluster_cpu="8"),
        )
        out = self._predict(cluster, _Job())
        self.assertEqual(out["cpu"], 800)

    def test_threads_flag_reserves_that_many_cores(self):
        step = _Step(
            "bwa",
            "mem --threads 8 ref.fa {{InputFile}}",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="16"),
        )
        out = self._predict(step, _Job())
        self.assertEqual(out["cpu"], 800)

    def test_job_parameter_counts_before_substitution(self):
        step = _Step(
            "bwa",
            "mem -t {{threads}} ref.fa {{InputFile}}",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="16"),
        )
        out = self._predict(step, _Job())
        self.assertIsNone(out["cpu"])
        out = self._predict(step, _Job(options={"threads": "8"}))
        self.assertEqual(out["cpu"], 800)
        raw = _Job(options=None, raw_parameter="threads=8;umi_len=6")
        out = self._predict(step, raw)
        self.assertEqual(out["cpu"], 800)

    def test_user_cpu_prior_beats_the_command_parse(self):
        step = _Step(
            "bwa",
            "mem --threads 16 ref.fa reads.fq",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="32"),
            cpu_prior=100,
        )
        out = self._predict(step, _Job())
        self.assertEqual(out["cpu"], 100)
        unset = _Step(
            "bwa",
            "mem --threads 8 ref.fa reads.fq",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="16"),
            cpu_prior=-1,
        )
        out = self._predict(unset, _Job())
        self.assertEqual(out["cpu"], 800)

    def test_saved_prediction_beats_the_command_parse(self):
        from QueueDB.models import _PD_CPU, _PD_DISK, _PD_MEM

        def eq(intercept, slope, kind):
            item = MagicMock()
            item.a = str(intercept)
            item.b = str(slope)
            item.type = kind
            return item

        step = _Step(
            "STAR",
            "--runThreadN 16 --readFilesIn {{InputFile}}",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="32"),
        )
        out = self._predict(
            step,
            _Job(),
            training_num=0,
            equations=[eq(100, 0, _PD_DISK), eq(200, 0, _PD_MEM), eq(300, 9, _PD_CPU)],
        )
        self.assertEqual(out["cpu"], 300)

    def test_training_regression_beats_the_command_parse(self):
        step = _Step(
            "bwa",
            "mem -t 16 ref.fa reads.fq",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="32"),
        )
        out = self._predict(
            step,
            _Job(),
            training_num=11,
            fitted=(2, 10, 3, 20, 4, 30, 5, 40),
        )
        self.assertEqual(out["cpu"], 30)

    def test_absurd_thread_count_is_capped_to_the_configured_budget(self):
        step = _Step(
            "bwa",
            "mem --threads 99999 ref.fa reads.fq",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="14"),
        )
        out = self._predict(step, _Job())
        self.assertEqual(out["cpu"], 1400)

        clustered = _Step(
            "bwa",
            "mem --threads 32 ref.fa reads.fq",
            "",
            "h",
            None,
            0,
            "",
            _predict_settings(cpu="32", cluster_type="Slurm", cluster_cpu="4"),
        )
        out = self._predict(clustered, _Job())
        self.assertEqual(out["cpu"], 400)

    def test_protocol_passes_an_explicit_cpu_prior(self):
        from types import SimpleNamespace

        from worker.queue.protocol import Protocol

        db_step = SimpleNamespace(
            software="bwa",
            parameter="mem --threads 8 ref.fa",
            specify_output="",
            hash="abc",
            env=None,
            version_check="",
            force_local=0,
            gpu_step=0,
            cpu_prior=400,
        )
        proto = Protocol.__new__(Protocol)
        proto._settings = _predict_settings()
        proto.raw_steps = [db_step]
        step = proto.customize_steps_by_user_dir(None, None)[0]
        self.assertEqual(step._cpu_prior, 400)
        out = self._predict(step, _Job())
        self.assertEqual(out["cpu"], 400)

        bare = SimpleNamespace(
            software="echo",
            parameter="hi",
            specify_output="",
            hash="abc",
            env=None,
            version_check="",
            force_local=0,
            gpu_step=0,
        )
        proto.raw_steps = [bare]
        step = proto.customize_steps_by_user_dir(None, None)[0]
        self.assertEqual(step._cpu_prior, -1)

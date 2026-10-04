import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from QueueDB.models import Job, ProtocolList, Reference, Step
from QueueDB.protocol_template import (
    ProtocolTemplateError,
    expand_document,
    expand_job,
    normalize_template,
    step_template_hash,
    template_input_files,
)
from ui.tests import Ui3TestCase


def _procap():
    return {
        "name": "PROcap",
        "description": "two replicates, one body",
        "samples": {
            "group": 2,
            "name": "rep{{index}}",
            "fields": {"umi_len": "{{UMI_LEN||6}}"},
        },
        "blocks": {
            "align": {
                "steps": [
                    {
                        "software": "fastp",
                        "parameter": "-i {{sample.r1}} -I {{sample.r2}} --umi_len={{sample.umi_len}} -o {{sample.prefix}}.1.fq.gz",
                        "outputs": {"clean": "{{sample.prefix}}.1.fq.gz"},
                    },
                    {
                        "software": "STAR",
                        "parameter": "--readFilesIn {{sample.clean}} --outFileNamePrefix {{sample.prefix}}_",
                        "outputs": {"bam": "{{sample.prefix}}_Aligned.sortedByCoord.out.bam"},
                    },
                    {
                        "software": "umi_tools",
                        "parameter": "dedup -I {{sample.bam}} -S {{sample.prefix}}.bam",
                        "outputs": {"dedup_bam": "{{sample.prefix}}.bam"},
                    },
                ]
            },
            "pints": {
                "steps": [
                    {
                        "software": "pints_visualizer",
                        "parameter": "-b {{bam}} -o {{JobName}}_{{tag}} {{flags}}",
                    }
                ]
            },
        },
        "pipeline": [
            {"software": "mkdir", "parameter": "raw_qc"},
            {"software": "fastqc", "parameter": "{{InputFile}}"},
            {
                "map": "samples",
                "steps": [
                    {"call": "align"},
                    {
                        "call": "pints",
                        "args": {
                            "bam": "{{sample.dedup_bam}}",
                            "tag": "{{sample.name}}_rpm",
                            "flags": "--rpm",
                        },
                    },
                ],
            },
            {
                "software": "samtools",
                "parameter": "merge -fh {{samples.first.dedup_bam}} {{JobName}}_merged.bam {{samples.dedup_bam}}",
                "outputs": {"merged_bam": "{{JobName}}_merged.bam"},
            },
            {
                "call": "pints",
                "args": {"bam": "{{shared.merged_bam}}", "tag": "merged", "flags": ""},
            },
        ],
    }


class TemplateExpandTests(SimpleTestCase):
    def test_import_defers_sample_count_and_metadata_checks(self):
        document = {
            "pipeline": [
                {"software": "echo", "parameter": "{{samples.3.r1}}"},
                {"map": "samples", "steps": [{"software": "echo", "parameter": "{{sample.condition}}"}]},
            ]
        }
        normalized = json.loads(normalize_template(document))
        sheet = json.dumps([{"condition": "treated"}] * 3)
        steps = expand_document(normalized, "a;b;c", sheet)
        self.assertEqual(steps[0].parameter, "{{InputFile:3}}")
        self.assertEqual([s.parameter for s in steps[1:]], ["treated"] * 3)
        with self.assertRaises(ProtocolTemplateError):
            expand_document(normalized, "a;b", sheet)
        with self.assertRaises(ProtocolTemplateError):
            expand_document(normalized, "a;b;c", "")

    def test_import_still_rejects_invalid_structure(self):
        invalid = [
            {"pipeline": []},
            {"pipeline": [{"call": "missing"}]},
            {"pipeline": [{"call": "cycle"}], "blocks": {"cycle": {"steps": [{"call": "cycle"}]}}},
            {"pipeline": [{"software": "echo", "outputs": ["bad"]}]},
            {"pipeline": [{"map": "samples", "steps": "bad"}]},
            {"pipeline": [{"software": "echo", "parameter": "{{sample.r1}}"}]},
        ]
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ProtocolTemplateError):
                normalize_template(document)

    def test_effective_inputs_follow_the_same_slot_order(self):
        self.assertEqual(template_input_files(" a ;; b ;c;d;", ""), ["a", "b", "c", "d"])
        sheet = json.dumps([{"r1": "a", "r2": "b"}, {"files": ["c", "d"]}])
        self.assertEqual(template_input_files("ignored", sheet), ["a", "b", "c", "d"])

    def test_map_then_join(self):
        steps = expand_document(_procap(), "a;b;c;d", "")
        fastp = [step for step in steps if step.software == "fastp"]
        self.assertEqual(len(fastp), 2)
        self.assertIn("{{InputFile:1}}", fastp[0].parameter)
        self.assertIn("{{InputFile:2}}", fastp[0].parameter)
        self.assertIn("{{InputFile:3}}", fastp[1].parameter)
        self.assertIn("{{InputFile:4}}", fastp[1].parameter)
        self.assertIn("{{UMI_LEN||6}}", fastp[0].parameter)
        self.assertIn("{{JobName}}_rep1.1.fq.gz", fastp[0].parameter)
        self.assertIn("{{JobName}}_rep2.1.fq.gz", fastp[1].parameter)

        star = [step for step in steps if step.software == "STAR"]
        raw = "--readFilesIn {{sample.clean}} --outFileNamePrefix {{sample.prefix}}_"
        self.assertEqual(star[0].hash, star[1].hash)
        self.assertEqual(star[0].hash, step_template_hash("STAR", raw))
        self.assertIn("{{JobName}}_rep1.1.fq.gz", star[0].parameter)
        self.assertIn("{{JobName}}_rep2_", star[1].parameter)

        merge = [step for step in steps if step.software == "samtools"][0]
        self.assertEqual(
            merge.parameter,
            "merge -fh {{JobName}}_rep1.bam {{JobName}}_merged.bam {{JobName}}_rep1.bam {{JobName}}_rep2.bam",
        )
        pints = [step for step in steps if step.software == "pints_visualizer"]
        self.assertEqual(len(pints), 3)
        self.assertIn("-o {{JobName}}_rep1_rpm", pints[0].parameter)
        self.assertIn("-o {{JobName}}_merged", pints[2].parameter)
        self.assertIn("{{JobName}}_merged.bam", pints[2].parameter)
        self.assertEqual(steps[0].software, "mkdir")
        self.assertEqual(steps[1].parameter, "{{InputFile}}")

    def test_sample_sheet_overrides_one_replicate(self):
        sheet = json.dumps([{"umi_len": "8"}, {"name": "treated", "umi_len": "6"}])
        steps = expand_document(_procap(), "a;b;c;d", sheet)
        fastp = [step for step in steps if step.software == "fastp"]
        self.assertIn("--umi_len=8", fastp[0].parameter)
        self.assertIn("{{JobName}}_treated.1.fq.gz", fastp[1].parameter)
        self.assertIn("--umi_len=6", fastp[1].parameter)

    def test_explicit_files_ignore_input_count(self):
        sheet = json.dumps(
            [
                {"name": "rep1", "r1": "/data/a_R1.fq", "r2": "/data/a_R2.fq"},
                {"name": "rep2", "r1": "/data/b_R1.fq", "r2": "/data/b_R2.fq"},
            ]
        )
        steps = expand_document(_procap(), "", sheet)
        fastp = [step for step in steps if step.software == "fastp"]
        self.assertIn("/data/a_R1.fq", fastp[0].parameter)
        self.assertIn("/data/b_R2.fq", fastp[1].parameter)

    def test_uneven_inputs_are_rejected(self):
        with self.assertRaises(ProtocolTemplateError):
            expand_document(_procap(), "a;b;c", "")

    def test_plain_protocol_is_not_expanded(self):
        proto = ProtocolList(name="plain", template="")
        self.assertIsNone(expand_job(proto, "a;b", ""))


class TemplateUiTests(Ui3TestCase):
    def test_parameters_load_after_sample_prefill_before_input_files(self):
        proto = self._indexed_protocol()
        document = json.loads(proto.template)
        document["pipeline"].append({"software": "report", "parameter": "{{API_KEY}} {{API_SECRET}}"})
        proto.template = normalize_template(document)
        proto.save()
        for inputs, count in (("", 1), ("a;b;c;d", 2)):
            sample_response = self.client.get(reverse("ui3:sample_scaffold"), {
                "protocol": proto.id, "input_file": inputs, "force": "1",
            })
            sheet = sample_response.context["samples_value"]
            # The browser sends these prefilled records while inputs are still
            # empty, then refreshes again when the files are entered.
            response = self.client.get(reverse("ui3:parameter_scaffold"), {
                "protocol": proto.id, "input_file": inputs, "sample_sheet": sheet,
                "force": "1", "format": "text",
            })
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "API_KEY=;API_SECRET=;")
            self.assertContains(response, f"UMI_LEN{count}=6;")

    def test_parameter_preview_uses_metadata_row_count_without_real_inputs(self):
        proto = self._indexed_protocol()
        response = self.client.get(reverse("ui3:parameter_scaffold"), {
            "protocol": proto.id, "sample_sheet": '[{"name":"a"},{"name":"b"},{"name":"c"}]', "format": "text",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UMI_LEN3=6;")
        # Preview inputs must never make an incomplete job executable.
        response = self.client.post(reverse("ui3:job_create"), {
            "protocol": proto.id, "job_name": "no-inputs", "sample_sheet": '[{"name":"a"}]',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Job.objects.filter(job_name="no-inputs").exists())

    def test_sample_scaffold_uses_declared_fields_and_preserves_parameter_links(self):
        from ui.services import sample_scaffold, parameter_scaffold

        proto = self._indexed_protocol()
        context = sample_scaffold(proto, "a;b;c;d;")
        rows = json.loads(context["samples_value"])
        self.assertEqual([row["name"] for row in rows], ["rep1", "rep2"])
        self.assertEqual(rows[0]["umi_len"], "{{UMI_LEN1||6}}")
        self.assertEqual(rows[1]["adapter_r2"], "{{ADAPT2_2||TGCA}}")
        self.assertEqual(set(rows[0]), {"name", "umi_len", "umi_loc", "adapter_r1", "adapter_r2"})
        self.assertEqual(context["samples_required"], "")
        self.assertEqual(
            parameter_scaffold(proto, self.user, input_file="a;b;c;d"),
            parameter_scaffold(proto, self.user, input_file="a;b;c;d", sample_sheet=context["samples_value"]),
        )

    def test_sample_scaffold_discovers_required_metadata_and_optional_defaults(self):
        from ui.services import sample_scaffold, prepare_sample_sheet

        payload = {"name": "metadata", "pipeline": [{"map": "samples", "steps": [
            {"software": "echo", "parameter": "{{sample.condition}} {{sample.batch||control}}", "outputs": {"bam": "out"}},
            {"software": "echo", "parameter": "{{sample.bam}}"},
        ]}]}
        self.assertEqual(self._import(payload).status_code, 302)
        proto = ProtocolList.objects.get(name="metadata")
        context = sample_scaffold(proto)
        self.assertEqual(json.loads(context["samples_value"]), [{"name": "rep1", "batch": "control", "condition": ""}])
        self.assertEqual(context["samples_required"], "condition")
        with self.assertRaisesRegex(ProtocolTemplateError, "provide a value for 'condition'"):
            prepare_sample_sheet(proto, "a", context["samples_value"])

    def test_sample_scaffold_preserves_links_when_sample_is_renamed(self):
        from ui.services import sample_scaffold

        payload = {"samples": {"fields": {"label": "{{sample.name}}", "r1": "ignored"}}, "pipeline": [
            {"map": "samples", "steps": [{"software": "echo", "parameter": "{{sample.label}} {{sample.r1}}"}]},
        ]}
        proto = ProtocolList(template=normalize_template(payload))
        rows = json.loads(sample_scaffold(proto)["samples_value"])
        self.assertEqual(rows, [{"name": "rep1", "label": "{{sample.name}}"}])
        rows[0]["name"] = "C1a"
        self.assertEqual(expand_job(proto, "a", json.dumps(rows))[0].parameter, "C1a {{InputFile:1}}")

    def test_sample_scaffold_endpoint_visibility_and_permissions(self):
        proto = self._indexed_protocol()
        url = reverse("ui3:sample_scaffold")
        response = self.client.get(url, {"protocol": proto.id, "input_file": "a;b;c;d", "force": "1"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "var active = true;")
        self.assertContains(response, "UMI_LEN2")
        self.assertNotContains(response, "<html")
        response = self.client.get(url, {"protocol": self.protocol.id})
        self.assertContains(response, "var active = false;")
        self.login("bob")
        response = self.client.get(url, {"protocol": proto.id})
        self.assertContains(response, "var active = false;")
        self.assertNotContains(response, "UMI_LEN")

    def test_samples_hidden_for_plain_protocol_and_visible_for_template_clone(self):
        proto = self._indexed_protocol()
        self.assertContains(self.client.get(reverse("ui3:job_create")), 'id="sample-fields" class="hidden"')
        clone = self.make_job(protocol=proto, sample_sheet='[{"name":"custom"}]')
        response = self.client.get(reverse("ui3:job_create"), {"clone": clone.id})
        self.assertContains(response, 'id="sample-fields">')
        self.assertContains(response, "custom")
        response = self.client.post(reverse("ui3:job_create"), {
            "protocol": self.protocol.id, "job_name": "plain", "sample_sheet": "stale invalid text",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Job.objects.get(job_name="plain").sample_sheet, "")

    def test_sample_json_syntax_and_shape_rejected_before_job_creation(self):
        proto = self._indexed_protocol()
        for sheet in ('[{', '{}', '[1]'):
            with self.subTest(sheet=sheet):
                response = self.client.post(reverse("ui3:job_create"), {
                    "protocol": proto.id, "job_name": "invalid-json", "input_file": "a;b", "sample_sheet": sheet,
                })
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, 'id="sample-fields">', status_code=400)
                self.assertFalse(Job.objects.filter(job_name="invalid-json").exists())

    def test_template_json_validation_on_save_preserves_saved_protocol(self):
        proto = self._indexed_protocol()
        original = proto.template
        for value in ('{', '[]', '{"pipeline":[{"call":"missing"}]}'):
            for htmx in (False, True):
                with self.subTest(value=value, htmx=htmx):
                    response = self.client.post(reverse("ui3:protocol_update", args=[proto.id]), {
                        "name": "changed", "template": value,
                    }, **({"HTTP_HX_REQUEST": "true"} if htmx else {}))
                    self.assertEqual(response.status_code, 400)
                    proto.refresh_from_db()
                    self.assertEqual(proto.template, original)
                    self.assertEqual(proto.name, "PROcap")
        response = self.client.get(reverse("ui3:protocols"), {"select": proto.id})
        self.assertContains(response, "ui3.validateJsonField(this, 'template')")

    def test_import_and_create_with_required_sample_metadata(self):
        payload = {
            "name": "metadata",
            "pipeline": [{"map": "samples", "steps": [{"software": "echo", "parameter": "{{sample.condition}}"}]}],
        }
        self.assertEqual(self._import(payload).status_code, 302)
        proto = ProtocolList.objects.get(name="metadata", user=self.user)
        fields = {"job_name": "metadata-job", "protocol": proto.id, "input_file": "a"}
        self.assertEqual(self.client.post(reverse("ui3:job_create"), fields).status_code, 400)
        fields["sample_sheet"] = '[{"condition":"treated"}]'
        self.assertEqual(self.client.post(reverse("ui3:job_create"), fields).status_code, 302)

    def _import(self, payload):
        self.login()
        upload = SimpleUploadedFile(
            "procap.json",
            json.dumps(payload).encode(),
            content_type="application/json",
        )
        return self.client.post(reverse("ui3:protocol_import"), {"file": upload})

    def test_import_shows_outline_and_join(self):
        response = self._import(_procap())
        self.assertEqual(response.status_code, 302)
        proto = ProtocolList.objects.get(name="PROcap", user=self.user)
        self.assertEqual(Step.objects.filter(parent=proto).count(), 0)
        self.assertTrue(proto.template)
        self.assertTrue(proto.ver)
        page = self.client.get(reverse("ui3:protocols") + "?select={}".format(proto.id))
        self.assertContains(page, "for each sample")
        self.assertContains(
            page,
            "merge -fh {{JobName}}_rep1.bam {{JobName}}_merged.bam {{JobName}}_rep1.bam {{JobName}}_rep2.bam",
        )
        exported = self.client.get(reverse("ui3:protocol_export", args=[proto.id]))
        body = json.loads(exported.content.decode())
        self.assertIn("pipeline", body)
        self.assertNotIn("step", body)
        self.assertEqual(body["name"], "PROcap")

    def test_export_reimport_preserves_template_and_expansion(self):
        self.assertEqual(self._import(_procap()).status_code, 302)
        original = ProtocolList.objects.get(name="PROcap", user=self.user)
        response = self.client.get(reverse("ui3:protocol_export", args=[original.id]))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        payload["name"] = "PROcap imported again"
        self.assertEqual(self._import(payload).status_code, 302)
        restored = ProtocolList.objects.get(name=payload["name"], user=self.user)
        self.assertEqual(restored.template, original.template)
        self.assertEqual(restored.ver, original.ver)
        self.assertEqual(restored.description, original.description)
        sheet = json.dumps([{"name": "control", "umi_len": "8"}, {"name": "treated"}])
        before = expand_job(original, "a;b;c;d", sheet)
        after = expand_job(restored, "a;b;c;d", sheet)
        signature = lambda steps: [(step.software, step.parameter, step.version_check, step.hash) for step in steps]
        self.assertEqual(signature(after), signature(before))

    def test_protocol_list_and_job_picker_mark_templates(self):
        self._import(_procap())
        proto = ProtocolList.objects.get(name="PROcap", user=self.user)
        page = self.client.get(reverse("ui3:protocols") + "?select={}".format(proto.id))
        self.assertContains(page, "tpl-badge")
        options = self.client.get(reverse("ui3:protocol_options"))
        self.assertContains(options, "(template)")
        self.assertContains(options, proto.name)

    def test_sample_scaffold_warns_when_files_do_not_divide_evenly(self):
        proto = self._indexed_protocol()
        response = self.client.get(reverse("ui3:sample_scaffold"), {
            "protocol": proto.id, "input_file": "a;b;c;d;e",
        })
        self.assertContains(response, "cannot be split evenly")
        self.assertContains(response, "2 files per sample")
        self.assertNotContains(response, "samples.group")
        self.assertContains(response, "var hold = true")
        self.assertNotContains(response, "rep2")

    def test_create_job_rejects_a_partial_group(self):
        self._import(_procap())
        proto = ProtocolList.objects.get(name="PROcap", user=self.user)
        response = self.client.post(
            reverse("ui3:job_create"),
            {
                "job_name": "partial",
                "protocol": proto.id,
                "input_file": "a;b;c",
                "parameter": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "not divisible", status_code=400)
        self.assertFalse(Job.objects.filter(job_name="partial").exists())

    def test_create_job_stores_sample_sheet(self):
        self._import(_procap())
        proto = ProtocolList.objects.get(name="PROcap", user=self.user)
        sheet = json.dumps([{"name": "rep1"}, {"name": "rep2", "umi_len": "9"}])
        response = self.client.post(
            reverse("ui3:job_create"),
            {
                "job_name": "paired",
                "protocol": proto.id,
                "input_file": "a;b;c;d",
                "parameter": "",
                "sample_sheet": sheet,
            },
        )
        self.assertEqual(response.status_code, 302)
        job = Job.objects.get(job_name="paired")
        self.assertEqual(json.loads(job.sample_sheet)[1]["umi_len"], "9")
        steps = expand_job(job.protocol, job.input_file, job.sample_sheet)
        fastp = [step.parameter for step in steps if step.software == "fastp"]
        self.assertIn("--umi_len=9", fastp[1])

    def test_scaffold_uses_template_keys(self):
        self._import(_procap())
        proto = ProtocolList.objects.get(name="PROcap", user=self.user)
        response = self.client.get(
            reverse("ui3:parameter_scaffold"),
            {"protocol": proto.id, "format": "text"},
        )
        body = response.content.decode()
        self.assertIn("UMI_LEN=", body)
        self.assertNotIn("sample", body)
        self.assertNotIn("InputFile=", body)
        self.assertNotIn("JobName=", body)
        self.assertEqual(body, "UMI_LEN=6;")  # Block arguments are already bound.

    def _indexed_protocol(self):
        payload = _procap()
        payload["samples"]["fields"] = {
            "umi_len": "{{UMI_LEN{{index}}||6}}",
            "umi_loc": "{{UMI_LOC{{index}}||per_read}}",
            "adapter_r1": "{{ADAPT{{index}}_1||ACGT}}",
            "adapter_r2": "{{ADAPT{{index}}_2||TGCA}}",
        }
        payload["blocks"]["align"]["steps"][0]["parameter"] += (
            " --umi_loc {{sample.umi_loc}} -a {{sample.adapter_r1}}"
            " -A {{sample.adapter_r2}} --index {{STAR_INDEX}}"
        )
        # Unused blocks must not contribute parameters.
        payload["blocks"]["unused"] = {"steps": [{"software": "echo", "parameter": "{{UNUSED}}"}]}
        self.assertEqual(self._import(payload).status_code, 302)
        return ProtocolList.objects.get(name="PROcap", user=self.user)

    def test_scaffold_resolves_indices_and_adapter_suffixes(self):
        proto = self._indexed_protocol()
        for count in (1, 2, 3):
            with self.subTest(count=count):
                response = self.client.get(reverse("ui3:parameter_scaffold"), {
                    "protocol": proto.id, "format": "text",
                    "input_file": ";".join("file{}".format(i) for i in range(count * 2)),
                })
                self.assertEqual(response.status_code, 200)
                keys = set(response.content.decode().split(";")) - {""}
                expected = {"STAR_INDEX="}
                for i in range(1, count + 1):
                    expected.update({f"UMI_LEN{i}=6", f"UMI_LOC{i}=per_read", f"ADAPT{i}_1=ACGT", f"ADAPT{i}_2=TGCA"})
                self.assertEqual(keys, expected)

    def test_scaffold_previews_one_sample_before_inputs(self):
        proto = self._indexed_protocol()
        response = self.client.get(reverse("ui3:parameter_scaffold"), {"protocol": proto.id, "format": "text"})
        self.assertContains(response, "ADAPT1_1=ACGT;ADAPT1_2=TGCA;")
        self.assertNotContains(response, "{{")
        self.assertNotContains(response, "UMI_LEN2")

    def test_scaffold_uses_sheet_files_overrides_and_visible_references(self):
        proto = self._indexed_protocol()
        Reference.objects.create(name="STAR_INDEX", path="/index", user=self.user)
        sheet = json.dumps([
            {"r1": "a", "r2": "b", "umi_len": "8"},
            {"r1": "c", "r2": "d", "adapter_r2": "{{CUSTOM_ADAPTER}}"},
        ])
        response = self.client.get(reverse("ui3:parameter_scaffold"), {
            "protocol": proto.id, "format": "text", "input_file": "ignored",
            "sample_sheet": sheet,
        })
        self.assertContains(response, "UMI_LEN2=6;")
        self.assertContains(response, "CUSTOM_ADAPTER=;")
        self.assertNotContains(response, "UMI_LEN1=")
        self.assertNotContains(response, "ADAPT2_2=")
        self.assertNotContains(response, "STAR_INDEX=")

    def test_scaffold_keeps_current_values_while_inputs_are_incomplete(self):
        proto = self._indexed_protocol()
        for data in ({"input_file": "a;b;c"}, {"sample_sheet": '[{"name":'}):
            with self.subTest(data=data):
                response = self.client.get(reverse("ui3:parameter_scaffold"), {
                    "protocol": proto.id, **data,
                }, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 204)
                self.assertEqual(response.content, b"")

    def test_scaffold_htmx_page_and_private_protocol(self):
        proto = self._indexed_protocol()
        page = self.client.get(reverse("ui3:job_create"))
        self.assertContains(page, "input from:#id_input_file delay:400ms")
        self.assertContains(page, "input from:#id_sample_sheet delay:400ms")
        self.assertContains(page, 'hx-include="#id_protocol, #id_input_file, #id_sample_sheet"')
        response = self.client.get(reverse("ui3:parameter_scaffold"), {
            "protocol": proto.id, "input_file": "a;b;c;d",
        }, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "ui3/jobs/_parameter_scaffold.html")
        self.assertContains(response, "UMI_LEN2")
        self.assertNotContains(response, "<html")
        self.login("bob")
        response = self.client.get(reverse("ui3:parameter_scaffold"), {"protocol": proto.id, "format": "text"})
        self.assertEqual(response.content, b"")

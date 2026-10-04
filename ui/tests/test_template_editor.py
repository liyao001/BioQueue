import json

from django.urls import reverse

from QueueDB.models import ProtocolList, VirtualEnvironment
from QueueDB.protocol_template import ProtocolTemplateError, expand_job, normalize_template
from ui import services
from ui.tests import Ui3TestCase


def document(env="analysis"):
    return {
        "samples": {"group": 1},
        "blocks": {"align": {"steps": [
            {"software": "echo", "parameter": "{{sample.r1}}", "env": env,
             "force_local": True, "gpu_step": True, "outputs": {"bam": "out.bam"}},
        ]}},
        "pipeline": [{"map": "samples", "steps": [{"call": "align"}]}],
    }


class TemplateEditorTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self.env = VirtualEnvironment.objects.create(user=self.user, name="analysis", value="analysis")
        self.protocol.template = normalize_template(document())
        self.protocol.save()
        self.login()

    def draft(self, action, path=None, **values):
        return self.client.post(reverse("ui3:protocol_template_edit", args=[self.protocol.id]), {
            "template": self.protocol.template, "template_mode": "visual", "editor_action": action,
            "editor_path": json.dumps(path or []), **values,
        }, HTTP_HX_REQUEST="true")

    def test_environments_and_flags_survive_expansion(self):
        steps = expand_job(self.protocol, "a;b", "")
        self.assertEqual(len(steps), 2)
        self.assertTrue(all(step.env == self.env and step.force_local and step.gpu_step for step in steps))

    def test_public_environment_and_owner_precedence(self):
        public = VirtualEnvironment.objects.create(name="analysis", user=None, value="public")
        self.assertEqual(expand_job(self.protocol, "a", "")[0].env, self.env)
        self.env.delete()
        self.assertEqual(expand_job(self.protocol, "a", "")[0].env, public)
        public.delete()
        VirtualEnvironment.objects.create(name="analysis", user=self.other, value="private")
        with self.assertRaisesRegex(ProtocolTemplateError, "missing, inaccessible"):
            expand_job(self.protocol, "a", "")

    def test_export_import_retains_environment_and_flags(self):
        self.env.recipe = "name: analysis\ndependencies:\n  - bwa\n"
        self.env.save(update_fields=["recipe"])
        payload = services.protocol_json_payload(self.protocol, self.user)
        self.assertEqual(payload["environment"]["analysis"]["recipe"], self.env.recipe)
        self.assertEqual(payload["environment"]["analysis"]["value"], "analysis")
        self.assertNotIn("environment", json.loads(self.protocol.template))
        payload["name"] = "imported"
        proto, _, notes = services.import_protocol_from_json(self.user, payload)
        self.assertEqual(notes, [])
        self.assertNotIn("environment", json.loads(proto.template))
        self.assertEqual(json.loads(proto.template)["blocks"]["align"]["steps"][0]["env"], "analysis")
        self.assertEqual(expand_job(proto, "a", "")[0].env, self.env)

    def test_import_creates_missing_environment_and_rolls_back(self):
        self.env.delete()
        payload = services.protocol_json_payload(self.protocol, self.user)
        payload["name"] = "fresh"
        payload["environment"]["analysis"]["recipe"] = "name: analysis\n"
        proto, _, _ = services.import_protocol_from_json(self.user, payload)
        created = VirtualEnvironment.objects.get(name="analysis", user=self.user)
        self.assertEqual(created.recipe, "name: analysis\n")
        self.assertEqual(expand_job(proto, "a", "")[0].env, created)

        broken = document()
        broken["blocks"]["align"]["steps"].append({"software": "echo", "parameter": "x", "env": "missing"})
        broken["name"] = "partial"
        broken["environment"] = {
            "analysis": {"ve_type": "conda", "recipe": "name: analysis\n", "value": "analysis"},
            "brandnew": {"ve_type": "conda", "recipe": "name: brandnew\n", "value": "brandnew"},
        }
        with self.assertRaises(services.ProtocolImportError):
            services.import_protocol_from_json(self.user, broken)
        self.assertFalse(VirtualEnvironment.objects.filter(name="brandnew").exists())
        self.assertFalse(ProtocolList.objects.filter(name="partial").exists())

    def test_import_and_save_reject_unavailable_environment(self):
        value = document("private")
        VirtualEnvironment.objects.create(name="private", user=self.other, value="secret")
        with self.assertRaises(services.ProtocolImportError):
            services.import_protocol_from_json(self.user, {"name": "blocked", **value})
        previous = self.protocol.template
        response = self.client.post(reverse("ui3:protocol_update", args=[self.protocol.id]), {
            "name": self.protocol.name, "template": json.dumps(value),
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 400)
        self.protocol.refresh_from_db()
        self.assertEqual(self.protocol.template, previous)

    def test_execution_option_types_are_validated(self):
        for field, value in (("env", 12), ("env", {}), ("gpu_step", "false"), ("force_local", 2)):
            payload = document()
            payload["blocks"]["align"]["steps"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ProtocolTemplateError):
                normalize_template(payload)

    def test_full_page_has_forms_and_environment_choices(self):
        VirtualEnvironment.objects.create(user=self.other, name="hidden-env", value="private")
        response = self.client.get(reverse("ui3:protocols"), {"select": self.protocol.id})
        self.assertContains(response, 'id="template-editor"')
        self.assertContains(response, "tpl-savebar")
        self.assertContains(response, "tpl-pipeline-actions")
        self.assertContains(response, "tpl-entry-meta")
        self.assertContains(response, "Remove block align")
        self.assertContains(response, "Run environment")
        self.assertContains(response, 'value="analysis" selected')
        self.assertContains(response, "Advanced JSON")
        self.assertContains(response, reverse("ui3:protocol_template_edit", args=[self.protocol.id]))
        self.assertNotContains(response, "hidden-env")

    def test_create_page_starts_with_starter_template(self):
        response = self.client.get(reverse("ui3:protocol_template_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New Protocol Template")
        self.assertContains(response, "Files per sample starts at 1")
        self.assertContains(response, "A sample map is optional")
        self.assertContains(response, "Commands.")
        self.assertContains(response, "Rename block")
        self.assertContains(response, "class=\"tpl-entry\" open")
        self.assertContains(response, 'id="template-editor"')
        self.assertContains(response, "process_sample")
        self.assertContains(response, "Create protocol")
        self.assertContains(response, reverse("ui3:protocol_template_create_edit"))
        self.assertContains(response, 'id="ui3-tokens"')

    def test_create_draft_does_not_persist_and_create_saves_template(self):
        blank = services.blank_template_document()
        response = self.client.post(reverse("ui3:protocol_template_create_edit"), {
            "template": json.dumps(blank), "template_mode": "visual", "editor_action": "add_step",
            "editor_path": json.dumps(["blocks", "process_sample", "steps"]),
            'tf:["blocks","process_sample","steps",0,"parameter"]': "kept draft",
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        draft = json.loads(response.context["editor"]["source"])
        self.assertEqual(draft["blocks"]["process_sample"]["steps"][0]["parameter"], "kept draft")
        self.assertEqual(len(draft["blocks"]["process_sample"]["steps"]), 2)
        self.assertFalse(ProtocolList.objects.filter(name="From GUI").exists())

        response = self.client.post(reverse("ui3:protocol_template_create"), {
            "name": "From GUI",
            "description": "built in forms",
            "template": response.context["editor"]["source"],
            "template_mode": "visual",
            'tf:["blocks","process_sample","steps",0,"software"]': "fastp",
            'tf:["blocks","process_sample","steps",0,"parameter"]': "-i {{sample.r1}}",
            'tf:["blocks","process_sample","steps",1,"software"]': "echo",
            'tf:["blocks","process_sample","steps",1,"parameter"]': "done",
        })
        self.assertEqual(response.status_code, 302)
        proto = ProtocolList.objects.get(name="From GUI")
        self.assertIn("select={}".format(proto.id), response["Location"])
        saved = json.loads(proto.template)
        self.assertEqual(saved["blocks"]["process_sample"]["steps"][0]["software"], "fastp")
        self.assertEqual(saved["pipeline"][0]["map"], "samples")
        self.assertTrue(proto.ver)

    def test_create_requires_name_and_rejects_invalid_template(self):
        blank = services.blank_template_document()
        response = self.client.post(reverse("ui3:protocol_template_create"), {
            "name": "", "template": json.dumps(blank), "template_mode": "json",
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Name is required.", status_code=400)
        response = self.client.post(reverse("ui3:protocol_template_create"), {
            "name": "Broken",
            "template": json.dumps({"pipeline": [{"software": "", "parameter": ""}]}),
            "template_mode": "json",
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "missing software", status_code=400)
        self.assertFalse(ProtocolList.objects.filter(name="Broken").exists())

    def test_invalid_json_is_kept_on_the_create_form(self):
        raw = "{ not json"
        response = self.client.post(reverse("ui3:protocol_template_create"), {
            "name": "Broken", "template": raw, "template_mode": "json",
        })
        self.assertContains(response, "Template is not valid JSON.", status_code=400)
        self.assertContains(response, raw, status_code=400)
        raw = '{"samples": {}}'
        response = self.client.post(reverse("ui3:protocol_template_create"), {
            "name": "Broken", "template": raw, "template_mode": "json",
        })
        self.assertContains(response, "pipeline", status_code=400)
        self.assertContains(response, '{"samples": {}}', status_code=400, html=True)

    def test_rename_block_updates_calls(self):
        response = self.client.post(reverse("ui3:protocol_template_edit", args=[self.protocol.id]), {
            "template": self.protocol.template, "template_mode": "visual",
            "editor_action": "rename_block", "editor_path": json.dumps(["blocks", "align"]),
            "br:align": "mapped",
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        source = json.loads(response.context["editor"]["source"])
        self.assertIn("mapped", source["blocks"])
        self.assertNotIn("align", source["blocks"])
        self.assertEqual(source["pipeline"][0]["steps"][0]["call"], "mapped")
        self.protocol.refresh_from_db()
        self.assertIn("align", json.loads(self.protocol.template)["blocks"])

    def test_draft_changes_preserve_unsaved_values_without_saving(self):
        original = self.protocol.template
        response = self.draft("add_step", ["blocks", "align", "steps"], **{
            'tf:["blocks","align","steps",0,"parameter"]': "unsaved value",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        value = json.loads(response.context["editor"]["source"])
        self.assertEqual(len(value["blocks"]["align"]["steps"]), 2)
        self.assertEqual(value["blocks"]["align"]["steps"][0]["parameter"], "unsaved value")
        self.protocol.refresh_from_db()
        self.assertEqual(self.protocol.template, original)

    def test_form_json_switch_and_save_preserve_unknown_fields(self):
        payload = document()
        payload["blocks"]["align"]["steps"][0]["custom_metadata"] = "keep"
        response = self.draft("show_json", template=json.dumps(payload), **{
            'tf:["blocks","align","steps",0,"parameter"]': "edited",
        })
        self.assertEqual(response.context["editor"]["mode"], "json")
        source = response.context["editor"]["source"]
        response = self.draft("show_forms", template=source, template_mode="json")
        self.assertEqual(response.context["editor"]["mode"], "visual")
        response = self.client.post(reverse("ui3:protocol_update", args=[self.protocol.id]), {
            "name": self.protocol.name, "template": response.context["editor"]["source"], "template_mode": "visual",
            'tb:["blocks","align","steps",0,"gpu_step"]': "0",
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.protocol.refresh_from_db()
        step = json.loads(self.protocol.template)["blocks"]["align"]["steps"][0]
        self.assertEqual(step["parameter"], "edited")
        self.assertEqual(step["custom_metadata"], "keep")
        self.assertFalse(step["gpu_step"])

    def test_draft_add_remove_reorder_and_permissions(self):
        response = self.draft("add_block", editor_block_name="new")
        self.assertEqual(response.status_code, 200)
        response = self.draft("remove", ["blocks", "align"])
        self.assertEqual(response.status_code, 400)  # still referenced
        payload = document()
        payload["pipeline"].append({"software": "echo", "parameter": "tail"})
        response = self.draft("up", ["pipeline", 1], template=json.dumps(payload))
        self.assertEqual(json.loads(response.context["editor"]["source"])["pipeline"][0]["parameter"], "tail")
        response = self.draft("remove", ["pipeline", 1], template=response.context["editor"]["source"])
        self.assertEqual(len(json.loads(response.context["editor"]["source"])["pipeline"]), 1)
        self.login("bob")
        self.assertEqual(self.draft("show_json").status_code, 403)

    def test_invalid_json_draft_returns_error_without_replacing_editor(self):
        response = self.draft("show_forms", template="{", template_mode="json")
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, 'id="template-editor"', status_code=400)

    def test_editor_shows_pipeline_before_blocks_and_a_live_preview(self):
        response = self.client.get(reverse("ui3:protocols"), {"select": self.protocol.id})
        body = response.content.decode()
        self.assertLess(body.index(">Pipeline<"), body.index(">Reusable blocks<"))
        self.assertIn("Expanded preview", body)
        self.assertContains(response, "2 steps for 2 samples")
        response = self.draft("show_forms", **{
            'tf:["blocks","align","steps",0,"parameter"]': "preview this command",
        })
        self.assertContains(response, "preview this command")
        self.assertContains(response, "2 steps for 2 samples")

    def test_name_value_rows_replace_json_objects_on_save(self):
        response = self.client.post(reverse("ui3:protocol_update", args=[self.protocol.id]), {
            "name": self.protocol.name,
            "template": self.protocol.template,
            "template_mode": "visual",
            'tpset:["blocks","align","steps",0,"outputs"]': "1",
            'tp:["blocks","align","steps",0,"outputs"]:0:k': "clean",
            'tp:["blocks","align","steps",0,"outputs"]:0:v': "{{sample.prefix}}.bam",
            'tpset:["samples","fields"]': "1",
            'tp:["samples","fields"]:0:k': "umi_len",
            'tp:["samples","fields"]:0:v': "{{UMI_LEN||6}}",
        }, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.protocol.refresh_from_db()
        saved = json.loads(self.protocol.template)
        self.assertEqual(saved["blocks"]["align"]["steps"][0]["outputs"]["clean"], "{{sample.prefix}}.bam")
        self.assertEqual(saved["samples"]["fields"]["umi_len"], "{{UMI_LEN||6}}")
        self.assertNotIn("bam", saved["blocks"]["align"]["steps"][0]["outputs"])

    def test_save_rejects_a_misspelled_sample_field(self):
        payload = document()
        payload["blocks"]["align"]["steps"][0]["outputs"] = {"clean": "out.fq"}
        payload["blocks"]["align"]["steps"][0]["parameter"] = "{{sample.clen}}"
        response = self.client.post(reverse("ui3:protocol_update", args=[self.protocol.id]), {
            "name": self.protocol.name, "template": json.dumps(payload),
        }, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Did you mean", status_code=400)
        self.assertContains(response, "clen", status_code=400)
        self.assertContains(response, "clean", status_code=400)
        self.protocol.refresh_from_db()
        self.assertIn("{{sample.r1}}", self.protocol.template)

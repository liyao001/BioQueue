import json
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from QueueDB.models import ApiIdempotency, Job, Profile, Slave
from ui.agent_api import _request_hash

from . import Ui3TestCase


class AgentApiTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self.token = Profile.objects.get(user=self.user).api_key
        self.other_token = Profile.objects.get(user=self.other).api_key

    def auth(self, token=None):
        return {"HTTP_AUTHORIZATION": "Bearer {}".format(token or self.token)}

    def test_missing_token_is_rejected(self):
        response = self.client.get(reverse("agent_api:index"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("Bearer", response.json()["error"])

    def test_session_cookie_is_not_enough(self):
        self.login()
        response = self.client.get(reverse("agent_api:jobs"))
        self.assertEqual(response.status_code, 401)

    def test_inactive_account_token_is_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.get(reverse("agent_api:index"), **self.auth())
        self.assertEqual(response.status_code, 401)

    def test_discovery_lists_endpoints(self):
        response = self.client.get(reverse("agent_api:index"), **self.auth())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["version"], 1)
        self.assertTrue(any(item["path"] == "/api/v1/jobs/" for item in body["endpoints"]))

    def test_create_job_by_protocol_name_and_hide_other_accounts(self):
        self.make_job(user=self.other, job_name="bobs-job")
        created = self.client.post(
            reverse("agent_api:jobs"),
            data=json.dumps(
                {
                    "job_name": "liver_rep1",
                    "protocol": "RNA-seq",
                    "parameter": "threads=4",
                    "input_file": "sample.fq",
                    "workspace": self.workspace.name,
                    "comments": "from an agent",
                }
            ),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(created.status_code, 201, created.content)
        job = created.json()["job"]
        self.assertEqual(job["job_name"], "liver_rep1")
        self.assertEqual(job["status_label"], "Waiting")
        self.assertEqual(job["workspace"], self.workspace.id)
        self.assertEqual(job["protocol"], self.protocol.id)

        listed = self.client.get(reverse("agent_api:jobs"), **self.auth())
        names = [row["job_name"] for row in listed.json()["jobs"]]
        self.assertIn("liver_rep1", names)
        self.assertNotIn("bobs-job", names)

        foreign = self.client.get(reverse("agent_api:job_detail", args=[job["id"]]), **self.auth(self.other_token))
        self.assertEqual(foreign.status_code, 404)

    def test_unknown_field_and_foreign_protocol_are_rejected(self):
        unknown = self.client.post(
            reverse("agent_api:jobs"),
            data=json.dumps({"job_name": "x", "protocol": self.protocol.id, "protcol": 1}),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("protcol", unknown.json()["error"])

        denied = self.client.post(
            reverse("agent_api:jobs"),
            data=json.dumps({"job_name": "x", "protocol": self.other_protocol.id}),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(Job.objects.filter(job_name="x").count(), 0)

    def test_idempotency_key_replays_the_same_job(self):
        body = json.dumps({"job_name": "once", "protocol": self.protocol.id, "input_file": "a.fq"})
        headers = self.auth()
        headers["HTTP_IDEMPOTENCY_KEY"] = "create-once"
        first = self.client.post(
            reverse("agent_api:jobs"),
            data=body,
            content_type="application/json",
            **headers,
        )
        second = self.client.post(
            reverse("agent_api:jobs"),
            data=body,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second["Idempotency-Replayed"], "true")
        self.assertEqual(first.json()["job"]["id"], second.json()["job"]["id"])
        self.assertEqual(Job.objects.filter(job_name="once").count(), 1)

        changed = self.client.post(
            reverse("agent_api:jobs"),
            data=json.dumps({"job_name": "twice", "protocol": self.protocol.id}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(Job.objects.filter(job_name="twice").count(), 0)

    def test_batch_tsv(self):
        tsv = "{pid}\tone\ta.fq\tthreads=1\n{pid}\ttwo\tb.fq\tthreads=2\n".format(pid=self.protocol.id)
        response = self.client.post(
            reverse("agent_api:jobs_batch"),
            data=json.dumps({"tsv": tsv, "workspace": self.workspace.id}),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["errors"], [])
        self.assertEqual({job.workspace_id for job in Job.objects.filter(job_name__in=["one", "two"])}, {self.workspace.id})

        failed = self.client.post(
            reverse("agent_api:jobs_batch"),
            data=json.dumps({"tsv": "not-a-job"}),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(failed.json()["error"], "No jobs were created.")
        self.assertEqual(failed.json()["errors"][0]["line"], 1)

        mixed = "{pid}\tok\ta.fq\tthreads=1\nbad\n".format(pid=self.protocol.id)
        partial = self.client.post(
            reverse("agent_api:jobs_batch"),
            data=json.dumps({"tsv": mixed}),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(partial.status_code, 207, partial.content)
        self.assertEqual(partial.json()["created"], 1)
        self.assertEqual(partial.json()["error"], "Some rows were skipped.")
        self.assertEqual(len(partial.json()["errors"]), 1)

    def test_logs_files_and_dag(self):
        upstream = self.make_job(job_name="align")
        downstream = self.make_job(
            job_name="count",
            input_file="{{{{History:{}-out.bam}}}}".format(upstream.id),
        )
        logs = self.client.get(
            reverse("agent_api:job_logs", args=[upstream.id]),
            {"kind": "stdout"},
            **self.auth(),
        )
        self.assertEqual(logs.status_code, 200)
        self.assertEqual(logs.json()["kind"], "stdout")

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, str(self.user.id), "results")
            os.makedirs(folder)
            with open(os.path.join(folder, "counts.txt"), "w", encoding="utf-8") as handle:
                handle.write("gene\t1\n")
            outside = os.path.join(tmp, "secret.txt")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("nope")
            upstream.run_dir = tmp
            upstream.result = "results"
            upstream.save(update_fields=["run_dir", "result"])

            listed = self.client.get(reverse("agent_api:job_files", args=[upstream.id]), **self.auth())
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["name"] for item in listed.json()["items"]], ["counts.txt"])

            downloaded = self.client.get(
                reverse("agent_api:job_file_download", args=[upstream.id]),
                {"name": "counts.txt"},
                **self.auth(),
            )
            self.assertEqual(downloaded.status_code, 200)
            self.assertIn(b"gene", b"".join(downloaded.streaming_content))

            escaped = self.client.get(
                reverse("agent_api:job_file_download", args=[upstream.id]),
                {"name": "../secret.txt"},
                **self.auth(),
            )
            self.assertEqual(escaped.status_code, 404)

        graph = self.client.get(
            reverse("agent_api:job_dag", args=[downstream.id]),
            {"up": 1, "down": 0},
            **self.auth(),
        )
        self.assertEqual(graph.status_code, 200)
        node_ids = {node["id"] for node in graph.json()["nodes"]}
        self.assertIn(upstream.id, node_ids)
        self.assertIn(downstream.id, node_ids)

    def test_import_protocol_and_list_it(self):
        response = self.client.post(
            reverse("agent_api:protocol_import"),
            data=json.dumps(
                {
                    "name": "agent-echo",
                    "description": "created by an agent",
                    "step": [{"software": "echo", "parameter": "hello"}],
                }
            ),
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(response.status_code, 201, response.content)
        protocol_id = response.json()["protocol"]["id"]
        detail = self.client.get(reverse("agent_api:protocol_detail", args=[protocol_id]), **self.auth())
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["name"], "agent-echo")
        self.assertEqual(detail.json()["step"][0]["software"], "echo")

        hidden = self.client.get(reverse("agent_api:protocol_detail", args=[protocol_id]), **self.auth(self.other_token))
        self.assertEqual(hidden.status_code, 404)
        listed = self.client.get(reverse("agent_api:protocols"), **self.auth()).json()
        names = [row["name"] for row in listed["protocols"]]
        self.assertIn("agent-echo", names)
        self.assertNotIn("secret-proto", names)
        self.assertFalse(listed["has_more"])
        self.assertGreaterEqual(listed["total"], 2)

    def test_workspaces_and_runners_omit_ssh_secrets(self):
        Slave.objects.create(name="lab-node", comment="local")
        workspaces = self.client.get(reverse("agent_api:workspaces"), **self.auth()).json()["workspaces"]
        self.assertIn({"id": self.workspace.id, "name": "ws1"}, workspaces)
        runners = self.client.get(reverse("agent_api:runners"), **self.auth()).json()["runners"]
        self.assertEqual(runners, [{"id": Slave.objects.get(name="lab-node").id, "name": "lab-node"}])
        self.assertNotIn("ssh", json.dumps(runners))

    def test_account_page_shows_token_and_rotation_revokes_it(self):
        self.login()
        page = self.client.get(reverse("ui3:account"))
        self.assertContains(page, self.token)
        self.assertContains(page, "Rotate agent token")
        rotated = self.client.post(reverse("ui3:account"), {"section": "agent_token"})
        self.assertEqual(rotated.status_code, 302)
        fresh = Profile.objects.get(user=self.user).api_key
        self.assertNotEqual(fresh, self.token)
        self.assertEqual(len(fresh), 36)
        old = self.client.get(reverse("agent_api:index"), **self.auth(self.token))
        self.assertEqual(old.status_code, 401)
        new = self.client.get(reverse("agent_api:index"), **self.auth(fresh))
        self.assertEqual(new.status_code, 200)

    def _plant_claim(self, key, body, stale):
        path = reverse("agent_api:jobs")
        request = RequestFactory().post(path, data=body, content_type="application/json")
        row = ApiIdempotency.objects.create(
            user=self.user,
            key=key,
            request_hash=_request_hash(request),
            status_code=0,
            response_body="held",
        )
        if stale:
            ApiIdempotency.objects.filter(pk=row.pk).update(created=timezone.now() - timedelta(minutes=5))
        return path

    def test_live_idempotency_claim_is_not_run_twice(self):
        body = json.dumps({"job_name": "busy", "protocol": self.protocol.id})
        path = self._plant_claim("busy-key", body, stale=False)
        response = self.client.post(path, data=body, content_type="application/json", HTTP_IDEMPOTENCY_KEY="busy-key", **self.auth())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Job.objects.filter(job_name="busy").count(), 0)

    def test_abandoned_idempotency_claim_can_be_retried(self):
        body = json.dumps({"job_name": "retry", "protocol": self.protocol.id})
        path = self._plant_claim("retry-key", body, stale=True)
        response = self.client.post(path, data=body, content_type="application/json", HTTP_IDEMPOTENCY_KEY="retry-key", **self.auth())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Job.objects.filter(job_name="retry").count(), 1)
        self.assertNotIn("Idempotency-Replayed", response)

    def test_result_outside_the_user_directory_is_not_listed_or_downloaded(self):
        job = self.make_job(job_name="escape")
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(tmp, "outside")
            os.makedirs(outside)
            with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as handle:
                handle.write("nope")
            job.run_dir = tmp
            job.result = outside
            job.save(update_fields=["run_dir", "result"])
            listed = self.client.get(reverse("agent_api:job_files", args=[job.id]), **self.auth())
            self.assertEqual(listed.json()["items"], [])
            downloaded = self.client.get(
                reverse("agent_api:job_file_download", args=[job.id]),
                {"name": "secret.txt"},
                **self.auth(),
            )
            self.assertEqual(downloaded.status_code, 404)

            nested = os.path.join(tmp, str(self.user.id), "results")
            os.makedirs(nested)
            with open(os.path.join(nested, "ok.txt"), "w", encoding="utf-8") as handle:
                handle.write("yes")
            job.result = "../outside"
            job.save(update_fields=["result"])
            escaped = self.client.get(
                reverse("agent_api:job_file_download", args=[job.id]),
                {"name": "secret.txt"},
                **self.auth(),
            )
            self.assertEqual(escaped.status_code, 404)

    def test_log_keeps_chronological_order_and_marks_the_tail(self):
        job = self.make_job(job_name="logged")
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "{}.log".format(job.id)), "w", encoding="utf-8") as handle:
                handle.write("first\nsecond\nthird\n")
            with patch("worker.bases.get_config", return_value=tmp):
                full = self.client.get(reverse("agent_api:job_logs", args=[job.id]), **self.auth())
            self.assertEqual(full.status_code, 200)
            self.assertEqual(full.json()["text"], "first\nsecond\nthird\n")
            self.assertFalse(full.json()["truncated"])

            with patch("worker.bases.get_config", return_value=tmp), patch("ui.agent_api.MAX_LOG_CHARS", 8):
                tail = self.client.get(reverse("agent_api:job_logs", args=[job.id]), **self.auth())
            self.assertTrue(tail.json()["truncated"])
            self.assertEqual(tail.json()["text"], "third\n")

    def test_token_is_the_signed_in_user_when_delegate_differs(self):
        from django.contrib.auth.models import User

        lab = User.objects.create_user("lab", password="secret")
        lab_key = Profile.objects.get(user=lab).api_key
        profile = Profile.objects.get(user=self.user)
        profile.delegate = lab
        profile.save(update_fields=["delegate"])
        self.protocol.user = lab
        self.protocol.save(update_fields=["user"])
        self.login()
        page = self.client.get(reverse("ui3:account"))
        self.assertContains(page, profile.api_key)
        self.assertNotContains(page, lab_key)
        created = self.client.post(
            reverse("agent_api:jobs"),
            data=json.dumps({"job_name": "for-lab", "protocol": self.protocol.id}),
            content_type="application/json",
            **self.auth(profile.api_key),
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(Job.objects.get(job_name="for-lab").user_id, lab.id)
        self.client.post(reverse("ui3:account"), {"section": "agent_token"})
        self.assertEqual(Profile.objects.get(user=lab).api_key, lab_key)
        self.assertNotEqual(Profile.objects.get(user=self.user).api_key, profile.api_key)


class AgentTokenShapeTests(Ui3TestCase):
    def test_new_profile_key_is_a_uuid(self):
        from uuid import UUID

        key = Profile.objects.get(user=self.user).api_key
        self.assertEqual(str(UUID(key)), key)

import os
import tempfile

from django.urls import reverse

from QueueDB.models import Audition, FileArchive, Job, JobStatus, Workspace
from ui3.tests import Ui3TestCase


class JobMigrateTests(Ui3TestCase):
    def _staff(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.login()

    def _exec(self, **fields):
        payload = {"source": "alice", "dest": "bob", "dry_run": "0", "move_files": "1", "confirm": "1"}
        payload.update(fields)
        return self.client.post(reverse("ui3:job_migrate"), payload)

    def test_non_staff_forbidden(self):
        self.login()
        response = self.client.get(reverse("ui3:job_migrate"))
        self.assertEqual(response.status_code, 403)
        post = self.client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": "bob", "dry_run": "0", "confirm": "1"},
        )
        self.assertEqual(post.status_code, 403)
        self.assertNotContains(self.client.get(reverse("ui3:jobs")), reverse("ui3:job_migrate"), status_code=200)
        page = self.client.get(reverse("ui3:account"))
        self.assertNotContains(page, reverse("ui3:job_migrate"))

    def test_staff_can_open_form(self):
        self._staff()
        response = self.client.get(reverse("ui3:job_migrate"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "From account")
        self.assertContains(response, "Preview")
        nav = self.client.get(reverse("ui3:jobs"))
        self.assertContains(nav, reverse("ui3:job_migrate"))
        self.assertContains(nav, reverse("ui3:archives"))
        self.assertContains(nav, "Migrate jobs")
        self.assertContains(response, "migrate-job-search")
        self.assertContains(response, reverse("ui3:job_migrate_search"))
        account = self.client.get(reverse("ui3:account"))
        self.assertContains(account, reverse("ui3:job_migrate"))

    def test_preview_does_not_change_owner(self):
        job = self.make_job(job_name="stay")
        self._staff()
        response = self.client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": "bob", "dry_run": "1", "move_files": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview")
        self.assertContains(response, "stay")
        job.refresh_from_db()
        self.assertEqual(job.user, self.user)

    def test_migrate_moves_owner_files_and_archives(self):
        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="pack", result="out", run_dir=tmp)
        child = self.make_job(job_name="child", result="", run_dir=tmp, parent_job=job)
        running = self.make_job(job_name="live", status=JobStatus.RUNNING, result="live-out", run_dir=tmp)
        ws = Workspace.objects.create(name="alice-ws", user=self.user)
        job.workspace = ws
        job.save(update_fields=["workspace"])
        src = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(src)
        with open(os.path.join(src, "hits.txt"), "w") as fh:
            fh.write("ok")
        FileArchive.objects.create(
            user=self.user,
            protocol=self.protocol,
            protocol_ver="test",
            inputs="",
            files="[]",
            file_md5s="ph",
            job=job,
            description="keep",
            status=0,
        )
        Audition.objects.create(
            operation="Created",
            related_job=job,
            job_name="pack",
            prev_par="",
            new_par="",
            prev_input="",
            current_input="",
            protocol="RNA-seq",
            protocol_ver="test",
            user=self.user,
        )
        self._staff()
        response = self._exec(ids=str(job.id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "moved")
        job.refresh_from_db()
        child.refresh_from_db()
        running.refresh_from_db()
        self.assertEqual(job.user, self.other)
        self.assertIsNone(job.workspace)
        self.assertEqual(child.user, self.other)
        self.assertEqual(running.user, self.user)
        dest = os.path.join(tmp, str(self.other.id), "out")
        self.assertTrue(os.path.isfile(os.path.join(dest, "hits.txt")))
        self.assertFalse(os.path.exists(src))
        self.assertEqual(FileArchive.objects.get(job=job).user, self.other)
        self.assertTrue(Audition.objects.filter(related_job=job, operation="Migrated", user=self.other).exists())
        self.assertEqual(Audition.objects.filter(related_job=job).exclude(operation="Migrated").first().user, self.user)

    def test_collision_and_unknown_account(self):
        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="clash", result="out", run_dir=tmp)
        os.makedirs(os.path.join(tmp, str(self.user.id), "out"))
        os.makedirs(os.path.join(tmp, str(self.other.id), "out"))
        self._staff()
        collision = self._exec(ids=str(job.id))
        self.assertContains(collision, "Destination folder already exists", status_code=200)
        job.refresh_from_db()
        self.assertEqual(job.user, self.user)
        missing = self.client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": "nobody", "dry_run": "1"},
        )
        self.assertEqual(missing.status_code, 400)
        same = self.client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": str(self.user.id), "dry_run": "1"},
        )
        self.assertEqual(same.status_code, 400)
        self.assertContains(same, "different accounts", status_code=400)

    def test_garbage_ids_are_rejected(self):
        self.make_job(job_name="keep")
        self._staff()
        response = self.client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": "bob", "dry_run": "1", "ids": "not-a-job"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Job IDs must be integers", status_code=400)
        leftover = self._exec(ids="abc, 12x")
        self.assertEqual(leftover.status_code, 400)
        self.assertEqual(Job.objects.filter(user=self.user).count(), 1)

    def test_job_search_picker(self):
        import json

        mine = self.make_job(job_name="pack-alpha")
        self.make_job(user=self.other, job_name="pack-alpha")
        self._staff()
        by_name = self.client.get(
            reverse("ui3:job_migrate_search"),
            {"q": "pack-alpha", "source": "alice"},
        )
        self.assertEqual(by_name.status_code, 200)
        rows = json.loads(by_name.content)["results"]
        self.assertEqual([row["id"] for row in rows], [mine.id])
        self.assertEqual(rows[0]["username"], "alice")
        by_id = self.client.get(
            reverse("ui3:job_migrate_search"),
            {"q": str(mine.id), "source": "alice"},
        )
        self.assertEqual([row["id"] for row in json.loads(by_id.content)["results"]], [mine.id])
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        forbidden = self.client.get(reverse("ui3:job_migrate_search"), {"q": "pack"})
        self.assertEqual(forbidden.status_code, 403)

    def test_missing_folder_and_blank_run_dir_skip_owner(self):
        tmp = tempfile.mkdtemp()
        missing = self.make_job(job_name="gone", result="out", run_dir=tmp)
        blank = self.make_job(job_name="cwd", result="out", run_dir="")
        relative = self.make_job(job_name="rel", result="out", run_dir="workspace")
        none = self.make_job(job_name="none", result="", run_dir=tmp)
        self._staff()
        response = self._exec(ids="{}, {}, {}, {}".format(missing.id, blank.id, relative.id, none.id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Source folder missing")
        self.assertContains(response, "Result path is not safe to move")
        missing.refresh_from_db()
        blank.refresh_from_db()
        relative.refresh_from_db()
        none.refresh_from_db()
        self.assertEqual(missing.user, self.user)
        self.assertEqual(blank.user, self.user)
        self.assertEqual(relative.user, self.user)
        self.assertEqual(none.user, self.other)

    def test_nested_array_folder_moves_with_parent(self):
        tmp = tempfile.mkdtemp()
        parent = self.make_job(job_name="array", result="out", run_dir=tmp)
        child = self.make_job(
            job_name="shard",
            result="out/0",
            run_dir=tmp,
            parent_job=parent,
            array_setting="0",
        )
        src = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(os.path.join(src, "0"))
        with open(os.path.join(src, "hits.txt"), "w") as fh:
            fh.write("ok")
        with open(os.path.join(src, "0", "shard.txt"), "w") as fh:
            fh.write("child")
        self._staff()
        response = self._exec(ids=str(parent.id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "covered by job #{}".format(parent.id))
        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.user, self.other)
        self.assertEqual(child.user, self.other)
        dest = os.path.join(tmp, str(self.other.id), "out")
        self.assertTrue(os.path.isfile(os.path.join(dest, "hits.txt")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "0", "shard.txt")))
        self.assertFalse(os.path.exists(src))

    def test_nested_child_skips_when_parent_does_not_move(self):
        tmp = tempfile.mkdtemp()
        running = self.make_job(job_name="live-array", status=JobStatus.RUNNING, result="out", run_dir=tmp)
        nested = self.make_job(job_name="live-shard", result="out/0", run_dir=tmp, parent_job=running, array_setting="0")
        parent = self.make_job(job_name="stay-array", result="keep", run_dir=tmp)
        orphan = self.make_job(job_name="orphan-shard", result="keep/1", run_dir=tmp, parent_job=parent, array_setting="1")
        os.makedirs(os.path.join(tmp, str(self.user.id), "out", "0"))
        os.makedirs(os.path.join(tmp, str(self.user.id), "keep", "1"))
        self._staff()
        running_resp = self._exec(ids=str(running.id))
        self.assertContains(running_resp, "Job is running")
        self.assertContains(running_resp, "which is not moving")
        running.refresh_from_db()
        nested.refresh_from_db()
        self.assertEqual(running.user, self.user)
        self.assertEqual(nested.user, self.user)
        self.assertTrue(os.path.isdir(os.path.join(tmp, str(self.user.id), "out", "0")))
        child_only = self._exec(ids=str(orphan.id))
        self.assertContains(child_only, "which is not in this migrate")
        parent.refresh_from_db()
        orphan.refresh_from_db()
        self.assertEqual(parent.user, self.user)
        self.assertEqual(orphan.user, self.user)
        self.assertTrue(os.path.isdir(os.path.join(tmp, str(self.user.id), "keep", "1")))
        self.assertFalse(os.path.exists(os.path.join(tmp, str(self.other.id), "keep", "1")))

    def test_execute_requires_confirm(self):
        job = self.make_job(job_name="hold")
        self._staff()
        response = self.client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": "bob", "dry_run": "0", "move_files": "1", "ids": str(job.id)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Confirm the migrate", status_code=400)
        job.refresh_from_db()
        self.assertEqual(job.user, self.user)

    def test_csrf_rejected_without_token(self):
        from django.test import Client

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        client = Client(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="alice", password="secret"))
        response = client.post(
            reverse("ui3:job_migrate"),
            {"source": "alice", "dest": "bob", "dry_run": "0", "confirm": "1"},
        )
        self.assertEqual(response.status_code, 403)

    def test_locked_and_resourcelock_are_skipped(self):
        tmp = tempfile.mkdtemp()
        locked = self.make_job(job_name="frozen", result="lock-out", run_dir=tmp, locked=1)
        busy = self.make_job(job_name="queued-res", result="res-out", run_dir=tmp, status=JobStatus.RESOURCELOCK)
        os.makedirs(os.path.join(tmp, str(self.user.id), "lock-out"))
        os.makedirs(os.path.join(tmp, str(self.user.id), "res-out"))
        self._staff()
        response = self._exec(ids="{}, {}".format(locked.id, busy.id))
        self.assertContains(response, "Job is locked")
        self.assertContains(response, "waiting for resources")
        locked.refresh_from_db()
        busy.refresh_from_db()
        self.assertEqual(locked.user, self.user)
        self.assertEqual(busy.user, self.user)
        self.assertTrue(os.path.isdir(os.path.join(tmp, str(self.user.id), "lock-out")))

    def test_history_peers_must_move_together(self):
        tmp = tempfile.mkdtemp()
        upstream = self.make_job(job_name="hist-up", result="up", run_dir=tmp)
        downstream = self.make_job(
            job_name="hist-down",
            result="down",
            run_dir=tmp,
            parameter="{{{{History:{}-hits.txt}}}}".format(upstream.id),
        )
        os.makedirs(os.path.join(tmp, str(self.user.id), "up"))
        os.makedirs(os.path.join(tmp, str(self.user.id), "down"))
        self._staff()
        partial = self._exec(ids=str(downstream.id))
        self.assertContains(partial, "History links job #{}".format(upstream.id))
        downstream.refresh_from_db()
        upstream.refresh_from_db()
        self.assertEqual(downstream.user, self.user)
        self.assertEqual(upstream.user, self.user)
        together = self._exec(ids="{}, {}".format(upstream.id, downstream.id))
        self.assertEqual(together.status_code, 200)
        upstream.refresh_from_db()
        downstream.refresh_from_db()
        self.assertEqual(upstream.user, self.other)
        self.assertEqual(downstream.user, self.other)

    def test_source_grandchild_behind_foreign_parent(self):
        tmp = tempfile.mkdtemp()
        root = self.make_job(job_name="root", result="root-out", run_dir=tmp)
        mid = self.make_job(job_name="mid", user=self.other, parent_job=root, result="mid-out", run_dir=tmp)
        leaf = self.make_job(job_name="leaf", parent_job=mid, result="leaf-out", run_dir=tmp)
        os.makedirs(os.path.join(tmp, str(self.user.id), "root-out"))
        os.makedirs(os.path.join(tmp, str(self.user.id), "leaf-out"))
        os.makedirs(os.path.join(tmp, str(self.other.id), "mid-out"))
        self._staff()
        response = self._exec(ids=str(root.id))
        self.assertEqual(response.status_code, 200)
        root.refresh_from_db()
        mid.refresh_from_db()
        leaf.refresh_from_db()
        self.assertEqual(root.user, self.other)
        self.assertEqual(mid.user, self.other)
        self.assertEqual(leaf.user, self.other)
        self.assertTrue(os.path.isdir(os.path.join(tmp, str(self.other.id), "root-out")))
        self.assertTrue(os.path.isdir(os.path.join(tmp, str(self.other.id), "leaf-out")))
        self.assertTrue(os.path.isdir(os.path.join(tmp, str(self.other.id), "mid-out")))

    def test_symlink_and_unsafe_result_are_skipped(self):
        tmp = tempfile.mkdtemp()
        user_root = os.path.join(tmp, str(self.user.id))
        uploads = os.path.join(user_root, "uploads")
        os.makedirs(uploads)
        with open(os.path.join(uploads, "secret.txt"), "w") as fh:
            fh.write("keep")
        os.symlink(uploads, os.path.join(user_root, "linked"))
        linked = self.make_job(job_name="link", result="linked", run_dir=tmp)
        traversal = self.make_job(job_name="trav", result="../uploads", run_dir=tmp)
        self._staff()
        response = self._exec(ids="{}, {}".format(linked.id, traversal.id))
        self.assertContains(response, "Result path is not safe to move")
        linked.refresh_from_db()
        traversal.refresh_from_db()
        self.assertEqual(linked.user, self.user)
        self.assertEqual(traversal.user, self.user)
        self.assertTrue(os.path.islink(os.path.join(user_root, "linked")))
        self.assertTrue(os.path.isfile(os.path.join(uploads, "secret.txt")))

    def test_numeric_username_and_inactive_dest(self):
        from django.contrib.auth.models import User

        numbered = User.objects.create_user("100", password="secret")
        job = self.make_job(job_name="named")
        self.other.is_active = False
        self.other.save(update_fields=["is_active"])
        self._staff()
        blocked = self._exec(ids=str(job.id))
        self.assertEqual(blocked.status_code, 400)
        self.assertContains(blocked, "inactive", status_code=400)
        job.refresh_from_db()
        self.assertEqual(job.user, self.user)
        numbered_dest = self._exec(dest="100", ids=str(job.id), move_files="0")
        self.assertEqual(numbered_dest.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.user, numbered)

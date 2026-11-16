import io
import json
import os
import shutil
import tarfile
import tempfile

from django.urls import reverse

from QueueDB.models import FileArchive
from ui.services import ARCHIVE_DONE, ARCHIVE_FAILED, ARCHIVE_QUEUED
from ui.tests import Ui3TestCase


class ArchiveTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self._archive_dir = tempfile.mkdtemp()
        profile = self.user.queuedb_profile_related
        profile.archive_folder = self._archive_dir
        profile.save(update_fields=["archive_folder"])

    def tearDown(self):
        shutil.rmtree(self._archive_dir, ignore_errors=True)
        super().tearDown()

    def _tar_names(self, path):
        with tarfile.open(path, "r:gz") as tar:
            return tar.getnames()

    def test_archives_requires_login(self):
        response = self.client.get(reverse("ui3:archives"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui/login/", response["Location"])

    def test_archives_list(self):
        job = self.make_job()
        FileArchive.objects.create(
            user=self.user,
            protocol=self.protocol,
            protocol_ver="test",
            inputs="sample.fq",
            files='["/tmp/a"]',
            file_md5s="ph",
            job=job,
            description="demo archive",
            status=0,
        )
        other_job = self.make_job(user=self.other, protocol=self.other_protocol)
        FileArchive.objects.create(
            user=self.other,
            protocol=self.other_protocol,
            protocol_ver="x",
            inputs="",
            files="[]",
            file_md5s="ph",
            job=other_job,
            description="bob-secret",
            status=0,
        )
        self.login()
        response = self.client.get(reverse("ui3:archives"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "demo archive")
        self.assertNotContains(response, "bob-secret")
        htmx = self.client.get(reverse("ui3:archives"), HTTP_HX_REQUEST="true")
        self.assertNotContains(htmx, "<html")
        self.assertContains(htmx, 'id="archive-table"')

    def test_queue_archive_from_traces(self):
        import os
        import tempfile

        from ui.files import encode_trace

        tmp = tempfile.mkdtemp()
        job = self.make_job(result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        with open(os.path.join(folder, "hello.txt"), "w") as fh:
            fh.write("abc")
        with open(os.path.join(folder, "other.txt"), "w") as fh:
            fh.write("leave this out")
        self.login()
        modal = self.client.get(reverse("ui3:job_archive", args=[job.id]))
        self.assertEqual(modal.status_code, 200)
        self.assertContains(modal, "Create archive")
        self.assertContains(modal, "built in the background")
        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"traces": encode_trace("out/hello.txt"), "description": "keep bam"},
        )
        self.assertEqual(response.status_code, 302)
        archive = FileArchive.objects.get(job=job)
        self.assertEqual(archive.description, "keep bam")
        self.assertEqual(archive.status, ARCHIVE_QUEUED)
        from ui.job_archive import process_queued_archives

        self.assertEqual(process_queued_archives(limit=5), 1)
        archive.refresh_from_db()
        self.assertEqual(archive.status, ARCHIVE_DONE)
        self.assertIn("hello.txt", archive.raw_files)
        self.assertNotEqual(archive.file_md5s, "ph")
        self.assertIn("results/hello.txt", self._tar_names(archive.archive_file))
        self.assertNotIn("results/other.txt", self._tar_names(archive.archive_file))
        self.assertTrue(
            os.path.realpath(archive.archive_file).startswith(os.path.realpath(self._archive_dir) + os.sep)
        )

    def test_history_token_cannot_escape_result_dir(self):
        import os
        import tempfile

        tmp = tempfile.mkdtemp()
        job = self.make_job(result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        uploads = os.path.join(tmp, str(self.user.id), "uploads")
        os.makedirs(uploads)
        with open(os.path.join(uploads, "secret.txt"), "w") as fh:
            fh.write("nope")
        self.login()
        token = "{{{{History:{}-../uploads/secret.txt}}}}".format(job.id)
        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"raw_files": token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FileArchive.objects.filter(job=job).exists())

    def test_archive_rejects_invalid_share_list(self):
        job = self.make_job()
        self.login()
        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"raw_files": "{{{{History:{}-a.txt}}}}".format(job.id), "shared_with": "not-an-email"},
        )
        self.assertEqual(response.status_code, 400)

    def test_archive_htmx_keeps_array_page(self):
        import os
        import tempfile

        from ui.files import encode_trace

        tmp = tempfile.mkdtemp()
        parent = self.make_job(job_name="arr-parent", is_executable=0)
        child = self.make_job(job_name="arr-child", parent_job=parent, result="out", run_dir=tmp)
        self.make_job(job_name="unrelated")
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        with open(os.path.join(folder, "hello.txt"), "w") as fh:
            fh.write("abc")
        self.login()
        array_url = "http://testserver" + reverse("ui3:job_array", args=[parent.id])
        response = self.client.post(
            reverse("ui3:job_archive", args=[child.id]),
            {"traces": encode_trace("out/hello.txt")},
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL=array_url,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "arr-child")
        self.assertNotContains(response, "unrelated")
        self.assertContains(response, reverse("ui3:job_array", args=[parent.id]))

    def test_cannot_archive_other_users_job(self):
        job = self.make_job(user=self.other, protocol=self.other_protocol)
        self.login()
        response = self.client.post(reverse("ui3:job_archive", args=[job.id]), {"raw_files": "x"})
        self.assertEqual(response.status_code, 403)

    def test_archive_rejects_long_protocol_ver(self):
        import os
        import tempfile

        from ui.files import encode_trace

        tmp = tempfile.mkdtemp()
        job = self.make_job(result="out", run_dir=tmp, protocol_ver="x" * 34)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        with open(os.path.join(folder, "hello.txt"), "w") as fh:
            fh.write("abc")
        self.login()
        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"traces": encode_trace("out/hello.txt")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FileArchive.objects.filter(job=job).exists())

    def test_archive_whole_job_and_download(self):
        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="liver rep 1", result="out", run_dir=tmp, parameter="threads=8")
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(os.path.join(folder, "nested"))
        with open(os.path.join(folder, "nested", "hello.txt"), "w") as fh:
            fh.write("abc")
        outside = os.path.join(tmp, "secret.txt")
        with open(outside, "w") as fh:
            fh.write("hidden")
        os.symlink(outside, os.path.join(folder, "secret.txt"))
        self.login()
        from ui.job_archive import process_queued_archives

        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"scope": "job", "description": "keep the run", "download": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("ui3:archives"), response["Location"])
        archive = FileArchive.objects.get(job=job)
        self.assertEqual(archive.status, ARCHIVE_QUEUED)
        self.assertEqual(archive.description, "keep the run")
        self.assertEqual(process_queued_archives(limit=5), 1)
        archive.refresh_from_db()
        self.assertEqual(archive.status, ARCHIVE_DONE)
        download = self.client.get(reverse("ui3:archive_download", args=[archive.id]))
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download["Content-Disposition"])
        payload = b"".join(download.streaming_content)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            names = tar.getnames()
            manifest = json.loads(tar.extractfile("bioqueue-job.json").read().decode("utf-8"))
            hello = tar.extractfile("results/nested/hello.txt").read()
        self.assertIn("results/nested/hello.txt", names)
        self.assertNotIn("results/secret.txt", names)
        self.assertEqual(hello, b"abc")
        self.assertEqual(manifest["job_name"], "liver rep 1")
        self.assertEqual(manifest["parameter"], "threads=8")
        htmx = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"scope": "job"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="modal-root",
        )
        self.assertEqual(htmx.status_code, 200)
        self.assertNotContains(htmx, "<html")
        self.assertContains(htmx, "is queued")
        self.assertNotContains(htmx, ">Download<")
        self.assertContains(htmx, reverse("ui3:archives"))
        listed = self.client.get(reverse("ui3:archives"))
        self.assertContains(listed, reverse("ui3:archive_download", args=[archive.id]))

    def test_archive_whole_job_requires_files(self):
        from ui.job_archive import process_queued_archives

        job = self.make_job()
        self.login()
        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"scope": "job"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(process_queued_archives(limit=5), 0)
        failed = FileArchive.objects.get(user=self.user)
        self.assertEqual(failed.status, ARCHIVE_FAILED)
        self.assertIn("No result files", failed.comment)
        self.assertIsNone(failed.job_id)

    def test_archive_download_is_private(self):
        job = self.make_job()
        archive = FileArchive.objects.create(
            user=self.user,
            protocol=self.protocol,
            protocol_ver="test",
            inputs="",
            files="[]",
            file_md5s="ph",
            job=job,
            description="mine",
            status=ARCHIVE_DONE,
            archive_file="/etc/passwd",
        )
        self.login()
        missing = self.client.get(reverse("ui3:archive_download", args=[archive.id]))
        self.assertEqual(missing.status_code, 404)
        link = os.path.join(self._archive_dir, "escape.tar.gz")
        os.symlink("/etc/passwd", link)
        archive.archive_file = link
        archive.save(update_fields=["archive_file"])
        linked = self.client.get(reverse("ui3:archive_download", args=[archive.id]))
        self.assertEqual(linked.status_code, 404)
        self.login("bob")
        forbidden = self.client.get(reverse("ui3:archive_download", args=[archive.id]))
        self.assertEqual(forbidden.status_code, 403)
        self.client.logout()
        login_wall = self.client.get(reverse("ui3:archive_download", args=[archive.id]))
        self.assertEqual(login_wall.status_code, 302)

    def test_worker_builds_queued_archive_and_drops_outside_paths(self):
        from ui.job_archive import process_queued_archives

        tmp = tempfile.mkdtemp()
        job = self.make_job(result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        with open(os.path.join(folder, "hello.txt"), "w") as fh:
            fh.write("abc")
        queued = FileArchive.objects.create(
            user=self.user,
            protocol=self.protocol,
            protocol_ver="test",
            inputs="",
            files=json.dumps({"scope": "result"}),
            file_md5s="ph",
            job=job,
            raw_files="result",
            status=ARCHIVE_QUEUED,
            archive_file="ph",
        )
        outside = FileArchive.objects.create(
            user=self.user,
            protocol=self.protocol,
            protocol_ver="test",
            inputs="",
            files=json.dumps(["/etc/passwd"]),
            file_md5s="ph",
            job=job,
            status=ARCHIVE_QUEUED,
            archive_file="ph",
        )
        built = process_queued_archives(limit=5)
        queued.refresh_from_db()
        outside.refresh_from_db()
        self.assertEqual(built, 1)
        self.assertEqual(queued.status, ARCHIVE_DONE)
        self.assertIn("results/hello.txt", self._tar_names(queued.archive_file))
        self.assertEqual(outside.status, ARCHIVE_FAILED)
        self.assertIsNone(outside.job_id)

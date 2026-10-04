from django.urls import reverse

from QueueDB.models import FileArchive
from ui.tests import Ui3TestCase


class ArchiveTests(Ui3TestCase):
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
        self.login()
        modal = self.client.get(reverse("ui3:job_archive", args=[job.id]))
        self.assertEqual(modal.status_code, 200)
        self.assertContains(modal, "Queue archive")
        response = self.client.post(
            reverse("ui3:job_archive", args=[job.id]),
            {"traces": encode_trace("out/hello.txt"), "description": "keep bam"},
        )
        self.assertEqual(response.status_code, 302)
        archive = FileArchive.objects.get(job=job)
        self.assertEqual(archive.description, "keep bam")
        self.assertEqual(archive.status, 0)
        self.assertIn("hello.txt", archive.raw_files)

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

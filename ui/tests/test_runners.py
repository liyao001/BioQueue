from django.urls import reverse

from QueueDB.models import Slave
from ui.tests import Ui3TestCase


class RunnerTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.runner = Slave.objects.create(
            name="g2",
            comment="gpu login",
            cluster_manager=1,
            ssh_connection="login.cluster.edu",
            ssh_user="ly349",
            ssh_key="/keys/id_ed25519",
            stage_in=1,
            result_root="/home/ly349/workdir",
        )

    def test_staff_list_and_nonstaff_forbidden(self):
        self.login()
        page = self.client.get(reverse("ui3:runners"))
        self.assertContains(page, "g2")
        self.assertContains(page, "Slurm, remote")
        self.assertContains(page, "login.cluster.edu")
        self.assertContains(page, 'id="runner-filters"')
        self.assertContains(page, 'hx-trigger="submit, input delay:400ms, change"')
        self.assertNotContains(page, "from:input")
        self.assertContains(page, 'hx-sync="#runner-filters:replace"')
        self.assertContains(page, "page-head")
        partial = self.client.get(reverse("ui3:runners"), HTTP_HX_REQUEST="true")
        self.assertContains(partial, 'id="runner-table"')
        self.assertNotContains(partial, "<html")

        self.login("bob")
        denied = self.client.get(reverse("ui3:runners"))
        self.assertEqual(denied.status_code, 403)

    def test_create_slurm_runner(self):
        self.login()
        response = self.client.post(
            reverse("ui3:runner_create"),
            {
                "name": "cpu-local",
                "comment": "",
                "cluster_manager": "0",
                "stage_in": "",
                "ssh_connection": "",
                "ssh_user": "",
                "ssh_key": "",
                "cluster_manager_path": "",
                "scripts_dir": "",
                "result_root": "",
                "log_root": "",
                "workdir": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cpu-local")
        self.assertNotContains(response, "<html")
        created = Slave.objects.get(name="cpu-local")
        self.assertEqual(created.cluster_manager, 0)
        self.assertIsNone(created.stage_in)
        self.assertEqual(created.scripts_dir, "")

    def test_create_direct_and_remote_managers(self):
        self.login()
        direct = self.client.post(
            reverse("ui3:runner_create"),
            {
                "name": "head-slurm",
                "comment": "",
                "cluster_manager": "1",
                "stage_in": "0",
                "ssh_connection": "",
                "ssh_user": "",
                "ssh_key": "",
                "cluster_manager_path": "/usr/local/slurm/current/bin/",
                "scripts_dir": "",
                "result_root": "",
                "log_root": "",
                "workdir": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(direct.status_code, 200)
        self.assertContains(direct, "Slurm, direct")
        head = Slave.objects.get(name="head-slurm")
        self.assertEqual(head.cluster_manager, 1)
        self.assertFalse(head.ssh_connection)

        lsf = self.client.post(
            reverse("ui3:runner_create"),
            {
                "name": "lsf-head",
                "comment": "",
                "cluster_manager": "2",
                "stage_in": "",
                "ssh_connection": "",
                "ssh_user": "",
                "ssh_key": "",
                "cluster_manager_path": "",
                "scripts_dir": "",
                "result_root": "",
                "log_root": "",
                "workdir": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(lsf.status_code, 200)
        self.assertContains(lsf, "LSF, direct")
        self.assertEqual(Slave.objects.get(name="lsf-head").cluster_manager, 2)

        remote_lsf = self.client.post(
            reverse("ui3:runner_create"),
            {
                "name": "lsf-ssh",
                "cluster_manager": "2",
                "ssh_connection": "login.example.edu",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(remote_lsf.status_code, 400)
        self.assertContains(remote_lsf, "Remote SSH is available for Slurm", status_code=400)

    def test_create_requires_name_and_unique(self):
        self.login()
        missing = self.client.post(
            reverse("ui3:runner_create"),
            {"name": "", "cluster_manager": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(missing.status_code, 400)
        duplicate = self.client.post(
            reverse("ui3:runner_create"),
            {"name": "g2", "cluster_manager": "1", "stage_in": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_edit_updates_paths(self):
        self.login()
        modal = self.client.get(reverse("ui3:runner_edit", args=[self.runner.id]))
        self.assertContains(modal, "login.cluster.edu")
        saved = self.client.post(
            reverse("ui3:runner_edit", args=[self.runner.id]),
            {
                "name": "g2",
                "comment": "gpu login",
                "cluster_manager": "1",
                "stage_in": "1",
                "ssh_connection": "login.cluster.edu",
                "ssh_user": "ly349",
                "ssh_key": "/keys/id_ed25519",
                "cluster_manager_path": "/usr/local/slurm/current/bin/",
                "scripts_dir": "/home/ly349/bioqueue-scripts",
                "result_root": "/home/ly349/workdir",
                "log_root": "",
                "workdir": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertContains(saved, "modal-root")
        self.runner.refresh_from_db()
        self.assertEqual(self.runner.scripts_dir, "/home/ly349/bioqueue-scripts")
        self.assertEqual(self.runner.stage_in, 1)
        self.assertEqual(self.runner.cluster_manager_path, "/usr/local/slurm/current/bin/")

    def test_delete_blocks_assigned_jobs(self):
        self.login()
        self.make_job(slave=self.runner, job_name="on-g2")
        blocked = self.client.post(
            reverse("ui3:runner_delete", args=[self.runner.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertTrue(Slave.objects.filter(pk=self.runner.id).exists())

        self.runner.job_set.all().delete()
        removed = self.client.post(
            reverse("ui3:runner_delete", args=[self.runner.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(Slave.objects.filter(pk=self.runner.id).exists())

    def test_nonstaff_cannot_create(self):
        self.login("bob")
        response = self.client.post(
            reverse("ui3:runner_create"),
            {"name": "sneaky", "cluster_manager": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Slave.objects.filter(name="sneaky").exists())

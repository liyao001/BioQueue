from django.contrib.auth.models import User
from django.test import TestCase

from QueueDB.models import Job, JobStatus, ProtocolList, Reference, Step, Workspace
from ui3.services import compute_step_hash, search_jobs


class Ui3TestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="secret")
        self.other = User.objects.create_user("bob", password="secret")
        self.protocol = ProtocolList.objects.create(name="RNA-seq", description="demo", user=self.user, ver="abc123")
        self.other_protocol = ProtocolList.objects.create(name="secret-proto", user=self.other, ver="def456")
        self.workspace = Workspace.objects.create(name="ws1", user=self.user)

    def login(self, user="alice"):
        ok = self.client.login(username=user, password="secret")
        self.assertTrue(ok)

    def make_job(self, user=None, **kwargs):
        owner = user or self.user
        defaults = {
            "user": owner,
            "protocol": self.protocol if owner == self.user else self.other_protocol,
            "protocol_ver": "test",
            "job_name": "job-a",
            "parameter": "threads=4",
            "input_file": "sample.fq",
            "status": JobStatus.WAITING,
            "visibility": 1,
        }
        defaults.update(kwargs)
        return Job.objects.create(**defaults)

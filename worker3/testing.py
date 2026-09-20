"""Shared dummy job / settings builders for worker3 tests and smoke."""
from __future__ import annotations

import hashlib


ECHO_MARKER = "worker3-ok"


def step_hash(software, parameter):
    payload = "{} {}".format(software or "", (parameter or "").strip())
    return hashlib.md5(payload.encode()).hexdigest()


def worker_settings(workspace, log_dir, max_job=4):
    return {
        "env": {
            "workspace": workspace,
            "log": log_dir,
            "max_job": str(max_job),
            "cpu": "2",
            "memory": "1024",
            "disk_quota": "1024",
        },
        "cluster": {
            "type": "",
            "cpu": "1",
            "mem": "1G",
            "vrt": "1G",
            "walltime": "",
            "new_queue": "",
        },
        "ml": {
            "confidence_weight_disk": "1",
            "confidence_weight_mem": "1",
            "confidence_weight_cpu": "0.8",
            "threshold": "0.5",
        },
    }


def seed_echo_job(workspace, job_name="echo-job", marker=ECHO_MARKER, username="worker3"):
    from django.contrib.auth.models import User
    from QueueDB.models import Job, JobStatus, ProtocolList, Step

    user = User.objects.filter(username=username).first()
    if user is None:
        user = User.objects.create_user(username, password="secret")
    protocol = ProtocolList.objects.create(name="echo-proto", user=user, ver="test")
    software = "echo"
    parameter = "{} {{{{JobName}}}}".format(marker)
    Step.objects.create(
        parent=protocol,
        software=software,
        parameter=parameter,
        step_order=1,
        hash=step_hash(software, parameter),
        user=user,
    )
    return Job.objects.create(
        user=user,
        protocol=protocol,
        protocol_ver=protocol.ver,
        job_name=job_name,
        input_file="",
        parameter="",
        run_dir=workspace,
        status=JobStatus.WAITING,
    )


def disable_ml_collector(job):
    """Avoid spawning ml_collector.py; keep enough resources to schedule locally."""
    step = job.get_current_step()
    if step is None or step.resources is None:
        return step
    step.resources["learn"] = 0
    if step.resources.get("cpu") is None:
        step.resources["cpu"] = 1
    if step.resources.get("mem") is None:
        step.resources["mem"] = 1
    if step.resources.get("disk") is None:
        step.resources["disk"] = 1
    if step.resources.get("vrt_mem") is None:
        step.resources["vrt_mem"] = 1
    return step

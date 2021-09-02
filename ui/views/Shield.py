#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/25/20
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from ..tools import error, success
from worker.bases import get_config
from QueueDB.models import Job
import os


def audit_job_atom():
    a_counts = 0
    try:
        for q in Job.objects.filter():
            if q.protocol_ver != q.protocol.ver and q.audit != 1:
                q.audit = 1
                q.save()
                a_counts += 1
            else:
                # otherwise release tag
                if q.audit > 0 and q.protocol_ver == q.protocol.ver:
                    q.audit = 0
                    q.save()
        return a_counts, ""
    except Exception as e:
        return -1, e


@staff_member_required
def audit_jobs(request):
    counts, msg = audit_job_atom()
    if counts == -1:
        return error(msg)
    else:
        return success("Checking finished, %d tags were put." % counts)


def check_job_integrity(job_path):
    from configparser import ConfigParser
    snapshot_file = os.path.join(job_path, ".snapshot.ini")
    if not os.path.exists(snapshot_file):
        return 0  # compatible to old jobs
    else:
        snapshot = ConfigParser()
        snapshot.read(snapshot_file)
        for input_file, wow in snapshot['input'].items():
            cctime = int(os.path.getctime(input_file))
            cmtime = int(os.path.getmtime(input_file))

            pctime, pmtime, pdigest = wow.split(";")
            pctime = int(pctime)
            pmtime = int(pmtime)
            if cctime == pctime and cmtime == pmtime:
                return 0
            else:
                return 1


@login_required
def clean_dead_folder(request):
    from shutil import rmtree
    jobs_containers = os.path.join(get_config('env', 'workspace'), str(request.user.queuedb_profile_related.delegate.id))
    job_results = set(
        [re["result"] for re in Job.objects.filter(user_id=str(request.user.queuedb_profile_related.delegate.id)).values('result')])
    protected_folders = set(["refs", "bin", "uploads", "archives", "OVERRIDE_UPLOAD"])
    death_counter = 0
    failed = 0
    if os.path.exists(jobs_containers):
        for job_result in os.listdir(jobs_containers):
            if job_result not in job_results and job_result not in protected_folders:
                death_counter += 1
                try:
                    abs_path = os.path.join(jobs_containers, job_result)
                    if os.path.isdir(abs_path):
                        rmtree(abs_path)
                except:
                    failed += 1
    return success("%d/%d dead folder detected. %d of them failed to be cleaned." % (death_counter,
                                                                                     len(job_results),
                                                                                     failed))


@staff_member_required
def clean_dead_lock(request):
    Job.objects.filter(status__gte=0).update(status=-3)
    Job.objects.filter(status=-2).update(status=-3)
    return success("Updated")


@staff_member_required
def update_bioqueue(request):
    try:
        update_py_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/worker/update.py'
        update_command = 'python %s' % update_py_path
        if not os.system(update_command):
            return success('Your instance has been updated, please restart '
                           'the ui1 server and queue service to apply the changes.')
        else:
            return error('An error occurred during the update process, please run update.py manually.')
    except Exception as e:
        return error(str(e))

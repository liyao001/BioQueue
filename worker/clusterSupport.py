#!/usr/bin/env python
import time
import os
import django_initial
from ui.models import Queue


def if_terminate(job_id):
    job = Queue.objects.get(job_id)
    return job.ter


def dispatch(cluster_type):
    if cluster_type == 'torque_pbs':
        from cluster_models.TorquePBS import TorquePBS
        cluster_model = TorquePBS()
    else:
        cluster_model = None
    return cluster_model


def main(cluster_type, parameter, job_id, step_id, cpu, mem, queue, workspace, learning=0, trace_id=0):
    cluster_model = dispatch(cluster_type)
    if cluster_model:
        if learning == 0:
            cluster_id = cluster_model.submit_job(parameter, job_id, step_id, cpu, mem, queue, workspace)
        else:
            tmp_filename = str(job_id)+'_'+str(step_id)+'.tmp'
            tmp_file = open(tmp_filename, mode='w')
            tmp_file.write(parameter)
            tmp_file.close()
            ml_parameter = ("python", os.path.join(os.path.split(os.path.realpath(__file__))[0], "mlContainer.py"),
                            "-j", os.path.join(os.path.split(os.path.realpath(__file__))[0], tmp_filename),
                            "-w", workspace, "-t", str(trace_id))
            cluster_id = cluster_model.submit_job(ml_parameter, job_id, step_id, cpu, mem, queue, workspace)

        while True:
            status_code = cluster_model.query_job_status()
            if status_code == step_id or status_code == 0:
                if if_terminate(job_id):
                    cluster_model.cancel_job()
                    break
                time.sleep(30)
            elif status_code == -1:
                return 0
            else:
                return 1
    else:
        print 'Unknown Cluster'

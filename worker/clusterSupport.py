#!/usr/bin/env python
import time
import os
import django_initial
from ui.models import Queue


def if_terminate(job_id):
    """
    If terminate a job
    :param job_id: int
    :return:
    """
    try:
        job = Queue.objects.get(job_id)
        return job.ter
    except:
        return 1


def get_cluster_models():
    """
    Get cluster modules
    :return: list, module names
    """
    models = []
    for model_name in os.listdir("cluster_models"):
        if not model_name.endswith('.py') or model_name.startswith('_') or model_name.startswith('cluster'):
            continue
        models.append(model_name.replace('.py', ''))
    return models


def dispatch(cluster_type):
    """
    Load cluster module
    :param cluster_type: string
    :return: mixed, module or None
    """
    models = get_cluster_models()
    if cluster_type in models:
        try:
            model = __import__("cluster_models." + cluster_type, fromlist=[cluster_type])
            return model
        except:
            return None
    else:
        return None


def main(cluster_type, parameter, job_id, step_id, cpu, mem, queue, workspace, learning=0, trace_id=0):
    """
    Cluster support function
    :param cluster_type: string, cluster type, like TorquePBS
    :param parameter: string, job parameter
    :param job_id: int, job id
    :param step_id: int, step order
    :param cpu: int, cpu cores
    :param mem: string, allocate memory
    :param queue: string, queue name
    :param workspace: string, job path
    :param learning: int
    :param trace_id: int
    :return: int
    """
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
            status_code = cluster_model.query_job_status(cluster_id)
            if status_code == step_id or status_code == 0:
                if if_terminate(job_id):
                    cluster_model.cancel_job(cluster_id)
                    break
                time.sleep(30)
            elif status_code == -1:
                return 0
            else:
                return 1
    else:
        print 'Unknown Cluster'

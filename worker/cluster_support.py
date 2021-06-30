#!/usr/bin/env python
from __future__ import print_function
import time
import os
from . import django_initial
from QueueDB.models import Job, Training


def if_terminate(job_id):
    """
    If terminate a job
    :param job_id: int
    :return:
    """
    try:
        job = Job.objects.get(id=job_id)
        return job.ter
    except:
        return 1


def get_cluster_models():
    """
    Get cluster modules
    :return: list, module names
    """
    models = []
    models_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'cluster_models')
    for model_name in os.listdir(models_path):
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


def main(cluster_type, parameter, job_id, step_id, cpu, mem, vrt_mem, queue, workspace, log_path, wall_time='', learning=0, trace_id=0):
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
    :param log_path: string, path to store job logs
    :param wall_time: string, CPU time limit for a job
    :param learning: int
    :param trace_id: int
    :return: int
    """
    cluster_model = dispatch(cluster_type)
    base_name = str(job_id) + '_' + str(step_id)
    ml_file_name = os.path.join(workspace, base_name + ".mlc")
    pending_tag = 0
    if cluster_model:
        if learning == 0:
            cluster_id = cluster_model.submit_job(parameter, job_id, step_id, cpu, mem, vrt_mem, queue,
                                                  log_path, wall_time, workspace)
        else:
            tmp_filename = os.path.join(workspace, base_name + ".tmp")
            tmp_file = open(tmp_filename, mode='w')
            tmp_file.write(parameter)
            tmp_file.close()

            ml_parameter = "python %s -j %s -w %s -o %s" % \
                           (os.path.join(os.path.split(os.path.realpath(__file__))[0], "ml_container.py"),
                            os.path.join(os.path.split(os.path.realpath(__file__))[0], tmp_filename),
                            workspace, ml_file_name)

            cluster_id = cluster_model.submit_job(ml_parameter, job_id, step_id, cpu, mem, vrt_mem, queue,
                                                  log_path, wall_time, workspace)
            if cluster_id == 0:
                # fail to submit
                return 1
        while True:
            status_code = cluster_model.query_job_status(cluster_id)
            if status_code == 1 or status_code == 2:
                # running or queueing
                if status_code == 2 and pending_tag == 0:
                    # queueing
                    pending_tag = 1
                    try:
                        job = Job.objects.get(id=job_id)
                        job.status = job.set_wait(5)
                    except:
                        pass

                if status_code == 1 and pending_tag == 1:
                    pending_tag = 0
                    try:
                        job = Job.objects.get(id=job_id)
                        job.set_status(step_id + 1)
                    except:
                        pass

                if if_terminate(job_id):
                    cluster_model.cancel_job(cluster_id)
                    break
                time.sleep(30)
            elif status_code == 0:
                try:
                    os.remove(tmp_filename)
                except:
                    pass
                if learning == 1:
                    # load learning results
                    try:
                        import pickle
                        with open(ml_file_name, "rb") as handler:
                            res = pickle.load(handler)
                            training_item = Training.objects.get(id=trace_id)
                            training_item.update_cpu_mem(res['cpu'], res['mem'], res['vrt_mem'])
                        os.remove(ml_file_name)
                    except:
                        pass
                return 0
            else:
                return 1
    else:
        print('Unknown Cluster')

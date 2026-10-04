#!/usr/bin/env python
from __future__ import print_function
import logging
import numbers
import os
import time

import bases

from . import django_initial
from QueueDB.models import Job, Training

logger = logging.getLogger("BioQueue.cluster_support")


def if_terminate(job_id):
    """
    Return True if the user requested termination for this job.

    On DB errors, returns False so we do not spuriously cancel cluster work.
    """
    try:
        job = Job.objects.get(id=job_id)
        return bool(job.ter)
    except Exception as e:
        logger.warning("if_terminate(%s): %s", job_id, e)
        return False


def get_cluster_models():
    """
    Get cluster modules
    :return: list, module names
    """
    models = []
    models_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'cluster_models')
    try:
        names = os.listdir(models_path)
    except OSError as e:
        logger.error("get_cluster_models: cannot list %s: %s", models_path, e)
        return models
    for model_name in names:
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
    if cluster_type not in models:
        return None
    try:
        return __import__("cluster_models." + cluster_type, fromlist=[cluster_type])
    except Exception as e:
        logger.error("dispatch(%r): %s", cluster_type, e)
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
    tmp_filename = None
    pending_tag = 0
    if not cluster_model:
        logger.error("Unknown cluster type: %r", cluster_type)
        return 1

    if learning == 0:
        cluster_id = cluster_model.submit_job(parameter, job_id, step_id, cpu, mem, vrt_mem, queue,
                                              log_path, wall_time, workspace)
    else:
        tmp_filename = os.path.join(workspace, base_name + ".tmp")
        with open(tmp_filename, mode='w') as tmp_file:
            tmp_file.write(parameter)

        ml_parameter = "python %s -j %s -w %s -o %s" % \
                       (os.path.join(os.path.split(os.path.realpath(__file__))[0], "ml_container.py"),
                        os.path.join(os.path.split(os.path.realpath(__file__))[0], tmp_filename),
                        workspace, ml_file_name)

        cluster_id = cluster_model.submit_job(ml_parameter, job_id, step_id, cpu, mem, vrt_mem, queue,
                                              log_path, wall_time, workspace)
        if cluster_id == 0:
            return 1

    while True:
        status_code = cluster_model.query_job_status(cluster_id)
        if status_code == 1 or status_code == 2:
            if status_code == 2 and pending_tag == 0:
                pending_tag = 1
                try:
                    job = Job.objects.get(id=job_id)
                    job.set_wait(5)
                except Exception as e:
                    logger.warning("cluster job %s queueing status sync: %s", job_id, e)

            if status_code == 1 and pending_tag == 1:
                pending_tag = 0
                try:
                    job = Job.objects.get(id=job_id)
                    job.set_status(step_id + 1)
                except Exception as e:
                    logger.warning("cluster job %s running status sync: %s", job_id, e)

            if if_terminate(job_id):
                cluster_model.cancel_job(cluster_id)
                break
            time.sleep(30)
        elif status_code == 0:
            if tmp_filename:
                try:
                    os.remove(tmp_filename)
                except OSError as e:
                    logger.debug("remove tmp %s: %s", tmp_filename, e)
            if learning == 1:
                try:
                    res = bases.safe_pickle_load(
                        ml_file_name, max_bytes=bases.PICKLE_MAX_LEARNING_BYTES
                    )
                    if not isinstance(res, dict):
                        raise ValueError("learning payload must be a dict, got %s" % type(res))
                    for key in ("cpu", "mem", "vrt_mem"):
                        if key not in res:
                            raise ValueError("learning payload missing key %r" % key)
                        if not isinstance(res[key], numbers.Real):
                            raise ValueError("learning payload key %r must be numeric" % key)
                    training_item = Training.objects.get(id=trace_id)
                    training_item.update_cpu_mem(res["cpu"], res["mem"], res["vrt_mem"])
                    os.remove(ml_file_name)
                except Exception as e:
                    logger.warning("learning result load for trace %s: %s", trace_id, e)
            return 0
        else:
            return 1

    # User cancelled while job was queued/running on cluster
    return 2

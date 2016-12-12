#!/usr/bin/env python
from procManeuver import if_terminate
import time
from baseDriver import update


def dispatch(cluster_type):
    if cluster_type == 'torque_pbs':
        from cluster_models.TorquePBS import TorquePBS
        cluster_model = TorquePBS()
    else:
        cluster_model = None
    return cluster_model


    cluster_model = dispatch(cluster_type)
    if cluster_model:
        while True:
            status_code = cluster_model.query_job_status()
            if status_code == step_id or status_code == 0:
                    cluster_model.cancel_job()
                    break
                time.sleep(30)
            elif status_code == -1:
                return 0
            else:
                return 1
    else:
        print 'Unknown Cluster'

#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2017/12/1 0:10
# @Project : BioQueue
# @Author  : Li Yao
# @File    : LSF.py
# @Description: Minimal support for IBM LSF

from __future__ import print_function


def cancel_job(job_id):
    """
    Cancel job
    :param job_id: int, job id
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        step_process = subprocess.Popen(('bkill', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        return 1
    except Exception as e:
        print(e)
        return 0


def load_template():
    """
    Load template
    :return: string, script template
    """
    import os
    with open(os.path.join(os.path.split(os.path.realpath(__file__))[0], 'LSF.tpl'), 'r') as file_handler:
        template = file_handler.read()
    return template


def query_job_status(job_id):
    """
    Query job status
    :param job_id: int, job id
    :return: int, job status
    """
    import subprocess
    step_process = subprocess.Popen(('bjobs', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    stdout, stderr = step_process.communicate()
    stdout = str(stdout)
    stderr = str(stderr)
    stdout += stderr
    raw_code = stdout.split('\n')[1].split()[2]
    if raw_code == 'RUN':
        # The job is currently running.
        return 1
    elif raw_code == 'PROV':
        # The job has been dispatched to a power-saved host that is waking up. Before the job can be sent to the sbatchd, it is in a PROV state.
        return 2
    elif raw_code == 'PEND':
        # The job is pending. That is, it has not yet been started.
        return 2
    elif raw_code == 'WAIT':
        # For jobs submitted to a chunk job queue, members of a chunk job that are waiting to run.
        return 2
    elif raw_code == 'PSUSP':
        # The job has been suspended, either by its owner or the LSF administrator, while pending.
        return 2
    elif raw_code == 'USUSP':
        # The job has been suspended, either by its owner or the LSF administrator, while running.
        return 2
    elif raw_code == 'SSUSP':
        return 2
    elif raw_code == 'DONE':
        # The job has terminated with status of 0.
        return 0
    elif raw_code == 'EXIT':
        # The job has terminated with a non-zero status.
        return -8
    else:
        # Unknown status
        return -3


def readable_to_kb(raw_value):
    """
    Convert readable value to integer in kb
    :param raw_value: string
    :return: int
    """
    # from math import ceil
    value_in_kb = 0
    if raw_value.find('KB') != -1:
        value_in_kb = int(raw_value.replace('KB', ''))
    elif raw_value.find('MB') != -1:
        value_in_kb = int(raw_value.replace('MB', '')) * 1024
    elif raw_value.find('GB') != -1:
        value_in_kb = int(raw_value.replace('GB', '')) * 1024 * 1024
    return value_in_kb


def submit_job(protocol, job_id, job_step, cpu=0, mem='', vrt_mem='', queue='', log_file='', wall_time='', workspace=''):
    """
    Submit job
    :param protocol: string, job parameter, like "wget http://www.a.com/b.txt"
    :param job_id: int, job id
    :param job_step: int, job order
    :param cpu: int, cpu cores
    :param mem: string, allocated memory, eg. 64G
    :param queue: string, job queue
    :param log_file: string, log file
    :param wall_time: string, cpu time
    :param workspace: string, job path
    :return: int, if success, return trace id, else return 0
    """
    import subprocess
    import os
    import re
    template = load_template()

    if not os.path.exists(workspace):
        try:
            os.makedirs(workspace)
        except:
            pass

    job_name = str(job_id)+'-'+str(job_step)+'.xsd'
    lsf_script_content = template.replace('{PROTOCOL}', protocol)\
        .replace('{JOBNAME}', job_name).replace('{GLOBAL_MAX_CPU_FOR_CLUSTER}', str(cpu))\
        .replace('{DEFAULT_QUEUE}', queue).replace('{WORKSPACE}', workspace)
    if mem != '':
        # By default, the limit is specified in KB.
        # Use LSF_UNIT_FOR_LIMITS in lsf.conf to specify a larger unit for the limit (MB, GB, TB, PB, or EB).
        converted_mem = readable_to_kb(mem)
        if converted_mem != 0:
            lsf_script_content = lsf_script_content.replace('{MEM}', '#BSUB -M ' + str(converted_mem))
        else:
            lsf_script_content = lsf_script_content.replace('{MEM}', '')
    else:
        lsf_script_content = lsf_script_content.replace('{MEM}', '')
    if wall_time != '':
        # in minutes by default
        lsf_script_content = lsf_script_content.replace('{WALLTIME}', '#BSUB -W '+str(wall_time))
    else:
        # no limit
        lsf_script_content = lsf_script_content.replace('{WALLTIME}', '')
    if log_file != '':
        lsf_script_content = lsf_script_content.replace('{STDERR}', log_file).replace('{STDOUT}', log_file)
    else:
        lsf_script_content = lsf_script_content.replace('{STDERR}', workspace).replace('{STDOUT}', workspace)
    try:
        job_file_path = os.path.join(workspace, job_name)
        with open(job_file_path, 'w') as pbs_handler:
            pbs_handler.write(lsf_script_content)
        step_process = subprocess.Popen('bsub < %s' % job_file_path, shell=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, cwd=workspace)
        stdout, stderr = step_process.communicate()
        # Job <6449> is submitted to queue <normal>.
        if step_process.returncode != 0:
            return 0
        re_pattern_for_lsf_id = "Job <(\d+)\> is submitted"
        status_m = re.search(re_pattern_for_lsf_id, stdout)
        try:
            os.remove(job_file_path)
        except:
            pass
        if status_m:
            lsf_trace_id = status_m.group(1)
            return lsf_trace_id
        else:
            return 0
    except Exception as e:
        print(e)
        return 0
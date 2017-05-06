#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2017/5/3 2:05
# @Project : BioQueue
# @Author  : Li Yao
# @File    : HTCondor.py

from __future__ import print_function


def cancel_job(job_id):
    """
    Cancel job
    :param job_id: int, job id
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        step_process = subprocess.Popen(('condor_rm', str(job_id)), shell=False, stdout=subprocess.PIPE,
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
    with open(os.path.join(os.path.split(os.path.realpath(__file__))[0], 'HTCondor.tpl'), 'r') as file_handler:
        template = file_handler.read()
    return template


def query_job_status(job_id):
    """
    Query job status
    :param job_id: int, job id
    :return: int, job status
    """
    return None


def build_executable_file(job_id, job_step, protocol, workspace):
    """
    Build executable file
    :param job_id: int
    :param job_step: int
    :param protocol: str
    :param workspace: str
    :return: str, file path
    """
    from ui.tools import os_to_int
    import os
    if os_to_int() == 2:
        job_name = str(job_id) + '-' + str(job_step) + '.bat'
        script = """:: file name: %s
@echo off

cd %s
%s
""" % (job_name, workspace, protocol)
    else:
        job_name = str(job_id) + '-' + str(job_step) + '.sh'
        script = """#!/bin/bash
# file name: %s

cd %s
%s
""" % (job_name, workspace, protocol)
    file_name = os.path.join(workspace, job_name)
    file_handler = open(file_name, 'w')
    file_handler.write(script)
    file_handler.close()
    return file_name


def submit_job(protocol, job_id, job_step, cpu=0, mem='', queue='', log_file='', wall_time='', workspace=''):
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

    job_name = str(job_id)+'-'+str(job_step)+'.sub'
    pbs_script_content = template.replace('{PROTOCOL}', build_executable_file(job_id, job_step, protocol, workspace))\
        .replace('{JOBNAME}', job_name).replace('{GLOBAL_MAX_CPU_FOR_CLUSTER}', str(cpu))\
        .replace('{DEFAULT_QUEUE}', queue).replace('{WORKSPACE}', workspace)
    if mem != '':
        pbs_script_content = pbs_script_content.replace('{MEM}', 'RequestMemory='+mem)
    else:
        pbs_script_content = pbs_script_content.replace('{MEM}', '')
    if wall_time != '':
        pbs_script_content = pbs_script_content.replace('{WALLTIME}', '#PBS -l walltime='+wall_time)
    else:
        # no limit
        pbs_script_content = pbs_script_content.replace('{WALLTIME}', '')
    if log_file != '':
        pbs_script_content = pbs_script_content.replace('{STDERR}', log_file).replace('{STDOUT}', log_file)
    else:
        pbs_script_content = pbs_script_content.replace('{STDERR}', workspace).replace('{STDOUT}', workspace)
    try:
        job_file_path = os.path.join(workspace, job_name)
        with open(job_file_path, 'w') as pbs_handler:
            pbs_handler.write(pbs_script_content)
        step_process = subprocess.Popen(('condor_submit', job_file_path), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, cwd=workspace)
        stdout, stderr = step_process.communicate()
        re_pattern_for_condor_id = "submitted to cluster (\d+)\."
        status_m = re.search(re_pattern_for_condor_id, stdout)
        if status_m:
            condor_trace_id = status_m.group(1)
        return condor_trace_id
    except Exception as e:
        print(e)
        return 0

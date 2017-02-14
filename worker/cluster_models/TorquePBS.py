#!/usr/bin/env python

def alter_attribute(job_id, attribute):
    """
    Change job attribute
    :param job_id: int, job id
    :param attribute: string, job attribute
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        parameter = ['qalter']
        parameter.extend(attribute)
        parameter.append(str(job_id))

        step_process = subprocess.Popen(parameter, shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        return 1
    except Exception, e:
        print e
        return 0


def cancel_job(job_id):
    """
    Cancel job
    :param job_id: int, job id
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        step_process = subprocess.Popen(('qdel', str(job_id)), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        return 1
    except Exception, e:
        print e
        return 0


def get_cluster_status():
    """
    Get cluster status
    :return: dict, node status (load, memav, memtol)
    """
    import subprocess
    import re
    cluster_status = dict()
    try:
        step_process = subprocess.Popen(('pbsnodes',), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        nodes = stdout.split('\n\n')
        load_pattern = re.compile('loadave=([+-]?\\d*\\.\\d+)(?![-+0-9\\.]),', re.IGNORECASE | re.DOTALL)
        memory_pattern = re.compile('availmem=(\\d+)kb,', re.IGNORECASE | re.DOTALL)
        total_memory_pattern = re.compile('totmem=(\\d+)kb,', re.IGNORECASE | re.DOTALL)
        for node in nodes:
            node_status = dict()
            load_m = load_pattern.search(node)
            if load_m:
                node_status['load'] = float(load_m.group(1))
            mem_m = memory_pattern.search(node)
            if mem_m:
                node_status['memav'] = int(mem_m.group(1)) * 1024
            totmem_m = total_memory_pattern.search(node)
            if totmem_m:
                node_status['memtol'] = int(totmem_m.group(1)) * 1024
            node_name = node.split('\n')[0]
            cluster_status[node_name] = node_status
    except Exception, e:
        print e
    return cluster_status


def hold_job(job_id):
    """
    Hold job
    :param job_id: int, job id
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        step_process = subprocess.Popen(('qhold', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        return 1
    except Exception, e:
        print e
        return 0


def load_template():
    """
    Load template
    :return: string, script template
    """
    import os
    with open(os.path.join(os.path.split(os.path.realpath(__file__))[0], 'TorquePBS.tpl'), 'r') as file_handler:
        template = file_handler.read()
    return template


def query_job_status(job_id, step_id):
    """
    Query job status
    :param job_id: int, job id
    :param step_id: int, step order
    :return: int, job status
    """
    import subprocess
    import re
    step_process = subprocess.Popen(('qstat', '-f', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    stdout, stderr = step_process.communicate()
    status_pattern = re.compile('job_state\\s+=\\s+(.)', re.IGNORECASE | re.DOTALL)
    status_m = status_pattern.search(stdout)
    if status_m:
        raw_code = status_m.group(1)
        if raw_code == 'R':
            return step_id
        elif raw_code == 'Q':
            return 0
        elif raw_code == 'C':
            return -1
    else:
        return -3


def release_job(job_id):
    """
    Release a job
    :param job_id: int, job id
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        step_process = subprocess.Popen(('qrls', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        return 1
    except Exception, e:
        print e
        return 0


def submit_job(protocol, job_id, job_step, cpu=0, mem='', queue='', workspace=''):
    """
    Submit job
    :param protocol: string, job parameter, like "wget http://www.a.com/b.txt"
    :param job_id: int, job id
    :param job_step: int, job order
    :param cpu: int, cpu cores
    :param mem: string, allocated memory, eg. 64G
    :param queue: string, job queue
    :param workspace: string, job path
    :return: int, if success, return trace id, else return 0
    """
    import subprocess
    template = load_template()
    job_name = str(job_id)+'-'+str(job_step)+'.pbs'
    pbs_script_content = template.replace('{PROTOCOL}', protocol)\
        .replace('{JOBNAME}', job_name).replace('{GLOBAL_MAX_CPU_FOR_CLUSTER}', str(cpu))\
        .replace('{DEFAULT_QUEUE}', queue).replace('{WORKSPACE}', workspace)
    if mem != '':
        pbs_script_content = pbs_script_content.replace('{MEM}', mem+',')
    else:
        pbs_script_content = pbs_script_content.replace('{MEM}', '')
    try:
        with open(job_name, 'w') as pbs_handler:
            pbs_handler.write(pbs_script_content)
        step_process = subprocess.Popen(('qsub', job_name), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        pbs_trace_id = stdout.split('\n')[0]
        return pbs_trace_id
    except Exception, e:
        print e
        return 0

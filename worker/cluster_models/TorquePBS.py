#!/usr/bin/env python


from __future__ import print_function


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
    except Exception as e:
        print(e)
        return 0


def cancel_job(job_id):
    """
    Cancel job
    :param job_id: int, job id
    :return: if success, return 1, else return 0
    """
    import subprocess
    try:
        step_process = subprocess.Popen(('qdel', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        return 1
    except Exception as e:
        print(e)
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
    except Exception as e:
        print(e)
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
    except Exception as e:
        print(e)
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


def query_job_status(job_id):
    """
    Query job status
    :param job_id: int, job id
    :return: int, job status
    """
    import subprocess
    import re
    step_process = subprocess.Popen(('qstat', '-f', str(job_id)), shell=False, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    stdout, stderr = step_process.communicate()
    status_pattern = re.compile('job_state\\s+=\\s+(.)', re.IGNORECASE | re.DOTALL)
    exit_pattern = re.compile('exit_status\\s+=\\s+(.)', re.IGNORECASE | re.DOTALL)
    status_m = status_pattern.search(stdout)
    '''
    TORQUE Supplied Exit Codes
    JOB_EXEC_OK 0
    JOB_EXEC_FAIL1 -1 job exec failed, before files, no retry
    JOB_EXEC_FAIL2 -2 job exec failed, after files, no retry
    JOB_EXEC_RETRY -3 job execution failed, do retry
    JOB_EXEC_INITABT -4 job aborted on MOM initialization
    JOB_EXEC_INITRST -5 job aborted on MOM init, chkpt, no migrate
    JOB_EXEC_INITRMG -6 job aborted on MOM init, chkpt, ok migrate
    JOB_EXEC_BADRESRT -7 job restart failed
    JOB_EXEC_CMDFAIL -8 exec() of user command failed
    '''
    if status_m:
        raw_code = status_m.group(1)
        if raw_code == 'R':
            # running
            return 1
        elif raw_code == 'Q':
            # queueing
            return 2
        elif raw_code == 'C':
            # completed
            try:
                exit_m = exit_pattern.search(stdout)
                if exit_m:
                    exit_code = exit_m.group(1)
                    exit_code = int(exit_code)
                    if exit_code == 1 or exit_code == 2:
                        exit_code = -8
                else:
                    exit_code = 0
                return int(exit_code)
            except:
                return 0
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
    except Exception as e:
        print(e)
        return 0


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
    template = load_template()

    if not os.path.exists(workspace):
        try:
            os.makedirs(workspace)
        except:
            pass

    job_name = str(job_id)+'-'+str(job_step)+'.pbs'
    pbs_script_content = template.replace('{PROTOCOL}', protocol)\
        .replace('{JOBNAME}', job_name).replace('{GLOBAL_MAX_CPU_FOR_CLUSTER}', str(cpu))\
        .replace('{DEFAULT_QUEUE}', queue).replace('{WORKSPACE}', workspace)
    if mem != '' and vrt_mem != '':
        pbs_script_content = pbs_script_content.replace('{MEM}', 'mem='+mem+',pmem='+mem+',vmem='
                                                        +vrt_mem+',pvmem='+vrt_mem+',')
    elif mem != '':
        pbs_script_content = pbs_script_content.replace('{MEM}', 'mem=' + mem + ',pmem=' + mem + ',')
    elif vrt_mem != '':
        pbs_script_content = pbs_script_content.replace('{MEM}', 'vmem=' + vrt_mem + ',pvmem=' + vrt_mem + ',')
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
        step_process = subprocess.Popen(('qsub', job_file_path), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, cwd=workspace)
        stdout, stderr = step_process.communicate()
        pbs_trace_id = stdout.split('\n')[0]
        return pbs_trace_id
    except Exception as e:
        print(e)
        return 0

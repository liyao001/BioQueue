#!/usr/local/bin python
from __future__ import print_function
import getopt
import time
import subprocess
import psutil
import sys
from mlCollector import get_cpu, get_mem, get_cpu_mem
from baseDriver import check_shell_sig
import django_initial
from ui.models import Training
import pickle


def get_protocol(fn):
    pf = open(fn)
    tmp = pf.readlines()
    return tmp


def main(pf, wd, output_file):
    protocol = get_protocol(pf)
    for step in protocol:
        vrt_mem_list = []
        mem_list = []
        cpu_list = []
        from parameterParser import parameter_string_to_list
        parameters = parameter_string_to_list(step)

        true_shell = check_shell_sig(parameters)

        if true_shell:
            proc = subprocess.Popen(step, shell=True, cwd=wd)
        else:
            proc = subprocess.Popen(parameters, shell=False, stdout=None, stderr=None, cwd=wd)

        process_id = proc.pid

        while proc.poll() is None:
            if process_id in psutil.pids():
                proc_info = psutil.Process(process_id)

                if proc_info.is_running():
                    try:
                        total_memory_usage, vrt = get_mem(process_id)
                        total_cpu_usage = get_cpu(process_id)
                        children = proc_info.children()
                        for child in children:
                            t1, t2 = get_mem(child.pid)
                            total_memory_usage += t1
                            vrt += t2
                            # total_memory_usage += get_mem(child.pid)
                            total_cpu_usage += get_cpu(child.pid)
                        mem_list.append(total_memory_usage)
                        vrt_mem_list.append(vrt)
                        cpu_list.append(total_cpu_usage)
                    except Exception as e:
                        print(e)
            time.sleep(10)

        cpu_usage, mem_usage, vrt_mem_usage = get_cpu_mem(cpu_list, mem_list, vrt_mem_list)
        # save results to local file
        result = {'cpu': cpu_usage, 'mem': mem_usage, 'vrt_mem': vrt_mem_usage}
        with open(output_file, 'wb') as handler:
            pickle.dump(result, handler)

        if proc.returncode != 0:
            import sys
            sys.exit(1)


if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:], "j:w:o:", ["job=", "workdir=", "output="])
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit()
    if len(opts) == 0:
        sys.exit()
    job = ''
    work_dir = ''
    trace_id = 0
    output_file = ''
    for o, a in opts:
        if o in ("-j", "--job"):
            job = a
        elif o in ("-w", "--workdir"):
            work_dir = a
        elif o in ("-o", "--output"):
            output_file = a
    main(job, work_dir, output_file)

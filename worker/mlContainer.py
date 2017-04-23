#!/usr/local/bin python
import getopt
import shlex
import time
import subprocess
import psutil
import sys
from mlCollector import get_cpu, get_mem
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
        mem_list = []
        cpu_list = []
        par = shlex.shlex(step)
        par.quotes = '"'
        par.whitespace_split = True
        par.commenters = ''
        parameters = list(par)
        true_shell = 0
        redirect_tags = ('>', '<')

        for rt in redirect_tags:
            if rt in parameters:
                true_shell = 1
                break

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
                        total_memory_usage = get_mem(process_id)
                        total_cpu_usage = get_cpu(process_id)
                        children = proc_info.children()
                        for child in children:
                            total_memory_usage += get_mem(child.pid)
                            total_cpu_usage += get_cpu(child.pid)
                        mem_list.append(total_memory_usage)
                        cpu_list.append(total_cpu_usage)
                    except Exception, e:
                        print e
            time.sleep(10)

        if len(mem_list) > 0:
            mem_usage = max(mem_list)
        else:
            mem_usage = -1
        if len(cpu_list) > 2:
            samples = int(round(len(cpu_list) * 0.5))
            cpu_list.sort(reverse=True)
            cpu_usage = sum(cpu_list[0:samples]) / samples
        elif len(cpu_list) > 0:
            cpu_usage = sum(cpu_list) / len(cpu_list)
        else:
            cpu_usage = -1

        # save results to local file
        result = {'cpu': cpu_usage, 'mem': mem_usage}
        with open(output_file, 'wb') as handler:
            pickle.dump(result, handler)


if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:], "j:w:o:", ["job=", "workdir=", "output="])
    except getopt.GetoptError, err:
        print str(err)
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

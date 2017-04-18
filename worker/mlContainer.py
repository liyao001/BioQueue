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
    protocol = []
    pf = open(fn)
    tmp = pf.readlines()
    return tmp


def main(pf, wd, trace, output_file):
    protocol = get_protocol(pf)
    for step in protocol:
        mem_list = []
        cpu_list = []
        par = shlex.shlex(step)
        par.quotes = '"'
        par.whitespace_split = True
        par.commenters = ''
        parameters = list(par)
        proc = subprocess.Popen(parameters, shell=False, stdout=None, stderr=None, cwd=wd)
        process_id = proc.pid

        while proc.poll() is None:
            if process_id in psutil.pids():
                proc_info = psutil.Process(process_id)

                if proc_info.is_running():
                    try:
                        mem_list.append(get_mem(process_id))
                        cpu_list.append(get_cpu(process_id))
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
        opts, args = getopt.getopt(sys.argv[1:], "j:w:t:o:", ["job=", "workdir=", "trace=", "output="])
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
        elif o in ("-t", "--trace"):
            trace_id = int(a)
        elif o in ("-o", "--output"):
            output_file = a
    main(job, work_dir, trace_id, output_file)

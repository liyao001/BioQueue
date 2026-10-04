#!/usr/bin/env python
from __future__ import print_function
import getopt
import logging
import os
import pickle
import subprocess
import sys
import time

import django_initial
import psutil

import bases
from _step import _Step
from ml_collector import get_cpu, get_cpu_mem, get_mem

logger = logging.getLogger("BioQueue.ml_container")


def get_protocol(fn):
    with open(fn, "r", encoding="utf-8", errors="replace") as pf:
        return pf.readlines()


def main(protocol_file, work_dir, output_file):
    protocol = get_protocol(protocol_file)
    for raw_step in protocol:
        step = raw_step.strip()
        if not step or step.startswith("#"):
            continue
        vrt_mem_list = []
        mem_list = []
        cpu_list = []
        parameters = _Step._parameter_string_to_list(step)

        true_shell = bases.check_shell_sig(parameters)

        if true_shell:
            proc = subprocess.Popen(step, shell=True, cwd=work_dir)
        else:
            proc = subprocess.Popen(
                parameters, shell=False, stdout=None, stderr=None, cwd=work_dir
            )

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
                            try:
                                t1, t2 = get_mem(child.pid)
                                total_memory_usage += t1
                                vrt += t2
                                total_cpu_usage += get_cpu(child.pid)
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                continue
                        mem_list.append(total_memory_usage)
                        vrt_mem_list.append(vrt)
                        cpu_list.append(total_cpu_usage)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                        logger.debug("sample process %s: %s", process_id, e)
                    except Exception as e:
                        logger.warning("sample process %s: %s", process_id, e)
            time.sleep(10)

        cpu_usage, mem_usage, vrt_mem_usage = get_cpu_mem(cpu_list, mem_list, vrt_mem_list)
        result = {"cpu": cpu_usage, "mem": mem_usage, "vrt_mem": vrt_mem_usage}
        out_tmp = output_file + ".tmp"
        with open(out_tmp, "wb") as handler:
            pickle.dump(result, handler)
        os.replace(out_tmp, output_file)

        if proc.returncode != 0:
            sys.exit(1)


if __name__ == "__main__":
    try:
        opts, args = getopt.getopt(sys.argv[1:], "j:w:o:", ["job=", "workdir=", "output="])
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit(1)
    if len(opts) == 0:
        sys.exit(1)
    protocol_file = ""
    work_dir = ""
    output_file = ""
    for o, a in opts:
        if o in ("-j", "--job"):
            protocol_file = a
        elif o in ("-w", "--workdir"):
            work_dir = a
        elif o in ("-o", "--output"):
            output_file = a
    main(protocol_file=protocol_file, work_dir=work_dir, output_file=output_file)

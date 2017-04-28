#!/usr/local/bin python
from __future__ import print_function
import psutil
import time
import getopt
import sys
import django_initial
from ui.models import Training

mem_list = []
cpu_list = []
read_list = []
write_list = []


def get_mem(pid):
    running_process = psutil.Process(pid)
    if running_process.is_running():
        mem = running_process.memory_info()
        return mem[0]
    else:
        return 0


def get_cpu(pid):
    running_process = psutil.Process(pid)
    if running_process.is_running():
        cpu = running_process.cpu_percent(interval=1)
        return cpu
    else:
        return 0


def get_io(pid):
    running_process = psutil.Process(pid)
    if running_process.is_running():
        io = running_process.io_counters()
        return io[2], io[3]
    else:
        return 0


def get_cpu_mem(cpu_list, mem_list):
    """
    Get CPU and memory usage
    :param cpu_list: list, cpu usage info
    :param mem_list: list, memory usage info
    :return: tuple, cpu_usage and mem_usage
    """
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
    return cpu_usage, mem_usage


def main():

    try:
        opts, args = getopt.getopt(sys.argv[1:], "n:p:j:", ["protocolStep=", "pid=", "job_id="])
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit()
        
    if len(opts) == 0:
        sys.exit()
        
    step_hash = ''
    process_id = 0
    job_id = 0
    
    for o, a in opts:
        if o in ("-n", "--protocolStep"):
            step_hash = a
        elif o in ("-p", "--pid"):
            process_id = int(a)
        elif o in ("-j", "--job_id"):
            job_id = int(a)

    if step_hash != '' and process_id != 0:       
        while True:

            if process_id in psutil.pids():
                process_info = psutil.Process(process_id)

                if process_info.is_running():
                    try:
                        total_memory_usage = get_mem(process_id)
                        total_cpu_usage = get_cpu(process_id)
                        children = process_info.children()
                        for child in children:
                            total_memory_usage += get_mem(child.pid)
                            total_cpu_usage += get_cpu(child.pid)
                        mem_list.append(total_memory_usage)
                        cpu_list.append(total_cpu_usage)
                        time.sleep(30)
                    except Exception as e:
                        print(e)
                        break
                else:
                    break
            else:
                break

        cpu_usage, mem_usage = get_cpu_mem(cpu_list, mem_list)

        try:
            training_item = Training.objects.get(id=job_id)
            training_item.mem = mem_usage
            training_item.cpu = cpu_usage
            training_item.save()
        except:
            pass

    else:
        sys.exit()

if __name__ == '__main__':
    main()

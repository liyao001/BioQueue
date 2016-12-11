#!/usr/local/bin python
import psutil
import time
import getopt
import sys
from baseDriver import get_config, update
from databaseDriver import con_mysql

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


def create_machine_learning_item(step_hash, input_bytes, output_bytes, mem_usage, cpu_usage):
    con, cursor = con_mysql()
    dyn_sql = """INSERT INTO %s (`step`, `input`, `output`, `mem`, `cpu`) VALUES ('%s', '%s', '%s', '%s', '%s');"""\
              % (get_config("datasets", "train_db"), str(step_hash), str(input_bytes), str(output_bytes),
                 str(mem_usage), str(cpu_usage))
    try:
        cursor.execute(dyn_sql)
        row_id = con.insert_id()
        con.commit()
        con.close()
    except Exception, e:
        print e
        return 0
    return row_id


def main():

    try:
        opts, args = getopt.getopt(sys.argv[1:], "n:p:j:", ["protocolStep=", "pid=", "job_id="])
    except getopt.GetoptError, err:
        print str(err)
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
                    except Exception, e:
                        print e
                        break
                else:
                    break
            else:
                break

        if len(mem_list) > 0:
            mem_usage = max(mem_list)
        else:
            mem_usage = -1
        if len(cpu_list) > 2:
            samples = int(round(len(cpu_list)*0.1))
            cpu_list.sort(reverse=True)
            cpu_usage = sum(cpu_list[0:samples])/samples
        elif len(cpu_list) > 0:
            cpu_usage = sum(cpu_list)/len(cpu_list)
        else:
            cpu_usage = -1
        update(get_config('datasets', 'train_db'), job_id, 'mem', mem_usage)
        update(get_config('datasets', 'train_db'), job_id, 'cpu', cpu_usage)
    else:
        sys.exit()

if __name__ == '__main__':
    main()

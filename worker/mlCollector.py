#!/usr/local/bin python
import psutil, time, getopt, sys
from baseDriver import get_config, update
from databaseDriver import con_mysql

memList = []
cpuList = []
readList = []
writeList = []


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
    dyn_sql = """INSERT INTO %s (`step`, `in`, `out`, `mem`, `cpu`) VALUES ('%s', '%s', '%s', '%s', '%s');"""\
              % (get_config("datasets", "trainStore"), str(step_hash), str(input_bytes), str(output_bytes),
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
        
    step_hash = ''; process_id = 0; job_id = 0
    
    for o, a in opts:
        if o in ("-n","--protocolStep"):
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
                        memList.append(get_mem(process_id))
                        cpuList.append(get_cpu(process_id))
                        time.sleep(30)
                    except Exception, e:
                        print e
                        break
                else:
                    break
            else:
                break

        if len(memList) > 0:
            mem_usage = max(memList)
        else:
            mem_usage = -1
        if len(cpuList) > 2:
            samples = round(len(cpuList)*0.1)
            cpuList.sort(reverse=True)
            cpu_usage = sum(cpuList[0:samples])/samples
        elif len(cpuList) == 1:
            cpu_usage = cpuList[0]
        else:
            cpu_usage = -1
        update(get_config('datasets', 'trainStore'), job_id, 'mem', mem_usage)
        update(get_config('datasets', 'trainStore'), job_id, 'cpu', cpu_usage)
    else:
        sys.exit()

if __name__ == '__main__':
    main()

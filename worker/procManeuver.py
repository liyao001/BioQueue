#!/usr/bin/env python
import baseDriver
import getopt
import psutil
import schedule
import sys
import time
from databaseDriver import update_resource

jid = None
pid = None
cpu = None
mem = None
disk = None
job_db = baseDriver.get_config('datasets', 'job_db')


def if_terminate(job):
    terminate_signal = baseDriver.get_field('ter', job_db, 'id', str(job))
    return terminate_signal


def terminate_cron():
    if pid in psutil.pids():
        if if_terminate(jid):
            try:
                # Kill watched job
                process = psutil.Process(pid)
                process.kill()
                st_dic = {'status': -1, 'ter': 0}
                baseDriver.multi_update(job_db, jid, st_dic)
                update_resource(cpu, mem, disk)
                exit(0)
            except Exception, e:
                print e
    else:
        exit(0)

if __name__ == "__main__":
    
    try:
        opts, args = getopt.getopt(sys.argv[1:], "j:p:c:m:d:", ["jid=", "pid=", "cpu=", "memory=", "disk="])
    except getopt.GetoptError, err:
        print str(err)
        sys.exit()
    
    if len(opts) == 2:
        for o, a in opts:
            if o in ("-j", "--jid"):
                jid = int(a)
            elif o in ("-p", "--pid"):
                pid = int(a)
            elif o in ("-c", "--cpu"):
                cpu = int(a)
            elif o in ("-m", "--memory"):
                mem = int(a)
            elif o in ("-d", "--disk"):
                disk = int(a)
    else:
        sys.exit()
    
    if jid and pid:
        schedule.every(10).seconds.do(terminate_cron)
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        sys.exit()

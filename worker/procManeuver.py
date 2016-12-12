#!/usr/bin/env python
import baseDriver
import getopt
import psutil
import schedule
import sys
import time

jid = None
pid = None
job_db = baseDriver.get_config('datasets', 'job_db')

def if_terminate(job):
    terminate_signal = baseDriver.get_field('ter', job_db, 'id', str(job))
    return terminate_signal

def terminate_cron():
    if if_terminate(jid):
        try:
            if pid in psutil.pids():
                # Kill watched job
                process = psutil.Process(pid)
                process.kill()
                st_dic = {'status': -1, 'ter': 0}
                baseDriver.multi_update(job_db, jid, st_dic)
            exit(0)
        except Exception, e:
            print e

if __name__ == "__main__":
    
    try:
        opts, args = getopt.getopt(sys.argv[1:], "j:p:", ["jid=", "pid="])
    except getopt.GetoptError, err:
        print str(err)
        sys.exit()
    
    if len(opts) == 2:
        for o, a in opts:
            if o in ("-j", "--jid"):
                jid = int(a)
            elif o in ("-p", "--pid"):
                pid = int(a)
    else:
        sys.exit()
    
    if jid and pid:
        schedule.every(10).seconds.do(terminate_cron)
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        sys.exit()

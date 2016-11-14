#!/usr/bin/env python
import baseDriver
import getopt
import psutil
import schedule
import sys
import time

jid = None
pid = None


def if_terminate():
    try:
        terminate_signal = baseDriver.get_field('ter', 'queue', 'id', str(jid))
        if terminate_signal:
            if pid in psutil.pids():
                # Kill watched job
                process = psutil.Process(pid)
                process.kill()
                st_dic = {'status': -1, 'ter': 0}
                baseDriver.multi_update('queue', jid, st_dic)
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
        schedule.every(10).seconds.do(if_terminate)
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        sys.exit()

#!/usr/bin/env python
import psutil, time, schedule, getopt, sys, baseDriver
from databaseDriver import conMySQL
jid=None;pid=None;

def ifTerminate():
    try:
        ifTer = baseDriver.getField('ter', 'queue', 'id', str(jid))
        if ifTer:
            if pid in psutil.pids():
                #Kill watched job
                proc = psutil.Process(pid)
                proc.kill()
                stDic = {'status':-1, 'ter':0}
                baseDriver.multiUpdate('queue', jid, stDic)
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
            if o in ("-j","--jid"):
                jid = int(a)
            elif o in ("-p", "--pid"):
                pid = int(a)
    else:
        sys.exit()
    
    if jid and pid:
        schedule.every(10).seconds.do(ifTerminate)
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        sys.exit()
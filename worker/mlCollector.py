#!/usr/local/bin python
#@todo
import subprocess, psutil, time, getopt, sys
from baseDriver import getConfig, writeAppend, getFolderSize, update
from os.path import join, getsize
from databaseDriver import conMySQL

memList = []
cpuList = []
readList = []
writeList = []

def getMem(pid):
    runningProc = psutil.Process(pid)
    #if runningProc.is_running() == True:
    mem = runningProc.memory_info()
    return mem[0]

def getCPU(pid):
    runningProc = psutil.Process(pid)
    cpu = runningProc.cpu_percent(interval=1)
    return cpu

def getIO(pid):
    runningProc = psutil.Process(pid)
    io = runningProc.io_counters()
    return io[2], io[3]

def createMachineLearningItem(stepHash, inputBytes, outputBytes, memUsage, cpuUsage):
    con, cursor = conMySQL()
    dynSQL = """INSERT INTO %s (`step`, `in`, `out`, `mem`, `cpu`) VALUES ('%s', '%s', '%s', '%s', '%s');"""	% (getConfig("datasets", "trainStore"), str(stepHash), str(inputBytes), str(outputBytes), str(memUsage), str(cpuUsage))
    try:
        cursor.execute(dynSQL)
        id = con.insert_id()
        con.commit()
    except Exception, e:
        print e
        return 0
    return id

def main():

    try:
        opts, args = getopt.getopt(sys.argv[1:], "n:p:j:", ["protocolStep=", "pid=", "jobid="])
    except getopt.GetoptError, err:
        print str(err) 
        sys.exit()
        
    if len(opts)==0:
        sys.exit()
        
    stepHash = ''; processId = 0; jobId = 0
    
    for o, a in opts:
        if o in ("-n","--protocolStep"):
            stepHash = a
        elif o in ("-p", "--pid"):
            processId = int(a)
        elif o in ("-j", "--jobid"):
            jobId = int(a)

    if stepHash != '' and processId != 0:       
        while True:

            if processId in psutil.pids():
                procInfo = psutil.Process(processId)

                if procInfo.is_running():
                    try:
                        memList.append(getMem(processId))
                        cpuList.append(getCPU(processId))
                        time.sleep(30)
                    except Exception, e:
                        print e
                        break
                else:
                    break
            else:
                break

        if len(memList) > 0:
            memUsage = max(memList)
        else:
            memUsage = -1
        if len(cpuList) > 2:
            samples = round(len(cpuList)*0.1)
            cpuList.sort(reverse=True)
            cpuUsage = sum(cpuList[0:samples])/samples
        elif len(cpuList) == 1:
            cpuUsage = cpuList[0]
        else:
            cpuUsage = -1
        update(getConfig('datasets', 'trainStore'), jobId, 'mem', memUsage)
        update(getConfig('datasets', 'trainStore'), jobId, 'cpu', cpuUsage)
    else:
        sys.exit()

if __name__ == '__main__':
    main()

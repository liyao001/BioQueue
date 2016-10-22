#!/usr/bin/env python
from databaseDriver import conMySQL, getResource, updateResource
import subprocess, checkPoint, HTMLParser, shlex, hashlib, time, os, baseDriver, re

con, cursor = conMySQL()
thisInputSize = 0
thisOutputSize = 0
cumulativeOutputSize = 0
traceId = 0
iniFile = ''

def getProtocol(proId):
    '''Get entire protocol and assign those constants'''
    html_parser = HTMLParser.HTMLParser()
    query = '''SELECT software, parameter, specify_output, hash FROM %s WHERE `parent`=%s ORDER BY id ASC;''' % (baseDriver.getConfig("datasets", "protocolDb"), proId)
    cursor.execute(query)
    tmp = cursor.fetchall()
    steps = [html_parser.unescape(str(step[0]).rstrip()+" "+str(step[1])) for step in tmp]
    outs = [str(step[2]) for step in tmp]
    hashes = [str(step[3]) for step in tmp]
    parseProtocolCST(steps)
    return steps, outs, hashes

def parseProtocolCST(steps):
    '''Replace constants in step'''
    from multiprocessing import cpu_count
    CONSTANT = {
        '{ThreadN}': cpu_count(),
    }

    for k, v in enumerate(steps):
        for key in CONSTANT.keys():
            if v.find(key) != -1:
                tmp = steps[k]
                steps[k] = steps[k].replace(key, str(CONSTANT[key]))

def getJob():
    '''Get job information from queue database'''
    '''
    dynSQL = """SELECT COUNT(*) FROM %s WHERE `status` > 0 or `status` = -2;"""%baseDriver.getConfig("datasets", "jobDb")
    cursor.execute(dynSQL)
    running = cursor.fetchone()
    con.commit()
    if int(running[0])!=0:
        return 0, 0, 0, 0, 0, 0, 0
    '''
    query = """SELECT `id`, `protocol`, `inputFile`, `parameter`, `run_dir`, `user_id`, `resume` FROM `%s` WHERE `status` = 0 ORDER BY `id` LIMIT 1;""" % baseDriver.getConfig("datasets", "jobDb")
    cursor.execute(query)
    res = cursor.fetchone()
    if res != None:
        id, protocol, inputFile, parameter, runDirctory, user, resume = res
        baseDriver.update(baseDriver.getConfig("datasets", "jobDb"), id, 'status', -2)#mark job
        return id, protocol, inputFile, parameter, runDirctory, user, int(resume)
    else:
        return 0, 0, 0, 0, 0, 0, 0

def insertSQL(sql):
    try:
        cursor.execute(sql)
        id = cursor.insert_id()
        con.commit()
    except Exception, e:
        print e
        return 0
    return id

def callProc(parameter, step, jobId, rund='', stepHash=''):
    global thisInputSize, thisOutputSize, cumulativeOutputSize, traceId, iniFile
    isoFile = 0
    learning = 0
    folderSizeBefore = 0
    try:
        trainingNum = getTrainingItems(stepHash)
        if rund != '':
            if trainingNum < 100:
                learning = 1
            if thisInputSize == 0:
                thisInputSize = baseDriver.getFolderSize(rund)
                if thisInputSize == 0 and step == 0:
                    thisInputSize = baseDriver.getRemoteSizeFactory(iniFile)
                    isoFile = 1
            else:
                thisInputSize = thisOutputSize #in fact this is the last output
            folderSizeBefore = baseDriver.getFolderSize(rund)
            
            if learning == 1:
                traceId = createMachineLearningItem(stepHash, thisInputSize)

            terProc = subprocess.Popen(["python", "procManeuver.py", "-p", str(os.getpid()), "-j", str(jobId)], shell=False, stdout = None, stderr = subprocess.STDOUT)
            status, cpuN, memN, diskN = checkPoint.checkOk2Go(jobId, stepHash, thisInputSize, trainingNum)
            while not status:
                time.sleep(13)
                status, cpuN, memN, diskN = checkPoint.checkOk2Go(jobId, stepHash, thisInputSize, trainingNum)
            proc = subprocess.Popen(parameter, shell=False, stdout = subprocess.PIPE, stderr = subprocess.PIPE, cwd=rund)
            if learning == 1 and stepHash != '':
                learnProc = subprocess.Popen(["python", "mlCollector.py", "-p", str(proc.pid), "-n", str(stepHash), "-j", str(traceId)], shell=False, stdout = None, stderr = subprocess.STDOUT)
        else:
            status, cpuN, memN, diskN = checkPoint.checkOk2Go(jobId, stepHash)
            while not status:
                time.sleep(13)
                status, cpuN, memN, diskN = checkPoint.checkOk2Go(jobId, stepHash)
            proc = subprocess.Popen(parameter, shell=False, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        baseDriver.update(baseDriver.getConfig("datasets", "jobDb"), jobId, 'status', step+1)
        stdout, stderr = proc.communicate()
        stdout += stderr
        baseDriver.recordJob(jobId, stdout)
        
        if rund != '':
            if isoFile == 1:
                thisInputSize = 0
                isoFile = 0
            thisOutputSize = baseDriver.getFolderSize(rund) - folderSizeBefore
            #cpuBf, memBf, diskBf = getResource()
            print '=='+str(jobId)+'=='+str(step)+'== diskN', diskN, 'outputSize', thisOutputSize
            updateResource(float(cpuN), float(memN), float(diskN)-thisOutputSize)
            cumulativeOutputSize += thisOutputSize
            if learning == 1:
                baseDriver.update(baseDriver.getConfig("datasets", "trainStore"), traceId, 'out', thisOutputSize)
        return proc.returncode
    except Exception, e:
        print 'Error caused by CPBQueue', e
        #baseDriver.update(baseDriver.getConfig("datasets", "jobDb"), jobId, 'status', -3)
        return 1

def createMachineLearningItem(stepHash, inputSize):
    dynSQL = """INSERT INTO %s (`step`, `in`) VALUES ('%s', '%s');""" % (baseDriver.getConfig("datasets", "trainStore"), stepHash, str(inputSize))
    try:
        cursor.execute(dynSQL)
        id = con.insert_id()
        con.commit()
    except Exception, e:
        print e
        return 0
    return id

def getTrainingItems(stepHash):
    dynSQL = """SELECT COUNT(*) FROM %s WHERE `step`='%s';""" % (baseDriver.getConfig("datasets", "trainStore"), stepHash)
    try:
        cursor.execute(dynSQL)
        trains = cursor.fetchone()
        con.commit()
        return trains[0]
    except Exception, e:
        print e
        return 0

def soParser(all):
    specialDict = {}
    for output in all:
        if output.find(';') != -1:
            options = output.split(';')
            options.remove('')
            for option in options:
                k, v = option.split('=')
                k.strip()
                v.strip()
                specialDict[k] = v
    return specialDict

def createUserFolder(uf, jf):
    try:
        if not os.path.exists(uf):
            os.mkdir(uf)
        if not os.path.exists(jf):
            os.mkdir(jf)
    except Exception, e:
        print e

def dynamicRun():
    global traceId, iniFile, cumulativeOutputSize
    outputSize = []; lastOutput = []; thisOutput = []; outputs = []; newFiles = []
    outDic = {}
    lastOutputS = ''
    
    jid, protocol, iniFile, indeedParameter, runf, userId, resume = getJob()
    
    if jid == 0 or protocol == 0 or iniFile == '':
        return 1
    
    resultStore = baseDriver.randSig()+str(jid)
    userFolder = os.path.join(runf, str(userId))
    runf = os.path.join(userFolder, resultStore)
    
    createUserFolder(userFolder, runf)
    #initSet = {'result': resultStore, 'pid':os.getpid()}
    #baseDriver.multiUpdate(baseDriver.getConfig("datasets", "jobDb"), jid, initSet)
    baseDriver.update(baseDriver.getConfig("datasets", "jobDb"), jid, 'result', resultStore)
    
    steps, specialOutput, hs = getProtocol(protocol)
    VARIABLE = {'firstFile': '{InitInput}', 
                'lastFile': '{LastOutput}',
                'allOutput': '{AllOutputBefore}',
                'jobId': '{job}',}
    #ip = soParser(indeedParameter)
    specialOutput.append(indeedParameter)
    so = soParser(specialOutput)
    rg = re.compile("\\{Output(\\d+)-(\\d+)\\}", re.IGNORECASE|re.DOTALL)
    
    lo = ''
    for k,v in enumerate(steps):
        #skip finished steps
        if k < resume:
            continue
        #load cached output
        if resume != -1:
            outDic = baseDriver.loadOutputDict(jid)

        for keyword in so.keys():
            steps[k] = steps[k].replace('{'+keyword+'}', so[keyword])

        steps[k] = steps[k].replace(VARIABLE['firstFile'], iniFile)
        steps[k] = steps[k].replace(VARIABLE['jobId'], str(jid))
        steps[k] = steps[k].replace(VARIABLE['lastFile'], lastOutputS)
        steps[k] = steps[k].replace(VARIABLE['allOutput'], ' '.join(outputs))
        
        for key, value in enumerate(newFiles):
            steps[k] = steps[k].replace('{LastOutput'+str(key)+'}', value)
            
        for outItem in re.findall(rg, steps[k]):
            if outDic.has_key(int(outItem[0])) and (int(outItem[1])-1) < len(outDic[int(outItem[0])]):
                steps[k] = steps[k].replace('{Output'+outItem[0]+'-'+outItem[1]+'}', outDic[int(outItem[0])][int(outItem[1])-1])
        par = shlex.shlex(steps[k])
        par.quotes='"'
        par.whitespace_split=True
        par.commenters=''
        parameters = list(par)
        lastOutput = os.listdir(runf)
        
        if runf:
            ret = callProc(parameters, k, jid, rund=runf, stepHash=hs[k])
        else:
            ret = callProc(parameters, k, jid)
        
        runningSet = {'resume':k, 'status': -2}
        baseDriver.multiUpdate(baseDriver.getConfig("datasets", "jobDb"), jid, runningSet)
        
        if ret != 0:
            print "Error when executing: "+steps[k]
            m = {'status':-3, 'pid':-1}
            baseDriver.multiUpdate(baseDriver.getConfig("datasets", "jobDb"), jid, m)
            baseDriver.delete(baseDriver.getConfig("datasets", "trainStore"), traceId)
            baseDriver.saveOutputDict(outDic, jid)
            return 2
        thisOutput = os.listdir(runf)
        newFiles = sorted(list(set(thisOutput).difference(set(lastOutput))))
        outputs.extend(newFiles)
        outDic[k+1] = newFiles
        lastOutputS = ' '.join(list(set(thisOutput).difference(set(lastOutput))))
    
    finalSize = baseDriver.getFolderSize(runf)
    updateResource(0, 0, cumulativeOutputSize-finalSize)
    if ret == 0:
        #mark as finished
        #m = {'status':-1, 'pid':-1}
        #baseDriver.multiUpdate(baseDriver.getConfig("datasets", "jobDb"), jid, m)
        baseDriver.update(baseDriver.getConfig("datasets", "jobDb"), jid, 'status', -1)
        baseDriver.delOutputDict(jid)
    else:
        # save output
        baseDriver.saveOutputDict(outDic, jid)
if __name__ == '__main__':
    dynamicRun()
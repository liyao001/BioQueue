#!/usb/bin/env python
from numpy import *
from databaseDriver import conMySQL, getResource, updateResource
from baseDriver import getConfig, getDiskFree, getCPUAvailable, getMemoUsageAvailable, randSig
from pandas import DataFrame
import pandas as pd
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

con, cursor = conMySQL()

def loadTrainFrame(stepHash):
    global con, cursor
    sql = """SELECT * FROM `%s` WHERE `step`='%s';"""%(getConfig("datasets", "trainStore"), stepHash)
    trainDataFrame = pd.read_sql_query(sql, con)
    trainDataFrame['cpu'] = trainDataFrame['cpu'].astype('float32')
    trainDataFrame['mem'] = trainDataFrame['mem'].astype('float32')
    trainDataFrame.fillna(trainDataFrame.mean())
    tmpX = list(trainDataFrame['in'])
    tmpOut = list(trainDataFrame['out'])
    tmpMem = list(trainDataFrame['mem'])
    tmpCPU = list(trainDataFrame['cpu'])
    allX = [[1.0, float(feat)] for feat in tmpX]
    outY = [float(label) for label in tmpOut]
    memY = [float(label) for label in tmpMem]
    cpuY = [float(label) for label in tmpCPU]
    return allX, outY, memY, cpuY

def standRegres(xArr, yArr):
    xMat = mat(xArr); yMat = mat(yArr).T
    xTx = xMat.T*xMat
    if linalg.det(xTx) == 0.0:
        print 'singular matrix'
        return
    ws = xTx.I * (xMat.T*yMat)
    return ws

def exportPlot(xArr, yArr, regCoefficient, xLabel, yLabel):
    fig = plt.figure()
    ax = fig.add_subplot(111)
    xMat = mat(xArr); yMat = mat(yArr)
    ax.scatter(xMat[:,1].flatten().A[0], yMat.T[:,0].flatten().A[0])
    xCopy=xMat.copy()
    xCopy.sort(0)
    yHat = xCopy*regCoefficient
    r = corrcoef(yHat.T, yMat)[0][1]
    plt.set_xlabel = xLabel    
    #fig.set_ylabel = yLabel
    ax.xaxis.set_label_text(xLabel)
    ax.yaxis.set_label_text(yLabel)
    ax.plot(xCopy[:, 1], yHat,label=yLabel)
    plt.legend()
    fileName = randSig()+'.png'
    plt.savefig(os.path.join(getConfig('ml', 'imgStore'), fileName), dpi=72)
    #plt.show()
    return r, fileName

def regSingleFeature(x, y, label, saveImg=1):
    rc = standRegres(x, y)
    if rc is not None:
        rc = rc.getA()
        if saveImg == 1:
            r, figFile = exportPlot(x, y, rc, 'Input Size', label)
        else:
            r = 0
            figFile = ''
        b = rc[0][0]
        a = rc[1][0]
        return a, b, r, figFile
    else:
        return 0, 0, 0, 0

def recordResult(stepHash, a, b, r, img, t):
    global con, cursor
    try:
        sql = """INSERT INTO `%s` (`stephash`, `a`, `b`, `r`, `img`, `type`) VALUES ('%s', %s, %s, %s, '%s', %s);""" % (getConfig('datasets', 'equation'), stepHash, a, b, r, img, t)
        cursor.execute(sql)
        con.commit()
    except Exception, e:
        print e
        return 0
    return 1

def regression(stepHash):
    x, out, mem, cpu = loadTrainFrame(stepHash)
    ao, bo, ro, io = regSingleFeature(x, out, 'Output Size')
    recordResult(stepHash, ao, bo, ro, io, 1)
    am, bm, rm, im = regSingleFeature(x, mem, 'Memory Usage')
    recordResult(stepHash, am, bm, rm, im, 2)
    ac, bc, rc, ic = regSingleFeature(x, cpu, 'CPU Usage')
    recordResult(stepHash, ac, bc, rc, ic, 3)
    return ao, bo, am, bm, ac, bc

def regressionNotSave(stepHash):
    x, out, mem, cpu = loadTrainFrame(stepHash)
    ao, bo, ro, io = regSingleFeature(x, out, 'Output Size', 0)
    if ao == bo and ao == 0:
        bo = average(out)
    am, bm, rm, im = regSingleFeature(x, mem, 'Memory Usage', 0)
    if am == bm and am == 0:
        bm = average(mem)
    ac, bc, rc, ic = regSingleFeature(x, cpu, 'CPU Usage', 0)
    if ac == bc and ac == 0:
        bc = average(cpu)
    return ao, bo, am, bm, ac, bc
    
def getTrainingItems(connection, cursor, stepHash):
    dynSQL = """SELECT COUNT(*) FROM %s WHERE `step`='%s';"""	% (getConfig("datasets", "trainStore"), stepHash)
    try:
        cursor.execute(dynSQL)
        trains = cursor.fetchone()
        connection.commit()
        return trains[0]
    except Exception, e:
        print e
        return 0

def checkOk2Go(jobid, step, inSize=-99999.0, trainingNum=0, runPath = '/'):
    con, cur = conMySQL()
    getEquationSQL = """SELECT `a`, `b`, `type` FROM %s WHERE `stephash`='%s';""" % (getConfig("datasets", "equation"), str(step))
    cur.execute(getEquationSQL)
    equations = cur.fetchall()
    if len(equations) > 0 and inSize != -99999.0:
        predNeed = {}
        cpuT, memT, diskT = getResource()
        cpuT = float(cpuT)
        memT = float(memT)
        diskT = float(diskT)
        for equation in equations:
            a = float(equation[0])
            b = float(equation[1])
            t = equation[2]
            needed = (a * inSize + b)*0.95
            if t == '1':
                predNeed['disk'] = needed
                if needed > getDiskFree(runPath) or needed > diskT:
                    return 0, 0, 0, 0
            elif t == '2':
                predNeed['mem'] = needed
                if needed > getMemoUsageAvailable() or needed > memT:
                    return 0, 0, 0, 0
            elif t == '3':
                predNeed['cpu'] = needed
                if needed > getCPUAvailable() or needed > cpuT:
                    return 0, 0, 0, 0

        print '=='+str(jobid)+'=='+str(step)+'==', 'cpu: pred', predNeed['cpu'], 'getCPU', getCPUAvailable(), 'cpuPool', cpuT, 'mem: pred', predNeed['mem'], 'getMem', getMemoUsageAvailable(), 'memPool', memT, 'disk: pred', predNeed['disk'], 'getDisk', getDiskFree(runPath), 'diskPool', diskT
        if updateResource(-1*predNeed['cpu'], -1*predNeed['mem'], -1*predNeed['disk']):
            return 1, predNeed['cpu'], predNeed['mem'], predNeed['disk']
        else:
            print '=='+str(jobid)+'=='+str(step)+'==recheck reject=='
            return 0, predNeed['cpu'], predNeed['mem'], predNeed['disk']
    else:
        #trainingNum = getTrainingItems(con, cur, step)
        if trainingNum < 10:
        #Not ready for machine learning
            getRunningSQL = """SELECT COUNT(*) FROM %s WHERE `status`>0 AND `id` != %s;""" % (getConfig("datasets", "jobDb"), jobid)
            cur.execute(getRunningSQL)
            running = cur.fetchone()
            if running:
                if running[0] == 0:
                    return 1, 0, 0, 0
                else:
                    return 0, 0, 0, 0
            else:
                return 1, 0, 0, 0
        elif trainingNum < 100:
            cpuT, memT, diskT = getResource()
            cpuT = float(cpuT)
            memT = float(memT)
            diskT = float(diskT)
            ao, bo, am, bm, ac, bc = regressionNotSave(step)
            diskNeeded = int((ao*inSize+bo)*0.9)
            memNeeded = int((am*inSize+bm)*0.9)
            cpuNeeded = int((ac*inSize+bc)*0.9)
            print '=='+str(jobid)+'=='+str(step)+'==', 'cpu: pred', cpuNeeded, 'getCPU', getCPUAvailable(), 'cpuPool', cpuT, 'mem: pred', memNeeded, 'getMem', getMemoUsageAvailable(), 'memPool', memT, 'disk: pred', diskNeeded, 'getDisk', getDiskFree(runPath), 'diskPool', diskT
            if diskNeeded > getDiskFree(runPath) or diskNeeded > diskT:
                return 0, cpuNeeded, memNeeded, diskNeeded
            if memNeeded > getMemoUsageAvailable() or memNeeded > memT:
                return 0, cpuNeeded, memNeeded, diskNeeded
            if cpuNeeded > getCPUAvailable() or cpuNeeded > cpuT:
                return 0, cpuNeeded, memNeeded, diskNeeded
            
            if updateResource(-1*cpuNeeded, -1*memNeeded, -1*diskNeeded):
                return 1, cpuNeeded, memNeeded, diskNeeded
            else:
                return 0, cpuNeeded, memNeeded, diskNeeded
        else:
            cpuT, memT, diskT = getResource()
            cpuT = float(cpuT)
            memT = float(memT)
            diskT = float(diskT)
            ao, bo, am, bm, ac, bc = regression(step)
            diskNeeded = int((ao*inSize+bo)*0.9)
            memNeeded = int((am*inSize+bm)*0.9)
            cpuNeeded = int((ac*inSize+bc)*0.9)
            print '=='+str(jobid)+'=='+str(step)+'==', 'cpu: pred', cpuNeeded, 'getCPU', getCPUAvailable(), 'cpuPool', cpuT, 'mem: pred', memNeeded, 'getMem', getMemoUsageAvailable(), 'memPool', memT, 'disk: pred', diskNeeded, 'getDisk', getDiskFree(runPath), 'diskPool', diskT
            
            if diskNeeded > getDiskFree(runPath) or diskNeeded > diskT:
                return 0, cpuNeeded, memNeeded, diskNeeded
            if memNeeded > getMemoUsageAvailable() or memNeeded > memT:
                return 0, cpuNeeded, memNeeded, diskNeeded
            if cpuNeeded > getCPUAvailable() or cpuNeeded > cpuT:
                return 0, cpuNeeded, memNeeded, diskNeeded

            if updateResource(-1*cpuNeeded, -1*memNeeded, -1*diskNeeded):
                return 1, cpuNeeded, memNeeded, diskNeeded
            else:
                return 0, cpuNeeded, memNeeded, diskNeeded
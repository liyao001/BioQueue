#!/usr/bin/env python

import ConfigParser
import os
import psutil
from multiprocessing import cpu_count

def getConfig(section, key):
    config = ConfigParser.ConfigParser()
    path = os.path.split(os.path.realpath(__file__))[0] + '/config.conf'
    config.read(path)
    return config.get(section, key)

def randSig():
    import datetime, hashlib
    sig = hashlib.md5()
    sig.update(str(datetime.datetime.now()))
    return sig.hexdigest()

def recordJob(jobId, logs):
    file = os.path.join(getConfig("env", "log"), str(jobId))
    fo = open(file, "a")
    if isinstance(logs, list):
        fo.writelines(logs)
    else:
        fo.write(logs)
    fo.close()

def getCPUPercent():
    return psutil.cpu_percent(interval=1)

def getCPUAvailable():
    return (cpu_count() * (100 - getCPUPercent()))

def getMemoUsageAvailable():
    mem = psutil.virtual_memory()
    return list(mem)[1]

def getDiskUsed(path='/'):
    du = psutil.disk_usage(path)
    return list(du)[1]

def getDiskFree(path='/'):
    du = psutil.disk_usage(path)
    return list(du)[2]

def getInitResource():
    cpu = cpu_count() * 100
    mem = list(psutil.virtual_memory())[0]
    disk = list(psutil.disk_usage(getConfig("ml", "trainStore")))[0]
    return cpu, mem, disk

def writeAppend(fileName, lines):
    file = open(fileName, 'a')
    file.writelines(lines)
    file.close()

def getFolderSize(folder):
    folderSize = 0
    for (path, dirs, files) in os.walk(folder):
        for file in files:
            fileName = os.path.join(path, file)
            folderSize += os.path.getsize(fileName)
    
    return folderSize

def conMySQL():
    '''Support for MySQL database(rely on MySQLdb)
    h=host, u=user, p=password, db=database, port=database port, local=local_infile'''
    import MySQLdb
    try:
        connection = MySQLdb.connect(host=getConfig("db", "host"), user=getConfig("db", "user"), passwd=getConfig("db", "password"), db=getConfig("db", "db_name"), port=int(getConfig("db", "port")), local_infile=1)
        if buffer == 1:
            cursor = connection.cursor()
            #cursor = connection.cursor(buffered=True)
        else:
            cursor = connection.cursor()
            
    except Exception, e:
        print e
    return connection, cursor

def update(table, jid, field, value):
    connection, cursor = conMySQL()
    query = """UPDATE `%s` SET `%s` = '%s' WHERE `id` = %s;""" % (table, field, value, jid)
    try:
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception, e:
        print e
        return 0
    return 1

def multiUpdate(table, jid, m):
    connection, cursor = conMySQL()
    res = []
    for key in m:
        res.append("`%s` = '%s'" % (key, m[key]))
    dynSql = ', '.join(res)
    query = """UPDATE `%s` SET %s WHERE `id` = %s;""" % (table, dynSql, jid)
    try:
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception, e:
        print e
        return 0
    return 1

def getField(field, table, key, value):
    try:
        connection, cursor = conMySQL()
        query = """SELECT `%s` FROM `%s` WHERE `%s` = '%s';"""%(field, table, key, value)
        cursor.execute(query)
        res = cursor.fetchone()
        connection.close()
        if res != None:
            return res[0]
        else:
            return None
    except Exception, e:
        print e

def delete(table, id):
    connection, cursor = conMySQL()
    query = """DELETE FROM `%s` WHERE `id` = '%s';""" % (table, id)
    try:
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception, e:
        print e
        return 0
    return 1

def getPath(url):
    import re
    regSite = re.compile(r"^(?:(?:http|https|ftp):\/\/)?([\w\-_]+(?:\.[\w\-_]+)+)", re.IGNORECASE)
    head = str(url).split(":")[0]
    try:
        port = str(url).split(':')[2].split('/')[0]
    except:
        port = ""
    matched = regSite.match(url)
    
    if regSite.match(url):
        hostName = regSite.match(url).group(1)
        if len(port)>1:
            hostName = hostName + ':' + port
        path = str(url).split(hostName)[1]        
    else:
        head = "loclf"
        hostName = "local"
        path = url
    return (head, hostName, path)

def ftpSize(hostName, path):
    from ftplib import FTP
    try:
        ftp = FTP(hostName)
    except:
        print 'FTP error!'
        return -1
    try:
        ftp.login()
        ftp.voidcmd('TYPE I')
        size = ftp.size(path)
        ftp.quit()
    except:
        print 'can not login anonymously or connect error or function exec error!'
        return 0
    return size

def httpSize(hostName, path):
    import httplib
    try:
        conn = httplib.HTTPConnection(hostName)
        conn.request("GET", path)
        resp = conn.getresponse()
    except:
        print 'connect error!'
        return 0
    return int(resp.getheader("content-length"))

def getRemoteSize(head, hostName, path):
    size = -1
    if head == 'ftp':
        size = ftpSize(hostName, path)
    if head == 'http' or head == 'https':
        size = httpSize(hostName, path)
    if head == 'loclf':
        if os.path.exists(path):
            size = os.path.getsize(path)
        else:
            size = 0
    return size

def getRemoteSizeFactory(url):
    url = url.strip()
    if len(url) <= 4:
        exit(-1)
    urlArr = url.split(" ")
    totalSize = 0
    for url in urlArr:
        head, hostName, path = getPath(url)
        if len(hostName) <= 4 or len(path) < 1:
            exit(-1)
        totalSize += getRemoteSize(head, hostName, path)
    return totalSize

def saveOutputDict(dic, job):
    import pickle
    fp = os.path.join(getConfig('env', 'outputs'), str(job))
    ff = open(fp, mode='wb')
    pickle.dump(dic, ff)
    ff.close()
    
def loadOutputDict(job):
    import pickle
    fp = os.path.join(getConfig('env', 'outputs'), str(job))
    if os.path.exists(fp):
        try:
            ff = open(fp, mode='rb')
            dic = pickle.load(ff)
            ff.close()
            return dic
        except Exception, e:
            print e
            return {}
    else:
        return {}

def delOutputDict(job):
    fp = os.path.join(getConfig('env', 'outputs'), str(job))
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except Exception, e:
            print e
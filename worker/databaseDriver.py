#!/usr/bin/env python
from baseDriver import getConfig
import time
def conSQLite(db):
    '''Support for sqlite database'''
    try:
        import sqlite3
    except Exception, e:
        print e
        return 0

    if (db == 'memory'):
        con = sqlite3.connect(':memory:')
    else:
        try:
            con = sqlite3.connect(db)
        except:
            return 0, 0

    cursor = con.cursor()
    return con, cursor

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
        return connection, cursor        
    except Exception, e:
        print e
        return None, None

def mysqlConnection():
    '''Support for MySQL(load configuration from local file)'''
    from baseDriver import getConfig
    return conMySQL(h=getConfig("db", "host"), u=getConfig("db", "user"), p=getConfig("db", "password"), db=getConfig("db", "db_name"), port=int(getConfig("db", "port")), local=1)

def initResource(cpu, mem, disk):
    setResource(cpu, mem, disk)
    
def getResource():
    conn, cursor = conMySQL()
    sql = """SELECT `cpu`, `mem`, `disk` FROM `resource` WHERE `own`='sys' LIMIT 1;"""
    resource = cursor.execute(sql)
    sysResource = cursor.fetchone()
    if sysResource:
        cpu, mem, disk = sysResource
    else:
        cpu = mem = disk = 0
    conn.close()
    return cpu, mem, disk

def setResource(cpu, mem, disk):
    tryTimes = 0
    flag = 0
    while tryTimes < 5:
        try:
            conn, cursor = conMySQL()
            sql = """UPDATE `resource` SET `cpu` = %s, `mem` = %s, `disk` = %s WHERE `own` = 'sys';""" % (cpu, mem, int(disk))
            cursor.execute(sql)
            conn.commit()
            conn.close()
            flag = 1
            break
        except Exception, e:
            print e, 'Try times:', tryTimes
            time.sleep(1)
            tryTimes += 1
    return flag

def updateResourceWithoutCheck(cpu, mem, disk):
    tryTimes = 0
    flag = 0
    while tryTimes < 5:
        try:
            conn, cursor = conMySQL()
            sql = """UPDATE `resource` SET `cpu` = `cpu` + %s, `mem` = `mem` + %s, `disk` = `disk` + %s WHERE `own` = 'sys';""" % (cpu, mem, disk)
            cursor.execute(sql)
            conn.commit()
            conn.close()
            flag = 1
            break
        except Exception, e:
            print e, 'Try times:', tryTimes
            time.sleep(1)
            tryTimes += 1
    return flag

def updateResource(cpu, mem, disk, giveBack=0):
    flag = 1
    conn, cursor = conMySQL()
    sql = """UPDATE `resource` SET `cpu` = `cpu` + %s, `mem` = `mem` + %s, `disk` = `disk` + %s WHERE `own` = 'sys';""" % (cpu, mem, int(disk))
    cursor.execute(sql)
    conn.commit()
    if not giveBack:
        sql = """SELECT `cpu`, `mem`, `disk` FROM `resource` WHERE `own`='sys' LIMIT 1;"""
        cursor.execute(sql)
        sysResource = cursor.fetchone()
        if sysResource:
            cpuL, memL, diskL = sysResource
            cpuL = float(cpuL)
            memL = float(memL)
            diskL = float(diskL)
            print 'new DISK', diskL
        else:
            cpuL = -1; memL = -1; diskL = -1
        if cpuL < 0 or memL < 0 or diskL < 0: #rollback
            sql = """UPDATE `resource` SET `cpu` = `cpu` - %s, `mem` = `mem` - %s, `disk` = `disk` - %s WHERE `own` = 'sys';""" % (cpu, mem, disk)
            cursor.execute(sql)
            conn.commit()
            flag = 0
    conn.close()
    return flag
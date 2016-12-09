#!/usr/bin/env python
from baseDriver import get_all_config
import time
settings = get_all_config()


def con_sqlite(db):
    """Support for sqlite database"""
    try:
        import sqlite3
    except Exception, e:
        print e
        return 0

    if db == 'memory':
        con = sqlite3.connect(':memory:')
    else:
        try:
            con = sqlite3.connect(db)
        except Exception, e:
            print e
            return 0, 0

    cursor = con.cursor()
    return con, cursor


def con_mysql():
    """Support for MySQL database(rely on MySQLdb)
    h=host, u=user, p=password, db=database, port=database port, local=local_infile"""
    import MySQLdb
    try:
        connection = MySQLdb.connect(host=settings['db']['host'], user=settings['db']['user'], passwd=settings['db']['password'], db=settings['db']['db_name'], port=int(settings['db']['port']), local_infile=1)
        if buffer == 1:
            # cursor = connection.cursor(buffered=True)
            cursor = connection.cursor(buffered=True)
        else:
            cursor = connection.cursor()
        return connection, cursor        
    except Exception, e:
        print e
        return None, None


def mysql_connection():
    """Support for MySQL(load configuration from local file)"""
    return con_mysql(h=settings['db']['host'], u=settings['db']['user'], p=settings['db']['password'],
                     db=settings['db']['db_name'], port=int(settings['db']['port']), local=1)


def init_resource(cpu, mem, disk):
    set_resource(cpu, mem, disk)


def get_resource():
    conn, cursor = con_mysql()
    sql = """SELECT `cpu`, `mem`, `disk` FROM `%s` WHERE `own`='sys' LIMIT 1;""" % settings['datasets']['resource']
    resource = cursor.execute(sql)
    sys_resource = cursor.fetchone()
    if sys_resource:
        cpu, mem, disk = sys_resource
    else:
        cpu = mem = disk = 0
    conn.close()
    return cpu, mem, disk


def set_resource(cpu, mem, disk):
    try_times = 0
    flag = 0
    while try_times < 5:
        try:
            conn, cursor = con_mysql()
            sql = """UPDATE `%s` SET `cpu` = %s, `mem` = %s, `disk` = %s WHERE `own` = 'sys';""" \
                  % (settings['datasets']['resource'], cpu, mem, int(disk))
            cursor.execute(sql)
            conn.commit()
            conn.close()
            flag = 1
            break
        except Exception, e:
            print e, 'Try times:', try_times
            time.sleep(1)
            try_times += 1
    return flag


def update_resource_without_check(cpu, mem, disk):
    try_times = 0
    flag = 0
    while try_times < 5:
        try:
            conn, cursor = con_mysql()
            sql = """UPDATE `%s` SET `cpu` = `cpu` + %s, `mem` = `mem` + %s, `disk` = `disk` + %s WHERE `own` = 'sys';""" % (settings['datasets']['resource'], cpu, mem, disk)
            cursor.execute(sql)
            conn.commit()
            conn.close()
            flag = 1
            break
        except Exception, e:
            print e, 'Try times:', try_times
            time.sleep(1)
            try_times += 1
    return flag


def update_resource(cpu, mem, disk, give_back=0):
    try:
        flag = 1
        conn, cursor = con_mysql()
        sql = """UPDATE `%s` SET `cpu` = `cpu` + %s, `mem` = `mem` + %s, `disk` = `disk` + %s WHERE `own` = 'sys';""" \
              % (settings['datasets']['resource'], cpu, mem, int(disk))
        cursor.execute(sql)
        conn.commit()
        if not give_back:
            sql = """SELECT `cpu`, `mem`, `disk` FROM `%s` WHERE `own`='sys' LIMIT 1;""" % settings['datasets']['resource']
            cursor.execute(sql)
            sys_resource = cursor.fetchone()
            if sys_resource:
                cpu_max_pool, memory_max_pool, disk_max_pool = sys_resource
                cpu_max_pool = float(cpu_max_pool)
                memory_max_pool = float(memory_max_pool)
                disk_max_pool = float(disk_max_pool)
                print 'new DISK', disk_max_pool
            else:
                cpu_max_pool = -1
                memory_max_pool = -1
                disk_max_pool = -1
            if cpu_max_pool < 0 or memory_max_pool < 0 or disk_max_pool < 0:
                # rollback
                sql = """UPDATE `%s` SET `cpu` = `cpu` - %s, `mem` = `mem` - %s, `disk` = `disk` - %s WHERE `own` = 'sys';""" \
                      % (settings['datasets']['resource'], cpu, mem, disk)
                cursor.execute(sql)
                conn.commit()
                flag = 0
        conn.close()
        return flag
    except Exception, e:
        print e
        return 1

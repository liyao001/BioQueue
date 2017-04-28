#!/usr/bin/env python

import ConfigParser
import os
import psutil
from multiprocessing import cpu_count


def config_init():
    config = ConfigParser.ConfigParser()
    path = os.path.split(os.path.realpath(__file__))[0] + '/config.conf'
    config.read(path)
    return config


def get_all_config():
    config = config_init()
    configurations = {}
    for section in config.sections():
        tmp = config.items(section)
        opts = dict()
        for opt in tmp:
            opts[opt[0]] = opt[1]
        configurations[section] = opts
    return configurations


def get_config(section, key):
    try:
        config = config_init()
        return config.get(section, key)
    except:
        return None


def set_config(section, key, value):
    config = config_init()
    config.set(section, key, value)
    config.write(open(os.path.split(os.path.realpath(__file__))[0] + '/config.conf', "w"))


def rand_sig():
    import datetime
    import hashlib
    sig = hashlib.md5()
    sig.update(str(datetime.datetime.now()))
    return sig.hexdigest()


def record_job(job_id, logs):
    file_name = os.path.join(get_config("env", "log"), str(job_id))
    fo = open(file_name, "a")
    if isinstance(logs, list):
        fo.writelines(logs)
    else:
        fo.write(logs)
    fo.close()


def get_cpu_percent():
    return psutil.cpu_percent(interval=1)


def get_cpu_available():
    return cpu_count() * (100 - get_cpu_percent())


def get_memo_usage_available():
    mem = psutil.virtual_memory()
    return list(mem)[1]


def get_disk_used(path='/'):
    du = psutil.disk_usage(path)
    return list(du)[1]


def get_disk_free(path='/'):
    du = psutil.disk_usage(path)
    return list(du)[2]


def get_init_resource():
    cpu = cpu_count() * 100
    mem = list(psutil.virtual_memory())[0]
    disk = list(psutil.disk_usage(get_config("env", "workspace")))[0]
    return cpu, mem, disk


def write_append(file_name, lines):
    to_write = open(file_name, 'a')
    to_write.writelines(lines)
    to_write.close()


def get_folder_size(folder):
    folder_size = 0
    for (path, dirs, files) in os.walk(folder):
        for fn in files:
            file_name = os.path.join(path, fn)
            folder_size += os.path.getsize(file_name)
    
    return folder_size


def con_mysql():
    """Support for MySQL database(rely on MySQLdb)
    h=host, u=user, p=password, db=database, port=database port, local=local_infile"""
    import MySQLdb
    try:
        connection = MySQLdb.connect(host=get_config("db", "host"), user=get_config("db", "user"),
                                     passwd=get_config("db", "password"), db=get_config("db", "db_name"),
                                     port=int(get_config("db", "port")), local_infile=1)
        if buffer == 1:
            cursor = connection.cursor(buffer=True)
        else:
            cursor = connection.cursor()
            
    except Exception, e:
        print e
    return connection, cursor


def update(table, jid, field, value):
    query = """UPDATE `%s` SET `%s` = '%s' WHERE `id` = %s;""" % (table, field, value, jid)
    try:
        connection, cursor = con_mysql()
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception, e:
        print e
        return 0
    return 1


def multi_update(table, jid, m):
    res = []
    for key in m:
        res.append("`%s` = '%s'" % (key, m[key]))
    dyn_sql = ', '.join(res)
    query = """UPDATE `%s` SET %s WHERE `id` = %s;""" % (table, dyn_sql, jid)
    try:
        connection, cursor = con_mysql()
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception, e:
        print e
        return 0
    return 1


def get_field(field, table, key, value):
    try:
        connection, cursor = con_mysql()
        query = """SELECT `%s` FROM `%s` WHERE `%s` = '%s';""" % (field, table, key, value)
        cursor.execute(query)
        res = cursor.fetchone()
        connection.close()
        if res is not None:
            return res[0]
        else:
            return None
    except Exception, e:
        print e


def delete(table, record_id):
    query = """DELETE FROM `%s` WHERE `id` = '%s';""" % (table, record_id)
    try:
        connection, cursor = con_mysql()
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception, e:
        print e
        return 0
    return 1


def get_path(url):
    import re
    reg_site = re.compile(r"^(?:(?:http|https|ftp):\/\/)?([\w\-_]+(?:\.[\w\-_]+)+)", re.IGNORECASE)
    head = str(url).split(":")[0]
    try:
        port = str(url).split(':')[2].split('/')[0]
    except Exception, e:
        port = ""
    reg_site.match(url)
    
    if reg_site.match(url):
        host_name = reg_site.match(url).group(1)
        if len(port) > 1:
            host_name = host_name + ':' + port
        path = str(url).split(host_name)[1]
    else:
        head = "loclf"
        host_name = "local"
        path = url
    return head, host_name, path


def ftp_size(host_name, path):
    from ftplib import FTP
    try:
        ftp = FTP(host_name)
    except Exception, e:
        print e
        return -1
    try:
        ftp.login()
        ftp.voidcmd('TYPE I')
        size = ftp.size(path)
        ftp.quit()
    except Exception, e:
        print e
        return 0
    return size


def http_size(host_name, path):
    import httplib
    try:
        conn = httplib.HTTPConnection(host_name, timeout=3)
        conn.request("GET", path)
        resp = conn.getresponse()
        return int(resp.getheader("content-length"))
    except Exception, e:
        print e
        return 0


def get_remote_size(head, host_name, path):
    size = -1
    if head == 'ftp':
        size = ftp_size(host_name, path)
    if head == 'http' or head == 'https':
        size = http_size(host_name, path)
    if head == 'loclf':
        if os.path.exists(path):
            size = os.path.getsize(path)
        else:
            size = 0
    return size


def get_bioqueue_version():
    """
    Get BioQueue Version
    :return: string, version
    """
    import os
    version = ''
    version_file = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/version'
    with open(version_file) as version_file_handle:
        version = version_file_handle.read()
    return version


def get_remote_size_factory(url):
    url = url.strip()
    if len(url) <= 4:
        return 0
    url_arr = url.split(" ")
    total_size = 0
    for url in url_arr:
        head, host_name, path = get_path(url)
        if len(host_name) <= 4 or len(path) < 1:
            return 0
        total_size += get_remote_size(head, host_name, path)
    return total_size


def save_output_dict(dic, job):
    import pickle
    fp = os.path.join(get_config('env', 'outputs'), 'output_' + str(job))
    ff = open(fp, mode='wb')
    pickle.dump(dic, ff)
    ff.close()


def load_output_dict(job):
    import pickle
    fp = os.path.join(get_config('env', 'outputs'), 'output_' + str(job))
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


def del_output_dict(job):
    fp = os.path.join(get_config('env', 'outputs'), str(job))
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except Exception, e:
            print e


def build_upload_file_path(user_folder, file_name):
    upload_path = os.path.join(user_folder, 'uploads')
    file_path = os.path.join(upload_path, file_name)
    if os.path.exists(file_path):
        return file_path
    else:
        return ''


def get_user_folder_size(user):
    kb_to_mb = 1073741824
    user_path = os.path.join(get_config('env', 'workspace'), str(user))
    return round(get_folder_size(user_path)/kb_to_mb)


def get_folder_content(folder_path):
    import os
    folder_content = []
    for root, dirs, files in os.walk(folder_path):
        for file_name in files:
            file_full_path = os.path.join(root, file_name)
            folder_content.append(file_full_path)
    return folder_content

#!/usr/bin/env python
from __future__ import print_function

try:
    from ConfigParser import ConfigParser
except ImportError:
    from configparser import ConfigParser

import os
import psutil
from multiprocessing import cpu_count


def config_init(const = 0):
    """
    Initial configuration file
    :param const: int, 0 means load user's conf, 1 means load bioqueue's conf
    :return:
    """
    config = ConfigParser()
    if const:
        path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/config/bioqueue.conf'
    else:
        path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/config/custom.conf'
    config.read(path)
    return config


def get_all_config(const = 0):
    config = config_init(const)
    configurations = {}
    for section in config.sections():
        tmp = config.items(section)
        opts = dict()
        for opt in tmp:
            opts[opt[0]] = opt[1]
        configurations[section] = opts
    return configurations


def get_config(section, key, const = 0):
    try:
        config = config_init(const)
        return config.get(section, key)
    except:
        return None


def set_config(section, key, value, const = 0):
    config = config_init(const)
    config.set(section, key, value)
    if const:
        file_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/config/bioqueue.conf'
    else:
        file_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/config/custom.conf'

    config.write(open(file_path, "w"))


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
    psy_mem = psutil.virtual_memory()
    vrt_mem = psutil.swap_memory()
    return psy_mem.available, vrt_mem.free + psy_mem.available


def get_disk_used(path='/'):
    du = psutil.disk_usage(path)
    return list(du)[1]


def get_disk_free(path='/'):
    du = psutil.disk_usage(path)
    return list(du)[2]


def get_init_resource():
    cpu = cpu_count() * 100
    # mem = list(psutil.virtual_memory())[0]
    psy_mem = psutil.virtual_memory()
    vrt_mem = psutil.swap_memory()
    disk = list(psutil.disk_usage(get_config("env", "workspace")))[0]
    return cpu, psy_mem.total, disk, vrt_mem.total + psy_mem.total


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
            
    except Exception as e:
        print(e)
    return connection, cursor


def update(table, jid, field, value):
    query = """UPDATE `%s` SET `%s` = '%s' WHERE `id` = %s;""" % (table, field, value, jid)
    try:
        connection, cursor = con_mysql()
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception as e:
        print(e)
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
    except Exception as e:
        print(e)
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
    except Exception as e:
        print(e)


def delete(table, record_id):
    query = """DELETE FROM `%s` WHERE `id` = '%s';""" % (table, record_id)
    try:
        connection, cursor = con_mysql()
        cursor.execute(query)
        connection.commit()
        connection.close()
    except Exception as e:
        print(e)
        return 0
    return 1


def get_path(url):
    import re
    reg_site = re.compile(r"^(?:(?:http|https|ftp):\/\/)?([\w\-_]+(?:\.[\w\-_]+)+)", re.IGNORECASE)
    head = str(url).split(":")[0]
    try:
        port = str(url).split(':')[2].split('/')[0]
    except Exception as e:
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
    except Exception as e:
        print(e)
        return -1
    try:
        ftp.login()
        ftp.voidcmd('TYPE I')
        size = ftp.size(path)
        ftp.quit()
    except Exception as e:
        print(e)
        return 0
    return size


def http_size(host_name, path):
    try:
        from httplib import HTTPConnection
    except ImportError:
        from http.client import HTTPConnection
    try:
        conn = HTTPConnection(host_name, timeout=3)
        conn.request("GET", path)
        resp = conn.getresponse()
        return int(resp.getheader("content-length"))
    except Exception as e:
        print(e)
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
    try:
        import pickle
        fp = os.path.join(get_config('env', 'outputs'), 'output_' + str(job))
        ff = open(fp, mode='wb')
        pickle.dump(dic, ff)
        ff.close()
    except:
        pass


def load_output_dict(job):
    import pickle
    fp = os.path.join(get_config('env', 'outputs'), 'output_' + str(job))
    if os.path.exists(fp):
        try:
            ff = open(fp, mode='rb')
            dic = pickle.load(ff)
            ff.close()
            return dic
        except Exception as e:
            print(e)
            return {}
    else:
        return {}


def del_output_dict(job):
    fp = os.path.join(get_config('env', 'outputs'), str(job))
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except Exception as e:
            print(e)


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


def is_text(s, threshold=0.3):
    """
    Determine whether a certain string is text or arbitrary bytes.
    This is derived from Python Cookbook
    :param s: string, input string
    :param threshold: float, threshold for the max proportion in a string which can be null translates
    :return: 
    """
    import string
    from __future__ import division
    text_characters = "".join(map(chr, range(32, 127)))+"\n\r\t\b"
    _null_trans = string.maketrans("", "")
    if "\0" in s:
        return False
    if not s:
        return True
    t = s.translate(_null_trans, text_characters)
    return len(t)/len(s) <= threshold


def is_text_file(filename, block_size=512):
    """
    Determine whether a file is a text file or binary file.
    :param filename: string, path to the file
    :param block_size: int
    :return: bool
    """
    return is_text(open(filename).read(block_size))


def get_job_log(file_path):
    """
    Get job log
    :param file_path: string
    :return: string, If size of the file is less than 1MB, it will return the last 100 lines, or it will return the last 10 KB.
    """
    _1_mb_in_bytes = 1024000
    try:
        if is_text_file(file_path):
            with open(file_path, 'r') as file_handler:
                if os.path.getsize(file_path) > _1_mb_in_bytes:
                    off = -10240
                    file_handler.seek(off, 2)
                    log = file_handler.readlines()
                    log.reverse()
                else:
                    log = file_handler.readlines()
                    log.reverse()
                    len_log = len(log)
                    read_lines = 100 if len_log > 100 else len_log
                    log = log[:read_lines]
            log_content = '<br />'.join(log)
            return log_content
        else:
            return 'This is a binary file.'
    except Exception as e:
        print(e)
        return ''

#!/usr/bin/env python
import os
import sys
from multiprocessing import cpu_count
from getpass import getpass
import ConfigParser
byte_to_gigabyte = 1073741824


def set_config(section, key, value):
    config = ConfigParser.ConfigParser()
    path = os.path.split(os.path.realpath(__file__))[0] + '/worker/config.conf'
    config.read(path)
    config.set(section, key, value)
    config.write(open(os.path.split(os.path.realpath(__file__))[0] + '/worker/config.conf', "w"))


def get_random_secret_key():
    import random
    import hashlib
    import time
    try:
        random = random.SystemRandom()
        using_sysrandom = True
    except NotImplementedError:
        import warnings
        warnings.warn('A secure pseudo-random number generator is not available '
                      'on your system. Falling back to Mersenne Twister.')
        using_sysrandom = False

    chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'
    if not using_sysrandom:
        random.seed(
            hashlib.sha256(
                ("%s%s%s" % (
                    random.getstate(),
                    time.time(),
                    'BioQueue')).encode('utf-8')
            ).digest())
    return ''.join(random.choice(chars) for i in range(50))


def setup():
    workspace_path = os.path.split(os.path.realpath(__file__))[0] + '/workspace'
    while not os.path.exists(workspace_path):
        try:
            os.makedirs(workspace_path)
            break
        except Exception, e:
            print 'The path you input doesn\'t exist! Please reassign it.', e
            workspace_path = raw_input('Path of workspace: ')

    print '===================================================='
    print 'Installing dependent python packages, please wait...'
    print '===================================================='

    pip_import_path = os.path.split(os.path.realpath(__file__))[0] + '/deploy/prerequisites.txt'
    if os.system('pip install -r %s' % pip_import_path):
        print '====================================================='
        print '|Fetal error occured when installing python packages|'
        print '|Installation will be terminated now                |'
        print '====================================================='
        sys.exit(1)

    log_path = os.path.join(workspace_path, 'logs')
    output_path = os.path.join(workspace_path, 'outputs')
    train_path = os.path.join(workspace_path, 'training')
    upload_path = os.path.join(workspace_path, 'batch_job')
    try:
        os.mkdir(log_path)
        os.mkdir(output_path)
        os.mkdir(train_path)
        os.mkdir(upload_path)
    except Exception, e:
        print 'Doesn\'t have the permission to write your workspace!', e
        sys.exit(1)

    set_config('env', 'workspace', workspace_path)
    set_config('env', 'log', log_path)
    set_config('env', 'outputs', output_path)
    set_config('env', 'batch_job', upload_path)
    set_config('ml', 'trainStore', output_path)

    app_root = os.path.split(os.path.realpath(__file__))[0]
    setting_file_template = app_root + '/BioQueue/settings-example.py'
    setting_file_new = app_root + '/BioQueue/settings.py'
    apache_file_template = app_root + '/deploy/000-default.conf.tpl'
    apache_file_new = app_root + '/deploy/000-default.conf'

    setting_handler = open(setting_file_template, 'r')
    setting_handler_new = open(setting_file_new, 'w')
    apache_handler = open(apache_file_template, 'r')
    apache_handler_new = open(apache_file_new, 'w')
    setting_file = setting_handler.read()
    apache_file = apache_handler.read()
    secret_key = get_random_secret_key()
    set_config('program', 'secret_key', secret_key)
    setting_file = setting_file.replace('{SECRET_KEY}', secret_key)

    print ''
    print '==================='
    print 'Basic configuration'
    print '==================='
    print ''

    cpu_cores = str(cpu_count())
    user_cpu_cores = raw_input('CPU cores (By default: %s): ' % cpu_cores)
    if user_cpu_cores:
        cpu_cores = user_cpu_cores
    set_config('env', 'cpu', cpu_cores)
    import psutil
    memory_gbs = round(psutil.virtual_memory().total / byte_to_gigabyte)
    user_memory = raw_input('Memory (Gb, by default: %s Gb): ' % memory_gbs)
    if user_memory:
        memory_gbs = user_memory
    set_config('env', 'memory', memory_gbs)

    disk_size = psutil.disk_usage(workspace_path).total / byte_to_gigabyte
    user_disk_size = raw_input('Disk quota for each user (Gb, by default: %s Gb): ' % disk_size)
    if user_disk_size:
        disk_size = user_disk_size
    set_config('env', 'disk_quota', disk_size)

    print '======================================='
    print 'Do you want to use BioQueue with MySQL? '
    print '======================================='
    mysql_fb = raw_input('y/n (By default: y)')

    if mysql_fb == 'n':
        db_file_template = app_root + '/deploy/sqlite.tpl'
        db_file_handler = open(db_file_template, 'r')
        db_file = db_file_handler.read()
    else:
        db_file_template = app_root + '/deploy/mysql.tpl'
        db_file_handler = open(db_file_template, 'r')
        db_file = db_file_handler.read()
        database_configure = dict()
        database_configure['host'] = raw_input('Database host: ')
        database_configure['user'] = raw_input('Database user: ')
        database_configure['db_name'] = raw_input('Database name: ')
        database_configure['password'] = getpass('Database password: ')
        db_port = raw_input('Database port (By default is 3306): ')
        if not db_port:
            db_port = '3306'
        database_configure['port'] = db_port

        print '===================================='
        print 'Configuring database, please wait...'
        print '===================================='

        set_config('db', 'host', database_configure['host'])
        set_config('db', 'user', database_configure['user'])
        set_config('db', 'db_name', database_configure['db_name'])
        set_config('db', 'password', database_configure['password'])
        set_config('db', 'port', database_configure['port'])
        db_file = db_file.replace('{DB_NAME}', database_configure['db_name']) \
            .replace('{DB_USER}', database_configure['user']) \
            .replace('{DB_PASSWORD}', database_configure['password']) \
            .replace('{DB_HOST}', database_configure['host']) \
            .replace('{DB_PORT}', database_configure['port'])

    setting_file = setting_file.replace('{DATABASE_BACKEND}', db_file)

    print '====================================================================================='
    print 'Do you agree to provide us diagnostic and usage information to help improve BioQueue?'
    print 'We collect this information anonymously.'
    print '====================================================================================='
    fb = raw_input('y/n (By default: y)')

    if fb == 'n':
        set_config('program', 'feedback', 'no')
    else:
        set_config('program', 'feedback', 'yes')

    setting_handler.close()
    setting_handler_new.write(setting_file)
    apache_handler_new.write(apache_file.replace('{APP_ROOT}', app_root))
    setting_handler_new.close()
    apache_handler.close()
    apache_handler_new.close()

    django_manage_path = os.path.split(os.path.realpath(__file__))[0] + '/manage.py'

    init_data_path = os.path.split(os.path.realpath(__file__))[0] + '/init_resource.json'

    print '==============================='
    print 'Creating tables, please wait...'
    print '==============================='

    os.system('python %s migrate' % django_manage_path)

    print '============================'
    print 'Loading data, please wait...'
    print '============================'

    os.system('python %s loaddata %s' % (django_manage_path, init_data_path))

    print '====================================='
    print 'Now we\'ll create a superuser account'
    print '====================================='

    os.system('python %s createsuperuser' % django_manage_path)


if __name__ == '__main__':
    setup()

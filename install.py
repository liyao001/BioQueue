#!/usr/bin/env python
import os
import sys
from getpass import getpass
import ConfigParser


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
    workspace_path = raw_input('Path of workspace: ')
    while not os.path.exists(workspace_path):
        try:
            os.makedirs(workspace_path)
            break
        except Exception, e:
            print 'The path you input doesn\'t exist! Please reassign it.', e
            workspace_path = raw_input('Path of workspace: ')

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

    set_config('env', 'cpu', raw_input('CPU cores: '))
    set_config('env', 'mem', raw_input('Memory(Gb): '))
    set_config('env', 'disk_quota', raw_input('Disk quota for each user(Gb): '))

    database_configure = dict()
    database_configure['host'] = raw_input('Database host: ')
    database_configure['user'] = raw_input('Database user: ')
    database_configure['db_name'] = raw_input('Database name: ')
    database_configure['password'] = getpass('Database password: ')
    database_configure['port'] = raw_input('Database port (By default is 3306): ')

    print '===================================================='
    print 'Configuring database, please wait...'
    print '===================================================='

    set_config('db', 'host', database_configure['host'])
    set_config('db', 'user', database_configure['user'])
    set_config('db', 'db_name', database_configure['db_name'])
    set_config('db', 'password', database_configure['password'])
    set_config('db', 'port', database_configure['port'])

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

    setting_file = setting_file.replace('{SECRET_KEY}', get_random_secret_key())\
        .replace('{DB_NAME}', database_configure['db_name'])\
        .replace('{DB_USER}', database_configure['user'])\
        .replace('{DB_PASSWORD}', database_configure['password'])\
        .replace('{DB_HOST}', database_configure['host'])\
        .replace('{DB_PORT}', database_configure['port'])
    setting_handler.close()
    setting_handler_new.write(setting_file)
    apache_handler_new.write(apache_file.replace('{APP_ROOT}', app_root))
    setting_handler_new.close()
    apache_handler.close()
    apache_handler_new.close()

    print '===================================================='
    print 'Installing dependent python packages, please wait...'
    print '===================================================='

    pip_import_path = os.path.split(os.path.realpath(__file__))[0] + '/deploy/prerequisites.txt'
    os.system('pip install -r %s' % pip_import_path)

    django_manage_path = os.path.split(os.path.realpath(__file__))[0] + '/manage.py'

    init_data_path = os.path.split(os.path.realpath(__file__))[0] + '/init_resource.json'

    print '===================================================='
    print 'Creating tables, please wait...'
    print '===================================================='

    os.system('python %s migrate' % django_manage_path)

    print '===================================================='
    print 'Loading data, please wait...'
    print '===================================================='

    os.system('python %s loaddata %s' % (django_manage_path, init_data_path))

    print '===================================================='
    print 'Now we\'ll create a superuser account'
    print '===================================================='

    os.system('python %s createsuperuser' % django_manage_path)

if __name__ == '__main__':
    setup()

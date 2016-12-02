#! /usr/bin/env python
import os
import sys
from worker.baseDriver import set_config


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
                    'CPBQueue')).encode('utf-8')
            ).digest())
    return ''.join(random.choice(chars) for i in range(50))


def setup():
    workspace_path = raw_input('Path of workspace: ')
    while not os.path.exists(workspace_path):
        print 'The path you input doesn\'t exist! Please reassign it'
        workspace_path = raw_input('Path of workspace: ')

    log_path = os.path.join(workspace_path, 'logs')
    output_path = os.path.join(workspace_path, 'outputs')
    try:
        os.mkdir(log_path)
        os.mkdir(output_path)
    except Exception, e:
        print 'Doesn\'t have the permission to write your workspace!'
        sys.exit(1)

    set_config('env', 'workspace', workspace_path)
    set_config('env', 'log', log_path)
    set_config('env', 'outputs', output_path)

    database_configure = dict()
    database_configure['host'] = raw_input('Database host: ')
    database_configure['user'] = raw_input('Database user: ')
    database_configure['db_name'] = raw_input('Database name: ')
    database_configure['password'] = raw_input('Database password: ')
    database_configure['port'] = raw_input('Database port: ')

    print 'Configuring database, please wait...'

    set_config('db', 'host', database_configure['host'])
    set_config('db', 'user', database_configure['user'])
    set_config('db', 'db_name', database_configure['db_name'])
    set_config('db', 'password', database_configure['password'])
    set_config('db', 'port', database_configure['port'])

    setting_file_template = os.path.split(os.path.realpath(__file__))[0] + '/CPBQueue/settings-example.py'
    setting_file_new = os.path.split(os.path.realpath(__file__))[0] + '/CPBQueue/settings.py'

    setting_handler = open(setting_file_template, 'r')
    setting_handler_new = open(setting_file_new, 'w')
    setting_file = setting_handler.read()
    setting_file = setting_file.replace('{SECRET_KEY}', get_random_secret_key())\
        .replace('{DB_NAME}', database_configure['db_name'])\
        .replace('{DB_USER}', database_configure['user'])\
        .replace('{DB_PASSWORD}', database_configure['password'])\
        .replace('{DB_HOST}', database_configure['host'])\
        .replace('{DB_PORT}', database_configure['port'])
    setting_handler.close()
    setting_handler_new.write(setting_file)
    setting_handler_new.close()

    os.system('pip install -r deploy/requirements.txt')
    os.system('python manage.py migrate')


if __name__ == '__main__':
    setup()
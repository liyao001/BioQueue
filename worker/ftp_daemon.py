#!/usr/bin/env python
from daemon import runner
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from django.utils.crypto import pbkdf2
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import django_initial
from django.contrib.auth.models import User
from baseDriver import get_config
import os
import base64
root_path = os.path.split(os.path.realpath(__file__))[0]
from ftpserver import ftp_init


class App:
    def __init__(self):
        self.stdin_path = '/dev/null'
        self.stdout_path = os.path.join(root_path, 'ftplog.txt')
        self.stderr_path = os.path.join(root_path, 'ftplog.txt')
        self.pidfile_path = os.path.join(root_path, 'BioQueueFtp.pid')
        self.pidfile_timeout = 5

    def run(self):
        while True:
            try:
                ftp_init()
            except Exception as e:
                print e

app = App()
daemon_runner = runner.DaemonRunner(app)
daemon_runner.do_action()

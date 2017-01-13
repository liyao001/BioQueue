#!/usr/bin/env python
import time
from daemon import runner
import subprocess
import os
root_path = os.path.split(os.path.realpath(__file__))[0]


class App:
    def __init__(self):
        self.stdin_path = '/dev/null'
        self.stdout_path = os.path.join(root_path, 'queuelog.txt')
        self.stderr_path = os.path.join(root_path, 'queuelog.txt')
        self.pidfile_path = os.path.join(root_path, 'BioQueue.pid')
        self.pidfile_timeout = 5

    def run(self):
        while True:
            try:
                subprocess.Popen(['python', os.path.join(root_path, 'BioCommander.py')], stdin=None, stdout=None, stderr=None)
            except Exception, e:
                print e
            time.sleep(10)

app = App()
daemon_runner = runner.DaemonRunner(app)
daemon_runner.do_action()

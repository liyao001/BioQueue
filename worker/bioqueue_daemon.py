#!/usr/bin/env python
from multiprocessing import cpu_count
import baseDriver
import time
import os
root_path = os.path.split(os.path.realpath(__file__))[0]


class App:
    def __init__(self):
        self.stdin_path = '/dev/null'
        self.stdout_path = os.path.join(root_path, 'queuelog.txt')
        self.stderr_path = os.path.join(root_path, 'queuelog.txt')
        self.pidfile_path = os.path.join(root_path, 'BioQueue.pid')
        self.pidfile_timeout = 5

    @staticmethod
    def run():
        import bioqueue
        bioqueue.main()


if __name__ == '__main__':
    from daemon import runner
    app = App()
    daemon_runner = runner.DaemonRunner(app)
    daemon_runner.do_action()

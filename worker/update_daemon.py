#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2017/4/27 3:21
# @Project : BioQueue
# @Author  : Li Yao
# @File    : update_daemon.py
from __future__ import print_function
import os
import update
import time

root_path = os.path.split(os.path.realpath(__file__))[0]


class App:
    def __init__(self):
        self.stdin_path = '/dev/null'
        self.stdout_path = os.path.join(root_path, 'updatelog.txt')
        self.stderr_path = os.path.join(root_path, 'updatelog.txt')
        self.pidfile_path = os.path.join(root_path, 'BioQueueUpdate.pid')
        self.pidfile_timeout = 5

    @staticmethod
    def run():
        # check update per day
        update_frequency = 60 * 60 * 24
        while True:
            try:
                update.main()
            except Exception as e:
                print(e)
            time.sleep(update_frequency)



if __name__ == '__main__':
    from daemon import runner
    app = App()
    daemon_runner = runner.DaemonRunner(app)
    daemon_runner.do_action()

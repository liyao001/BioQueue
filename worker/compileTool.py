#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 03/12/2017 10:16 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : compileTool.py
from __future__ import print_function
import getopt
import os
import subprocess
import sys


def get_maintenance_models():
    """
    Get maintenance models
    :return: list, module names
    """
    protocols = []
    protocols_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'maintenance_models')
    for model_name in os.listdir(protocols_path):
        if not model_name.endswith('.py') or model_name.startswith('_') or model_name.startswith('maintenance'):
            continue
        protocols.append(model_name.replace('.py', ''))
    return protocols


def main(compile_method, workspace, user_bin, enter_dir=""):
    if compile_method in get_maintenance_models():
        if enter_dir != "":
            workspace = os.path.join(workspace, enter_dir)
        model = __import__("maintenance_models." + compile_method, fromlist=[compile_method])
        steps = model.get_method()
        for step in steps:
            command = step['software']+' '+step['parameter']
            command.replace('{UserBin}', user_bin)
            step_process = subprocess.Popen(command, shell=True, cwd=workspace)
            process_id = step_process.pid
            step_process.wait()
            if step_process.returncode != 0:
                sys.exit(1)
    else:
        sys.exit(1)


if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:], "c:w:u:s:", ["compile=", "workspace=", "user_bin=", "enter_dir="])
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit()

    if len(opts) == 0:
        sys.exit()

    cm = ''
    w = ''
    ub = ''
    ed = ''

    for o, a in opts:
        if o in ("-c", "--compile"):
            cm = a
        elif o in ("-w", "--workspace"):
            w = a
        elif o in ("-u", "--user_bin"):
            ub = a
        elif o in ("-s", "--enter_dir"):
            ed = a
    main(cm, w, ub, ed)

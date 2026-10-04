#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 03/12/2017 10:16 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : compile_tool.py
from __future__ import print_function
import getopt
import logging
import os
import subprocess
import sys

logger = logging.getLogger("BioQueue.compile_tool")


def get_maintenance_models():
    """
    Get maintenance models
    :return: list, module names
    """
    protocols = []
    protocols_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'maintenance_models')
    try:
        names = os.listdir(protocols_path)
    except OSError as e:
        logger.error("get_maintenance_models: cannot list %s: %s", protocols_path, e)
        return protocols
    for model_name in names:
        if not model_name.endswith('.py') or model_name.startswith('_') or model_name.startswith('maintenance'):
            continue
        protocols.append(model_name.replace('.py', ''))
    return protocols


def main(compile_method, workspace, user_bin, enter_dir=""):
    if compile_method not in get_maintenance_models():
        sys.exit(1)
    if enter_dir != "":
        workspace = os.path.join(workspace, enter_dir)
    try:
        model = __import__("maintenance_models." + compile_method, fromlist=[compile_method])
    except Exception as e:
        logger.error("Failed to import maintenance_models.%s: %s", compile_method, e)
        sys.exit(1)
    steps = model.get_method()
    for step in steps:
        command = step['software'] + ' ' + step['parameter']
        command = command.replace('{UserBin}', user_bin)
        step_process = subprocess.Popen(command, shell=True, cwd=workspace)
        step_process.wait()
        if step_process.returncode != 0:
            sys.exit(1)


if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:], "c:w:u:s:", ["compile=", "workspace=", "user_bin=", "enter_dir="])
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit(1)

    if len(opts) == 0:
        sys.exit(1)

    compile_method = ""
    workspace = ""
    user_bin = ""
    enter_dir = ""

    for o, a in opts:
        if o in ("-c", "--compile"):
            compile_method = a
        elif o in ("-w", "--workspace"):
            workspace = a
        elif o in ("-u", "--user_bin"):
            user_bin = a
        elif o in ("-s", "--enter_dir"):
            enter_dir = a
    main(compile_method, workspace, user_bin, enter_dir)

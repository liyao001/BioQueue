#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2017/4/27 3:21
# @Project : BioQueue
# @Author  : Li Yao
# @File    : update.py

from __future__ import print_function
from worker.baseDriver import get_config, get_bioqueue_version
import subprocess, sys, os

def check_version():
    """
    Compare local version with remote version, decide whether the instance needs to be updated.
    :return: int, 0 or 1
    """
    try:
        from urllib2 import urlopen
    except ImportError:
        from urllib.request import urlopen

    remote_address = get_config('program', 'latest_version')
    try:
        res_data = urlopen(remote_address)
        remote_version = res_data.read()
        local_version = get_bioqueue_version()
        if remote_version == local_version:
            return 0
        else:
            return 1
    except Exception as e:
        print(e)
        return 0


def main():
    """
    Update function
    It will call git pull, install the new required packages and update the old packages.
    If git is not installed or the program failed to update dependant packages, the program will raise an error.
    :return: None
    """
    if check_version():
        # backup settings
        config_file = os.path.split(os.path.realpath(__file__))[0] + '/worker/config.conf'
        settings_file = os.path.split(os.path.realpath(__file__))[0] + '/BioQueue/settings.py'
        os.rename(config_file, config_file+'.back')
        os.rename(settings_file, settings_file+'.back')
        # update
        try:
            git_back = subprocess.Popen(('git', 'pull'))
            git_back.wait()
            return_code = git_back.returncode

            if return_code:
                # force
                step_1 = os.system('git fetch --all')
                if step_1:
                    sys.exit(3)
                step_2 = os.system('git reset --hard origin/master')
                if step_2:
                    sys.exit(3)
                return_code = os.system('git pull')
                if return_code:
                    sys.exit(3)

        except OSError:
            print("===========================================")
            print("|Please install git before update BioQueue|")
            print("===========================================")
            sys.exit(1)
        # restore settings
        os.rename(config_file + '.back', config_file)
        os.rename(settings_file + '.back', settings_file)

        # update dependant packages
        from install import install_package
        if not install_package():
            sys.exit(2)

        # migrate model
        manage_file = os.path.split(os.path.realpath(__file__))[0] + '/manage.py'
        os.system('python %s migrate' % manage_file)
    else:
        print("Your instance is already up-to-date.")


if __name__ == '__main__':
    main()

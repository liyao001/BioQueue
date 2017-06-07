#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2017/4/27 3:21
# @Project : BioQueue
# @Author  : Li Yao
# @File    : update.py

from __future__ import print_function
from baseDriver import get_config, get_bioqueue_version
import subprocess, sys, os

def check_version():
    """
    Compare local version with remote version, decide whether the instance needs to be updated.
    :return: int, 0 or 1
    """
    import requests

    remote_address = get_config('program', 'latest_version')
    try:
        res_data = requests.get(remote_address)
        remote_version = res_data.content
        local_version = get_bioqueue_version()
        if remote_version == local_version:
            return 0
        else:
            return 1
    except Exception as e:
        print(e)
        return 0


def calc_md5_for_file(file_path):
    """
    Calculate the md5 value for a file
    :param file_path: string, file path
    :return: string, md5 value or ''
    """
    import hashlib
    if not os.path.isfile(file_path):
        return
    file_hash = hashlib.md5()
    f = open(file_path, 'rb')
    while True:
        b = f.read(8096)
        if not b:
            break
        file_hash.update(b)
    f.close()
    return file_hash.hexdigest()


def main():
    """
    Update function
    It will call git pull, install the new required packages and update the old packages.
    If git is not installed or the program failed to update dependant packages, the program will raise an error.
    :return: None
    """
    root_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0]
    # backup settings
    prerequisite_file = root_path + '/deploy/prerequisites.txt'
    prerequisite_md5_before = calc_md5_for_file(prerequisite_file)
    config_file = root_path + '/worker/config.conf'
    settings_file = root_path + '/BioQueue/settings.py'
    os.rename(config_file, config_file+'.back')
    os.rename(settings_file, settings_file+'.back')
    # update
    try:
        git_back = subprocess.Popen(('git', 'pull'), cwd=root_path)
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
    prerequisite_md5_after = calc_md5_for_file(prerequisite_file)
    if prerequisite_md5_before == prerequisite_md5_after:
        print('===================================')
        print('|Dependent packages are up-to-date|')
        print('===================================')
        sys.exit(0)
    else:
        print('===================================')
        print('|Updating dependent packages......|')
        print('===================================')

        from install import install_package
        if not install_package():
            sys.exit(2)
        else:
            sys.exit(0)

    # migrate model
    # manage_file = os.path.split(os.path.realpath(__file__))[0] + '/manage.py'
    # os.system('python %s migrate' % manage_file)


if __name__ == '__main__':
    main()

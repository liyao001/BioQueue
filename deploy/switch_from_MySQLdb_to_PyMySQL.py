#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2017/4/26 10:04
# @Project : BioQueue
# @Author  : Li Yao
# @File    : switch_from_MySQLdb_to_PyMySQL.py
import os

# remove from prerequisites
common_suffix = os.path.split(os.path.realpath(__file__))[0]
pip_import_path = common_suffix + '/prerequisites.txt'
pip_import_fallback_path = common_suffix + '/prerequisites.fallback.txt'
pip_list_handler = open(pip_import_path, 'r')
pip_list = pip_list_handler.read()
pip_list = pip_list.replace('MySQL-python==1.2.5', 'PyMySQL')
pip_list_handler.close()
pip_list_handler = open(pip_import_fallback_path, 'w')
pip_list_handler.write(pip_list)
pip_list_handler.close()

# switch to PyMySQL
import_string = """
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass
"""
manage_py_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/manage.py'
mpp_handler = open(manage_py_path, 'r')
mpp = mpp_handler.read()
mpp = mpp.replace('import sys\n', 'import sys\n' + import_string)
mpp_handler.close()
mpp_handler = open(manage_py_path, 'w')
mpp_handler.write(mpp)
mpp_handler.close()

worker_init_py_path = os.path.split(os.path.split(os.path.realpath(__file__))[0])[0] + '/worker/__init__.py'
wi_handler = open(worker_init_py_path, 'w')
wi_handler.write(import_string)
wi_handler.close()
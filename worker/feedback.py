#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time: 2017/2/27 12:24
# @Author: Li Yao
# @File: feedback.py
# @License: Apache
# @Bitbutcket: https://bitbucket.org/li_yao/
# @Github: https://github.com/liyao001
import requests
import base64
from baseDriver import get_config, get_bioqueue_version


def feedback(software, parameter, hash):
    """
    Usage feedback
    :param software:
    :param parameter:
    :param hash:
    :return:
    """
    ver = base64.b64encode(get_bioqueue_version())
    software = base64.b64encode(software)
    parameter = base64.b64encode(parameter)
    get_data_dict = {'ver': base64.b64encode(get_bioqueue_version()),
                     'software': software,
                     'parameter': parameter}
    try:
        fb_url = get_config('ml', 'api') + '/Gate/feedback'
        _ = requests.get(fb_url, params=get_data_dict, timeout=3)
    except:
        pass


def feedback_error(software, parameter, error_message):
    """
    Feedback error
    :param software: string, software name
    :param parameter: string, parameter
    :param error_message: string, error message
    :return:
    """
    post_data_dict = {
        'ver': get_bioqueue_version(),
        'software': software,
        'parameter': parameter,
        'error': error_message,
    }
    try:
        fb_url = get_config('ml', 'api') + '/Gate/error_feedback'
        _ = requests.post(fb_url, data=post_data_dict, timeout=3)
    except:
        pass


def feedback_checkpoint(software, parameter, hash, cpu_a, cpu_b, cpu_r, mem_a, mem_b, mem_r, disk_a, disk_b, disk_r):
    """
    Feedback checkpoint
    :param software: string, software name
    :param parameter: string, parameter
    :param hash: string, hash
    :param cpu_a: float, cpu a
    :param cpu_b: float, cpu b
    :param cpu_r: float, cpu r
    :param mem_a: float, memory a
    :param mem_b: float, memory b
    :param mem_r: float, memory r
    :param disk_a: float, disk a
    :param disk_b: float, disk b
    :param disk_r: float, disk r
    :return:
    """
    from ui.tools import os_to_int
    post_data_dict = dict()
    post_data_dict['cpu'] = get_config('env', 'cpu')
    post_data_dict['mem'] = get_config('env', 'memory')
    post_data_dict['os'] = os_to_int()
    post_data_dict['software'] = software
    post_data_dict['parameter'] = parameter
    post_data_dict['hash'] = hash
    post_data_dict['parent'] = 1
    if abs(float(cpu_r)) > 0.5:
        post_data_dict['cpu_a'] = cpu_a
        post_data_dict['cpu_b'] = cpu_b
        post_data_dict['cpu_r'] = cpu_r
    if abs(float(mem_r)) > 0.5:
        post_data_dict['mem_a'] = mem_a
        post_data_dict['mem_b'] = mem_b
        post_data_dict['mem_r'] = mem_r
    if abs(float(disk_r)) > 0.5:
        post_data_dict['disk_a'] = disk_a
        post_data_dict['disk_b'] = disk_b
        post_data_dict['disk_r'] = disk_r
    try:
        fb_url = get_config('ml', 'api') + '/Gate/cb_feedback'
        t = requests.post(fb_url, data=post_data_dict, timeout=3)
    except:
        pass

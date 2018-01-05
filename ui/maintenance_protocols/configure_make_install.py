#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 29/12/2017 10:05 AM
# @Project : main
# @Author  : Li Yao
# @File    : configure_make_install.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='./configure',
                        parameter='--prefix {UserBin}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='dfca5277f71c6782e3351f6ed9ac7fcb',
                        step_order=step_order_start))
    steps.append(db_obj(software='make',
                        parameter='',
                        parent=protocol_parent,
                        user_id=0,
                        hash='099dafc678df7d266c25f95ccf6cde22',
                        step_order=step_order_start+1))
    steps.append(db_obj(software='make',
                        parameter='install',
                        parent=protocol_parent,
                        user_id=0,
                        hash='12b64827119f4815ca8d43608d228f36',
                        step_order=step_order_start+2))
    return step_order_start+len(steps), steps
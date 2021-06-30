#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 14/01/2018 01:04 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : gunzip.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='gunzip',
                        parameter='{{LastOutput}}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='0603ff9d39724ecd6d62be4618901b54',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

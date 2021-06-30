#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 14/01/2018 01:04 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : gunzip.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='gzip',
                        parameter='{{InputFile}}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='fe5d52008fdd08800b24354df032b07c',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

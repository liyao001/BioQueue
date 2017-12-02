#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 02/12/2017 11:59 PM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : zip.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='make',
                        parameter='',
                        parent=protocol_parent,
                        user_id=0,
                        hash='099dafc678df7d266c25f95ccf6cde22',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

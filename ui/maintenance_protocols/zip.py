#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 02/12/2017 11:40 PM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : zip.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='unzip',
                        parameter='{LastOutput}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='728ab46516121c0215887cd60bcbb8bd',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

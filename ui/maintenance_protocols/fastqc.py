#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 19/08/2018 03:04 PM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : fastqc.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='fastqc',
                        parameter='-o {Workspace} {InputFile}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='3a24f9a8e2f78d22e6e310d2694c08c2',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 14/01/2018 01:04 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : gunzip.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='gunzip',
                        parameter='{InputFile}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='541df26aff8e4d054a57c7e3717e91ca',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

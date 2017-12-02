#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 02/12/2017 8:47 PM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : download.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='wget',
                        parameter='{InputFile}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='3efb64d0fa1144993ee287d3233dde06',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

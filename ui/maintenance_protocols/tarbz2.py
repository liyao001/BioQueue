#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 04/12/2017 1:39 PM
# @Project : main
# @Author  : Li Yao
# @File    : tarbz2.py
def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='tar',
                        parameter='-jxvf {LastOutput}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='670fb21245414e6d79b43dbd59ae1fb9',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps
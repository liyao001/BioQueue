#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 14/01/2018 01:04 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : bam_index.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='samtools',
                        parameter='index {InputFile}.sorted.bam',
                        parent=protocol_parent,
                        user_id=0,
                        hash='030fdbd05e08e64d7b5df6db763a3687',
                        step_order=step_order_start))
    return step_order_start+len(steps), steps

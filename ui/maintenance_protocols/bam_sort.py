#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 14/01/2018 01:04 AM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : bam_sort.py


def get_sub_protocol(db_obj, protocol_parent, step_order_start=1):
    steps = list()
    steps.append(db_obj(software='samtools',
                        parameter='sort -@ {ThreadN} -o sorted.bam {InputFile}',
                        parent=protocol_parent,
                        user_id=0,
                        hash='1c676531136f2dbd035894eb8a36e2e1',
                        step_order=step_order_start))
    steps.append(db_obj(software='samtools',
                        parameter='index sorted.bam',
                        parent=protocol_parent,
                        user_id=0,
                        hash='cb09b58adf333beb914e95e3a271fac3',
                        step_order=step_order_start + 1))
    return step_order_start+len(steps), steps

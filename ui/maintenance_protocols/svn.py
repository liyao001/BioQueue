#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 02/12/2017 8:57 PM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : svn.py
from ..models import Protocol


def get_sub_protocol(protocol_parent, step_order_start=1):
    steps = list()
    steps.append(Protocol(software='svn',
                    parameter='checkout {InputFile}',
                    parent=protocol_parent,
                    user_id=0,
                    hash='c025d53644388a50fb3704b4a81d5a93',
                    step=step_order_start))
    return step_order_start+len(steps), steps

#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 02/12/2017 8:56 PM
# @Project : BioQueue
# @Author  : Li Yao
# @File    : git.py
from ..models import Protocol


def get_sub_protocol(protocol_parent, step_order_start=1):
    steps = list()
    steps.append(Protocol(software='git',
                    parameter='clone {InputFile}',
                    parent=protocol_parent,
                    user_id=0,
                    hash='f95d6d36a0d0cae61a03704b46f72892',
                    step=step_order_start))
    return step_order_start+len(steps), steps

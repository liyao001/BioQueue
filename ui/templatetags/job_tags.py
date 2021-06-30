#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 5/10/20
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def keep_par_paginator(context, **kwargs):
    query = context["request"].GET.copy()
    for k, v in kwargs.items():
        query[k] = v
    return query.urlencode()

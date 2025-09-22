#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao (yaoli.gm@gmail.com)
# Created on: 1/28/20
from typing import List, Dict, Any


class JobActionProvider:
    """
    Base interface for job action providers.
    """
    def supports(self, job) -> bool:
        return False

    def get_actions(self, job) -> List[Dict[str, Any]]:
        return []


_providers: List[JobActionProvider] = []


def register(provider: JobActionProvider):
    _providers.append(provider)


def get_job_actions(job) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for p in _providers:
        try:
            if p.supports(job):
                actions.extend(p.get_actions(job))
        except Exception:
            continue
    return actions


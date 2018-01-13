#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 05/01/2018 2:12 PM
# @Project : main
# @Author  : Li Yao
# @File    : ena.py
from __future__ import print_function
try:
    from urllib2 import urlopen
except ImportError:
    from urllib.request import urlopen
import json


def get_download_link(acc, field="fastq_ftp"):
    """
    Get download link from EBI ENA
    :param acc: str
    :param field: str
    :return:
    """
    links = list()
    # https://www.ebi.ac.uk/ena/submit/read-data-format
    if acc[2] == "A":
        keyword = "submission_accession"
    elif acc[2] == "S":
        keyword = "sample_accession"
    elif acc[2] == "P":
        keyword = "study_accession"
    elif acc[2] == "X":
        keyword = "experiment_accession"
    elif acc[2] == "R":
        keyword = "run_accession"
    else:
        print("Unsupported accession type %s" % acc)
        return []
    api_bus = 'https://www.ebi.ac.uk/ena/portal/api/search?result=read_run&query="%s=%s"&fields=%s&format=json' % (keyword, acc, field)
    res_data = urlopen(api_bus)
    ret = res_data.read()
    if ret:
        res = json.loads(ret)
        for run in res:
            links.extend(run[field].split(";"))
        return links
    else:
        return []


def get_accession(query):
    """
    Get accession ID from EBI Search
    :param query:
    :return:
    """
    api_bus = "http://www.ebi.ac.uk/ebisearch/ws/rest/nucleotideSequences?query=%s&fieldurl=true&viewurl=true&format=json" % query
    sra_list = list()
    try:
        res_data = urlopen(api_bus)
        res = json.loads(res_data.read())
        if res["hitCount"] == 0:
            return 0
        for entry in res["entries"]:
            sra_list.append(entry["id"])
        return sra_list
    except Exception as e:
        print(e)
        return 0


def query_download_link_from_ebi(query):
    """
    Query download link from ebi
    :param query: str
    :return: list
    """
    all_links = list()
    fl = get_accession(query)
    for r in fl:
        tmp = get_download_link(r)
        if len(tmp) > 0:
            all_links.extend(tmp)
    ret_links = ["ftp://"+link for link in all_links]
    return sorted(list(set(ret_links)))

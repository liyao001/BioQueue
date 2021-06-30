#!/usr/bin/env python
# coding=utf-8
# @Author: Li Yao
# @Date: 01/28/20
import time
import threading
import logging
import os
import sys
from django.core.wsgi import get_wsgi_application

sys.path.append(os.path.split(os.path.split(os.path.realpath(__file__))[0])[0])
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "BioQueue.settings")

application = get_wsgi_application()
from ui.cron_jobs import archive_job_manager, audit_job_manager, audit_archiving_file_manager

DEFAULT_PREFIX = str(os.getpid())
logging.basicConfig(format='%(name)s - %(asctime)s - %(levelname)s: %(message)s',
                    datefmt='%d-%b-%y %H:%M:%S',
                    level=logging.INFO,
                    handlers=[
                        logging.FileHandler(os.path.join(os.getcwd(), 'cron_%s.log' % DEFAULT_PREFIX)),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger("BioQueue - Cron")


def aj_cron(logger):
    while True:
        logger.info("Cron - File archive")
        archive_job_manager(logger)
        logger.info("Cron - Done - File archive")
        time.sleep(300)


def pv_cron(logger):
    while True:
        logger.info("Cron - Job audit")
        audit_job_manager(logger)
        logger.info("Cron - Done - Job audit")
        time.sleep(3000)


def af_cron(logger):
    while True:
        logger.info("Cron - Archived file audit")
        audit_archiving_file_manager(logger)
        logger.info("Cron - Done - Archived file audit")
        time.sleep(3000)


def init_cron(function, args):
    t = threading.Thread(target=function, args=args)
    t.setDaemon(True)
    t.start()


if __name__ == "__main__":
    init_cron(aj_cron, (logger, ))
    init_cron(pv_cron, (logger, ))
    init_cron(af_cron, (logger, ))

    while True:
        time.sleep(30)

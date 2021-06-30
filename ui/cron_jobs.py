#!/usr/bin/env python
# coding=utf-8
# @Author: Li Yao
# @Date: 1/28/20
import hashlib
import os
import json
from worker.bases import get_config
from QueueDB.models import FileArchive  #, GoogleDriveConnection
from .views import audit_job_atom
# from .plugins.google_drive import GoogleDrive


def save_job(archive_id, logger):
    def file_md5(file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    try:
        archive = FileArchive.objects.get(id=archive_id)
        logger.info("Working on %s" % archive)
        try:
            prev_same_archive = FileArchive.objects.filter(protocol=archive.protocol,
                                                           protocol_ver=archive.protocol_ver,
                                                           files=archive.files).exclude(file_md5s="ph")
            logger.info("# md5 caches" % len(prev_same_archive))
        except:
            prev_same_archive = None
            logger.info("No md5 cache")
        md5_flag = 0
        tared_flag = 0
        uploaded_flag = 0
        files = json.loads(archive.files.replace("'", "\""))
        if prev_same_archive is not None:
            for psa in prev_same_archive:
                md5_flag = 1
                archive.file_md5s = psa.file_md5s
                if psa.archive_file != "ph":
                    archive.archive_file = psa.archive_file
                    tared_flag = 1
                if psa.file_id_remote != "ph":
                    archive.file_id_remote = psa.file_id_remote
                    uploaded_flag = 1
                archive.save()
        if not md5_flag:
            logger.info("Calculating MD5 sums")
            md5_sums = []
            for file in files:
                md5_sums.append(file_md5(file))
            archive.file_md5s = ",".join(md5_sums)
            archive.save()
        if not tared_flag:
            logger.info("Compressing files")
            import tarfile
            user_archives = archive.user.queuedb_profile_related.delegate.queuedb_profile_related.archive_folder
            if user_archives != "":
                if not os.path.exists(user_archives):
                    try:
                        os.makedirs(user_archives)
                    except Exception as e:
                        logger.exception(e)
                        archive_folder = ""
            if user_archives == "":
                user_archives = os.path.join(get_config("env", "workspace"),
                                             str(archive.user.queuedb_profile_related.delegate.id), "archives")
            if not os.path.exists(user_archives):
                os.makedirs(user_archives)
            tan = "%s.tar.gz" % os.path.join(user_archives, str(archive.id))
            tf = tarfile.open(tan, mode="w:gz")
            for f in files:
                tf.add(f, arcname=os.path.basename(f))
            tf.close()
            archive.archive_file = tan
            archive.save()
        # if not uploaded_flag:
        #     logger.info("Uploading files")
        #     try:
        #         g_info = GoogleDriveConnection.objects.get(user=archive.created_by)
        #         g = GoogleDrive(token_file=g_info.credential_pickle)
        #         folder_tag, folder_id = g.already_folder("BioQueue_Share")
        #         if not folder_tag:
        #             folder_id = g.create_folder("BioQueue_Share")
        #         file_id = g.upload_file(file_name="%d.tar.gz" % archive.id, file_path=archive.archive_file,
        #                                 folder_id=folder_id, description=archive.description)
        #         archive.file_id_remote = file_id
        #         archive.status = 1
        #         archive.save()
        #
        #         users = archive.shared_with.split(",")
        #         g.share_with_person(file_id, users, msg=archive.description+"\n Protocol ver: "+archive.protocol_ver)
        #     except GoogleDriveConnection.DoesNotExist:
        #         archive.comment = "No Google Drive connection available for account %s" % archive.created_by.username
        #         archive.save()
        #     except Exception as e:
        #         archive.comment(e)
        #         logger.error(e)
        #         archive.save()
    except FileArchive.DoesNotExist as e:
        logger.error(e)
        return False


def archive_job_manager(logger):
    jobs = FileArchive.objects.filter(status=0)
    # mark as in queue
    for job in jobs:
        try:
            job.status = -1
            job.save()
        except Exception as e:
            logger.error(e)
    # actually handle with these samples
    for job in jobs:
        try:
            logger.info("Archiving %d" % (job.id))
            save_job(job.id, logger)
        except Exception as e:
            logger.error(e)


def audit_job_manager(logger):
    counts, msg = audit_job_atom()
    if counts == -1:
        logger.error(msg)
    else:
        logger.info("Audit finished, %d jobs need audition" % counts)


def audit_archiving_file_manager(logger):
    try:
        jobs = FileArchive.objects.all()
        for job in jobs:
            if job.protocol_ver != job.protocol.ver:
                job.audit = 1
                job.save()
    except Exception as e:
        logger.error(e)

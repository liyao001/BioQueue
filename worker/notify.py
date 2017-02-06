#!/usr/bin/env python
import django_initial
from django.contrib.auth.models import User


class MailNotify:
    user_id = 0
    mail_type = 1
    job_id = 0
    protocol_id = 0
    ini_file = ''
    job_parameter = ''

    def __init__(self, uid, mail_type, job, protocol, in_file, parameters):
        self.user_id = uid
        self.mail_type = mail_type
        self.job_id = job
        self.protocol_id = protocol
        self.ini_file = in_file
        self.job_parameter = parameters

    @staticmethod
    def get_user_mail_address(uid):
        """
        from databaseDriver import con_mysql
        con, cur = con_mysql()
        sql = '''SELECT `email` FROM `auth_user` WHERE `id` = %d;''' % int(uid)
        cur.execute(sql)
        uid = cur.fetchone()
        if uid:
            return uid[0]
        else:
            return None
        """
        user_info = User.objects.get(id=uid)
        if user_info:
            return user_info.mail
        else:
            return None

    def success_job(self):
        content = """
        <h1>Job Updates from BioQueue</h1>
        <p>Your job has successfully finished! Here is a short overview of the job:</p>
        <ul>
            <li>Job id: %s</li>
            <li>Protocol id: %s</li>
            <li>Initial File: %s</li>
            <li>Job parameter: %s</li>
        </ul>
        """ % (str(self.job_id), str(self.protocol_id), self.ini_file, self.job_parameter)
        return content

    def error_job(self):
        content = """
        <h1>Job Updates from BioQueue</h1>
        <p>Some error(s) occurred during running your job! Here is a short overview of the job:</p>
        <ul>
            <li>Job id: %s</li>
            <li>Protocol id: %s</li>
            <li>Initial File: %s</li>
            <li>Job parameter: %s</li>
        </ul>
        """ % (str(self.job_id), str(self.protocol_id), self.ini_file, self.job_parameter)
        return content

    def send_mail(self, to):
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        from baseDriver import get_all_config
        settings = get_all_config()

        receivers = list()
        receivers.append(to)

        if self.mail_type == 1:
            mail_msg = self.success_job()
        else:
            mail_msg = self.error_job()

        message = MIMEText(mail_msg, 'html', 'utf-8')
        message['From'] = Header("BioQueue", 'utf-8')
        message['To'] = Header(to, 'utf-8')

        message['Subject'] = Header('Job notice', 'utf-8')

        try:
            if settings['mail']['mail_host'] != '':
                smtp_object = smtplib.SMTP()
                smtp_object.connect(settings['mail']['mail_host'], int(settings['mail']['mail_port']))
                smtp_object.login(settings['mail']['mail_user'], settings['mail']['mail_password'])
            else:
                smtp_object = smtplib.SMTP('localhost')

            smtp_object.sendmail(settings['mail']['sender'], receivers, message.as_string())
            return 1
        except smtplib.SMTPException:
            return 0

#!/usr/bin/env python
from __future__ import print_function
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
        Get user mail address
        :param uid: int, user id
        :return: string or None, e-mail address
        """
        user_info = User.objects.get(id=uid)
        if user_info:
            return user_info.mail
        else:
            return None

    def success_job(self):
        """
        Return the template content for successful jobs
        :return: String, template
        """
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
        """
        Return the template content for failed jobs
        :return: String, template
        """
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
        """
        Send mail
        :param to: string, receiver's e-mail address
        :return: int, 1 for success, 0 for error
        """
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
                if settings['mail']['ssl'] != '':
                    # ssl connection
                    url = "%s:%d" % (settings['mail']['mail_host'], int(settings['mail']['mail_port']))
                    smtp_object = smtplib.SMTP_SSL(settings['mail']['mail_host'], int(settings['mail']['mail_port']))
                elif settings['mail']['tls'] != '':
                    # tls connection
                    smtp_object = smtplib.SMTP(settings['mail']['mail_host'], int(settings['mail']['mail_port']))
                    smtp_object.ehlo()
                    smtp_object.starttls()
                else:
                    # normal connection
                    smtp_object = smtplib.SMTP(settings['mail']['mail_host'], int(settings['mail']['mail_port']))

                smtp_object.ehlo()
                smtp_object.login(settings['mail']['mail_user'], settings['mail']['mail_password'])
            else:
                smtp_object = smtplib.SMTP('localhost')

            smtp_object.sendmail(settings['mail']['mail_user'], receivers, message.as_string())
            smtp_object.close()
            return 1
        except smtplib.SMTPException as e:
            print(e)

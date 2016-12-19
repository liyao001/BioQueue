#!/usr/bin/env python
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from django.utils.crypto import pbkdf2
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from databaseDriver import con_mysql
from baseDriver import get_config
import os
import base64


class DummyMD5Authorizer(DummyAuthorizer):

    def validate_authentication(self, username, password, handler):
        try:
            password_info = self.user_table[username]['pwd'].split('$')
            user_password = base64.b64encode(pbkdf2(password, password_info[2], int(password_info[1])))

            if user_password != password_info[3]:
                raise KeyError
        except KeyError:
            raise AuthenticationFailed


def load_user_table():
    try:
        con, cur = con_mysql()
        sql = '''SELECT `id`, `username`, `password` FROM `auth_user` WHERE `is_active` > 0;'''
        cur.execute(sql)
        auth = DummyMD5Authorizer()
        ws = get_config('env', 'workspace')
        for u in cur.fetchall():
            user_directory = os.path.join(ws, str(u[0]), 'uploads')
            
            if not os.path.exists(user_directory):
                os.makedirs(user_directory)
            auth.add_user(u[1], u[2], user_directory, perm='elradfmw')
        return auth
    except Exception, e:
        print e
        return 0

if __name__ == "__main__":
    authentication = load_user_table()
    if authentication:
        handler = FTPHandler
        handler.authorizer = authentication
        
        server = FTPServer((get_config('env', 'ftp_addr'), int(get_config('env', 'ftp_port'))), handler)
        server.serve_forever()
    else:
        print '==Unable to Start BioQueue FTP Server=='

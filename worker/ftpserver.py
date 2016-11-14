#!/usr/bin/env python
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from databaseDriver import con_mysql
from hashlib import md5
from baseDriver import get_config
import os
import sys


class DummyMD5Authorizer(DummyAuthorizer):

    def validate_authentication(self, username, password, handler):
        try:
            # password{CPBSPLIT}salt
            stored_password_combine = self.user_table[username]['pwd']
            pw, salt = stored_password_combine.split('{CPBQSPLIT}')
            password = password+salt
            if sys.version_info >= (3, 0):
                for i in range(5):
                    password = md5(password.encode('latin1'))
            for i in range(5):
                password = md5(password).hexdigest()                
            if pw != password:
                raise KeyError
        except KeyError:
            raise AuthenticationFailed


def load_user_table():
    try:
        con, cur = con_mysql()
        sql = '''SELECT `id`, `user`, `passwd`, `salt` FROM `user` WHERE `status` > 0;'''
        cur.execute(sql)
        authorizere = DummyMD5Authorizer()
        ws = get_config('env', 'workspace')
        for u in cur.fetchall():
            user_directory = os.path.join(ws, str(u[0]), 'uploads')
            
            if not os.path.exists(user_directory):
                os.makedirs(user_directory)
            authorizere.add_user(u[1], u[2]+'{CPBQSPLIT}'+u[3], user_directory, perm='elradfmw')
        return authorizere
    except Exception, e:
        print e
        return 0

if __name__ == "__main__":
    authorizere = load_user_table()
    if authorizere:
        handler = FTPHandler
        handler.authorizer = authorizere
        
        server = FTPServer((get_config('env', 'ftp_addr'), int(get_config('env', 'ftp_port'))), handler)
        server.serve_forever()
    else:
        print '==Unable to Start CPBQueue FTP Server=='

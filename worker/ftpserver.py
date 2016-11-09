#!/usr/bin/env python
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from databaseDriver import conMySQL
from hashlib import md5
from baseDriver import getConfig
import os, sys

class DummyMD5Authorizer(DummyAuthorizer):

    def validate_authentication(self, username, password, handler):
        try:
            #password{CPBSPLIT}salt
            storedPWCombain = self.user_table[username]['pwd']
            pw, salt = storedPWCombain.split('{CPBQSPLIT}')
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

def loadUserTable():
    try:
        con, cur = conMySQL()
        sql = '''SELECT `id`, `user`, `passwd`, `salt` FROM `user` WHERE `status` > 0;'''
        cur.execute(sql)
        authorizere = DummyMD5Authorizer()
        ws = getConfig('env', 'workspace')
        for u in cur.fetchall():
            userDir = os.path.join(ws, str(u[0]), 'uploads')
            
            if not os.path.exists(userDir):
                os.makedirs(userDir)
            authorizere.add_user(u[1], u[2]+'{CPBQSPLIT}'+u[3], userDir, perm='elradfmw')
        return authorizere
    except Exception, e:
        print e
        return 0

if __name__ == "__main__":
    authorizere = loadUserTable()
    if authorizere:
        handler = FTPHandler
        handler.authorizer = authorizere
        
        server = FTPServer((getConfig('env', 'ftp_addr'), int(getConfig('env', 'ftp_port'))), handler)
        server.serve_forever()
    else:
        print '==Unable to Start CPBQueue FTP Server=='
# BioQueue
[![document](https://readthedocs.org/projects/bioqueue/badge/?version=latest "document")](https://bioqueue.readthedocs.io/en/latest/?badge=latest)

BioQueue is a lightweight and easy-to-use queue system to accelerate the proceeding of bioinformatic workflows. Based on machine learning methods, BioQueue can maximize the efficiency, and at the same time, it also reduced the possibility of errors caused by unsupervised concurrency (like memory leak). BioQueue can both run on POSIX compatible systems (Linux, Solaris, OS X, etc.) and Windows.
# Installation
## Prerequisites
BioQueue stores data on MySQL, for Windows Users, download the MySQL Installer or Zipped binary from [MySQL](http://www.mysql.com/downloads/). For POSIX compatible systems (like Ubuntu) users, running following command should be enough to install MySQL server.
```
sudo apt-get install mysql-server mysql-client
apt-get install libmysqld-dev
mysql -u root -p
CREATE DATABASE BioQueue;
CREATE USER 'bioqueue'@'localhost' IDENTIFIED BY 'REPLACE WITH YOUR OWN PASSWORD HERE';
GRANT ALL PRIVILEGES ON BioQueue . * TO 'bioqueue'@'localhost';
```
Note: The following instructions are for Ubuntu 14.04, but can be used as a guideline for other Linux flavors.
```
apt-get install python-dev
apt-get install python-pip
```
## 1. Download and setup the BioQueue project
First of all, you will need to clone the project from github (Or you can download BioQueue by open [this link](https://github.com/yauli/BioQueue/zipball/master).
```
git clone https://github.com/yauli/BioQueue.git
Or
wget https://github.com/yauli/BioQueue/zipball/master
```
Then navigate to the project's directory, and run `install.py` script (All dependent python packages will be automatically installed):
```
cd BioQueue
python install.py
```
When running `install.py`, this script will ask you a few questions include:
 1. Path of the workspace(where stores all the data for running BioQueue, like `D:/biodata` or `/mnt/biodata`)
 2. Database host: If you install MySQL server on your own machine, enter `localhost` or `127.0.0.1`
 3. Database user: bioqueue by default
 4. Database password
 5. Database port: `3306` by default
 6. CPU cores
 7. Memory (Gb)
 8. Disk quota for each user(Gb)

## 2. Start the queue
Run the `cron.py` script in the `BioQueue/worker` folder
```
python worker/cron.py
```
For Linux/Unix users, BioQueue can run in background by run `queue_daemon.py` instead of `cron.py`
```
python worker/queue_daemon.py start
```

## 3. Start webserver
```
python manage.py runserver 0.0.0.0:8000
```
This will start up the server on `0.0.0.0` and port `8000`, so BioQueue can be accessed over the network. If you want access BioQueue only in local environment, remove `0.0.0.0:8000`.
## 4. Start ftp server (optional, listen 20001 port by default)
```
python worker/ftpserver.py
```
This step is optional, if you run command above, the FTP server will listen **20001** port by default. For Linux/Unix users, BioQueue FTP service can run in background by run `ftp_daemon.py` instead of `ftpserver.py`
```
python worker/ftp_daemon.py start
```

## Useful informations
1. To stop the queue, the webserver or the ftp server, just hit `Ctrl-c` in the terminal from which BioQueue is running. If you run the queue or FTP server in the background, hit
```
python worker/queue_daemon.py stop
python worker/ftp_daemon.py stop
```
2. To get a better performance, moving the webserver to [Apache](https://github.com/yauli/BioQueue/wiki/Use-CPBQueue-with-Apache-and-mod_wsgi) or [nginx](https://nginx.org) is a good idea. 
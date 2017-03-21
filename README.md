# BioQueue
[![document](https://readthedocs.org/projects/bioqueue/badge/?version=latest "document")](https://bioqueue.readthedocs.io/en/latest/?badge=latest)

BioQueue is a web-based queue engine designed preferentially to improve the efficiency and robustness of job execution in bioinformatics research by estimating the system resources required by a certain job. At the same time, BioQueue also aims to promote the accessibility and reproducibility of data analysis in biomedical research. Implemented by Python 2.7, BioQueue can work in both POSIX compatible systems (Linux, Solaris, OS X, etc.) and Windows.
# Installation
## Prerequisites
BioQueue can store data on SQLite, which means users can set up BioQueue without an extra database software. However, to achieve a higher performance, we suggest users to install MySQL. For Windows users, download the MySQL Installer or Zipped binary from [MySQL](http://www.mysql.com/downloads/). For POSIX compatible systems (like Ubuntu) users, running the following command should be enough to install MySQL server.
```
sudo apt-get install mysql-server mysql-client
apt-get install libmysqld-dev
mysql -u root -p
CREATE DATABASE BioQueue;
CREATE USER 'bioqueue'@'localhost' IDENTIFIED BY 'YOURPASSWORD';
GRANT ALL PRIVILEGES ON BioQueue . * TO 'bioqueue'@'localhost';
```
Note: The following instructions are for Ubuntu 14.04, but can be used as a guideline for other Linux flavors. **Please replace 'YOURPASSWORD' with your own password for the database!**
```
apt-get install python-dev
apt-get install python-pip
```
## 1. Download and setup the BioQueue project
First of all, you will need to clone the project from Github (Or you can download BioQueue by open [this link](https://github.com/liyao001/BioQueue/zipball/master)).
```
git clone https://github.com/liyao001/BioQueue.git
Or
wget https://github.com/liyao001/BioQueue/zipball/master
```
Then navigate to the project's directory, and run `install.py` script (All dependent python packages will be automatically installed):
```
cd BioQueue
python install.py
```
When running `install.py`, this script will ask you a few questions include:
 1. CPU cores: The amount of CPU to use. Default value: all cores on that machine.
 2. Memory (Gb): The amount of memory to use. Default value: all physical memory on that machine.
 3. Disk quota for each user(Gb, default value: all disk space on that machine).

If you decide to run BioQueue with MySQL, the script will ask a few more questions:
 1. Database host: If you install MySQL server on your own machine, enter `localhost` or `127.0.0.1`.
 2. Database user: user name of the database.
 3. Database password: password of the database.
 4. Database port: `3306` by default

## 2. Start the queue
Run the `bioqueue.py` script in the `BioQueue/worker` folder
```
python worker/bioqueue.py
```
For Linux/Unix users, BioQueue can run in background by run `bioqueue_daemon.py` instead of `bioqueue.py`
```
python worker/bioqueue_daemon.py start
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
* To stop the queue, the webserver or the ftp server, just hit `Ctrl-c` in the terminal from which BioQueue is running. If you run the queue or FTP server in background, hit
```
python worker/bioqueue_daemon.py stop
python worker/ftp_daemon.py stop
```

* To get a better performance, moving the webserver to [Apache](http://bioqueue.readthedocs.io/en/latest/faq.html#use-bioqueue-with-apache-in-production-environment) or [nginx](https://nginx.org) is a good idea.
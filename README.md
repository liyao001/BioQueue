# BioQueue
[![document](https://readthedocs.org/projects/bioqueue/badge/?version=latest "document")](https://bioqueue.readthedocs.io/en/latest/?badge=latest)

BioQueue is a researcher-facing bioinformatic platform preferentially to improve the efficiency and robustness of analysis in bioinformatics research by estimating the system resources required by a particular job. At the same time, BioQueue also aims to promote the accessibility and reproducibility of data analysis in biomedical research. Implemented by Python **3.x**, BioQueue can work in both POSIX compatible systems (Linux, Solaris, OS X, etc.) and Windows.
## Get started

`pip` is the default package manager for BioQueue, so before installing BioQueue, please make sure that you have [pip](https://pip.pypa.io/en/stable/) installed.

### Prerequisites

BioQueue can store data on SQLite, which means users can set up BioQueue without an extra database software. However, to achieve a higher performance, **we suggest users to install MySQL or PostgreSQL**. If you want to set up MySQL or PostgreSQL on your machine, you can visit the wiki page. 
### 1. Download and setup the BioQueue project

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

If you decide to run BioQueue with MySQL or PostgreSQL, the script will ask a few more questions:
 1. Database host: If you install MySQL server on your own machine, enter `localhost` or `127.0.0.1`.
 2. Database user: user name of the database.
 3. Database password: password of the database.
 4. Database name: Name of the data table.
 5. Database port: `3306` by default for MySQL

Then the script will interact with you and create a super user account for the platform.

### 2. Start the queue

Run the `bioqueue.py` script in the `BioQueue/worker` folder
```
python worker/bioqueue.py
```

### 3. Start webserver

```
python manage.py runserver 0.0.0.0:8000
```
This will start up the server on `0.0.0.0` and port `8000`, so BioQueue can be accessed over the network. If you want access BioQueue only in local environment, remove `0.0.0.0:8000`.

## Useful information

* To stop the queue, the webserver or the ftp server, just hit `Ctrl-c` in the terminal from which BioQueue is running.
* To get a better performance, moving the webserver to [Apache](http://bioqueue.readthedocs.io/en/latest/faq.html#use-bioqueue-with-apache-in-production-environment) or [nginx](https://nginx.org) is a good idea.

## Screenshot

 ![](status_page.png)

## Citation

1. Yao, L., Wang, H., Song, Y. & Sui, G. BioQueue: a novel pipeline framework to accelerate bioinformatics analysis. *Bioinformatics* 33, 3286–3288 (2017). [doi:10.1093/bioinformatics/btx403](https://doi.org/doi:10.1093/bioinformatics/btx403)
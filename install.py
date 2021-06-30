#!/usr/bin/env python
import os
import sys
from multiprocessing import cpu_count
from getpass import getpass

# check python version
if sys.version_info[0] != 3:
    print("")
    print("========================================================================")
    print("|BioQueue requires Python 3.x                                          |")
    print("|For users from all platforms, conda can be used to install Python,    |")
    print("|BioQueue and its dependencies.                                        |")
    print("|Please rerun install.py script after you have installed the new python|")
    print("========================================================================")
    print("")
    exit()

try:
    from ConfigParser import ConfigParser
except ImportError:
    from configparser import ConfigParser

# pylint: disable
try:
   input = raw_input
except NameError:
   pass

byte_to_gigabyte = 1073741824


def set_config(section, key, value):
    config = ConfigParser()
    path = os.path.split(os.path.realpath(__file__))[0] + "/config/custom.conf"
    config.read(path)
    config.set(section, key, value)
    config.write(open(path, "w"))


def get_random_secret_key():
    import random
    import hashlib
    import time
    try:
        random = random.SystemRandom()
        using_sysrandom = True
    except NotImplementedError:
        import warnings
        warnings.warn("A secure pseudo-random number generator is not available "
                      "on your system. Falling back to Mersenne Twister.")
        using_sysrandom = False

    chars = "abcdefghijklmnopqrstuvwxyz0123456789!@#$^&*(-_=+)"
    if not using_sysrandom:
        random.seed(
            hashlib.sha256(
                ("%s%s%s" % (
                    random.getstate(),
                    time.time(),
                    "BioQueue")).encode("utf-8")
            ).digest())
    return "".join(random.choice(chars) for i in range(50))


def install_package():
    common_suffix = os.path.split(os.path.realpath(__file__))[0]
    pip_import_path = common_suffix + "/deploy/prerequisites.txt"
    pip_install = "pip install -r %s" % pip_import_path
    if os.system(pip_install):
        print("")
        print("==========================================================")
        print("|Fetal error occurred when installing python packages    |")
        print("|You can try to install these packages yourself with     |")
        print("|other package manager, like conda                       |")
        print("|Required packages are listed in deploy/prerequisites.txt|")
        print("==========================================================")
        print("")
        skip_errors = input("Are you sure you have all required packages install properly? (Y or n)")
        if skip_errors != "Y":
            sys.exit(-1)


def install_db_connector(db_type):
    if db_type == "mysql":
        plugin = "mysqlclient"
    elif db_type == "postgresql":
        plugin = "psycopg2"
    else:
        sys.exit(-1)

    if os.system("pip install %s" % plugin) != 0:
        print("")
        print("===================================")
        print("|Failed to install %s,   |" % plugin)
        print("|please try to install it manually|")
        print("===================================")
        print("")
    skip_errors = input("Are you sure you have the connector install properly? (Y or n)")
    if skip_errors != "Y":
        sys.exit(-1)


def setup():
    workspace_path = input("Please tell me the full path that you want BioQueue to save all data (workspace): ")
    while not os.path.exists(workspace_path):
        try:
            os.makedirs(workspace_path)
            break
        except Exception as e:
            print("")
            print("The path you input doesn't exist! Please reassign it.", e)
            print("")
            workspace_path = input("Path of workspace: ")

    print("")
    print("======================================================")
    print("|Installing dependent python packages, please wait...|")
    print("======================================================")
    print("")

    install_package()

    log_path = os.path.join(workspace_path, "logs")
    output_path = os.path.join(workspace_path, "outputs")
    train_path = os.path.join(workspace_path, "training")
    upload_path = os.path.join(workspace_path, "batch_job")
    file_comment_path = os.path.join(workspace_path, "file_comment")
    try:
        if not os.path.exists(log_path):
            os.mkdir(log_path)
        if not os.path.exists(output_path):
            os.mkdir(output_path)
        if not os.path.exists(train_path):
            os.mkdir(train_path)
        if not os.path.exists(upload_path):
            os.mkdir(upload_path)
        if not os.path.exists(file_comment_path):
            os.mkdir(file_comment_path)
    except Exception as e:
        print("")
        print("Doesn't have the permission to write content to your workspace!", e)
        print("")
        sys.exit(1)

    set_config("env", "workspace", workspace_path)
    set_config("env", "log", log_path)
    set_config("env", "outputs", output_path)
    set_config("env", "batch_job", upload_path)
    set_config("ml", "trainStore", output_path)

    app_root = os.path.split(os.path.realpath(__file__))[0]
    setting_file_template = app_root + "/BioQueue/settings-example.py"
    setting_file_new = app_root + "/BioQueue/settings.py"
    apache_file_template = app_root + "/deploy/000-default.conf.tpl"
    apache_file_new = app_root + "/deploy/000-default.conf"

    setting_handler = open(setting_file_template, "r")
    setting_handler_new = open(setting_file_new, "w")
    apache_handler = open(apache_file_template, "r")
    apache_handler_new = open(apache_file_new, "w")
    setting_file = setting_handler.read()
    apache_file = apache_handler.read()
    secret_key = get_random_secret_key()
    set_config("env", "secret_key", secret_key)
    setting_file = setting_file.replace("{SECRET_KEY}", secret_key)

    print("")
    print("=====================")
    print("|Basic configuration|")
    print("=====================")
    print("")

    cpu_cores = str(cpu_count())
    user_cpu_cores = input("CPU cores (By default: %s): " % cpu_cores)
    if user_cpu_cores:
        cpu_cores = user_cpu_cores
    set_config("env", "cpu", str(cpu_cores))
    set_config("env", "max_job", str(cpu_cores))
    import psutil
    memory_gbs = round(psutil.virtual_memory().total / byte_to_gigabyte)
    user_memory = input("Memory (Gb, by default: %s Gb): " % memory_gbs)
    if user_memory:
        memory_gbs = user_memory
    set_config("env", "memory", str(memory_gbs))

    disk_size = psutil.disk_usage(workspace_path).total / byte_to_gigabyte
    user_disk_size = input("Disk quota for each user (Gb, by default: %s Gb): " % disk_size)
    if user_disk_size:
        disk_size = user_disk_size
    set_config("env", "disk_quota", str(disk_size))

    print("")
    print("===================================================")
    print("|Which database do you want BioQueue to work with?|")
    print("| 1. MySQL                                        |")
    print("| 2. PostgreSQL                                   |")
    print("| 3. SQLite (not recommended)                     |")
    print("===================================================")
    print("")
    db_choice = int(input("Database (1, 2, or 3. By default: 1) "))

    if db_choice == 3:
        db_file_template = app_root + "/deploy/sqlite.tpl"
        db_file_handler = open(db_file_template, "r")
        db_file = db_file_handler.read()
    else:
        database_configure = dict()
        database_configure["host"] = input("Database host: ")
        database_configure["user"] = input("Database user: ")
        database_configure["db_name"] = input("Database name: ")
        database_configure["password"] = getpass("Database password: ")

        print("")
        print("===============================================")
        print("|Installing database connector, please wait...|")
        print("===============================================")
        print("")

        if db_choice == 1:
            install_db_connector("mysql")
            db_file_template = app_root + "/deploy/mysql.tpl"

            db_port = input("Database port (By default is 3306): ")
            if not db_port:
                db_port = "3306"
        elif db_choice == 2:
            install_db_connector("postgresql")
            db_file_template = app_root + "/deploy/postgresql.tpl"

            db_port = input("Database port (By default is 5432): ")
            if not db_port:
                db_port = "5432"
        else:
            sys.exit(2)

        database_configure["port"] = str(db_port)
        db_file_handler = open(db_file_template, "r")
        db_file = db_file_handler.read()

        print("")
        print("======================================")
        print("|Configuring database, please wait...|")
        print("======================================")
        print("")
        db_file = db_file.replace("{DB_NAME}", database_configure["db_name"]) \
            .replace("{DB_USER}", database_configure["user"]) \
            .replace("{DB_PASSWORD}", database_configure["password"]) \
            .replace("{DB_HOST}", database_configure["host"]) \
            .replace("{DB_PORT}", database_configure["port"])

    setting_file = setting_file.replace("{DATABASE_BACKEND}", db_file)

    print()
    print("=======================================================================================")
    print("|Do you agree to provide us diagnostic and usage information to help improve BioQueue?|")
    print("|We collect this information anonymously.                                             |")
    print("=======================================================================================")
    print()
    fb = input("y/n (By default: y) ")

    if fb == "n":
        set_config("env", "feedback", "no")
    else:
        set_config("env", "feedback", "yes")

    setting_handler.close()
    setting_handler_new.write(setting_file)
    apache_handler_new.write(apache_file.replace("{APP_ROOT}", app_root))
    setting_handler_new.close()
    apache_handler.close()
    apache_handler_new.close()

    django_manage_path = os.path.split(os.path.realpath(__file__))[0] + "/manage.py"

    init_data_path = os.path.split(os.path.realpath(__file__))[0] + "/init_resource.json"

    print("")
    print("=================================")
    print("|Creating tables, please wait...|")
    print("=================================")
    print("")

    os.system("python %s migrate" % django_manage_path)

    print("")
    print("==============================")
    print("|Loading data, please wait...|")
    print("==============================")
    print("")

    os.system("python %s loaddata %s" % (django_manage_path, init_data_path))

    print("")
    print("======================================")
    print("|Now we'll create a superuser account|")
    print("======================================")
    print("")

    os.system("python %s createsuperuser" % django_manage_path)


if __name__ == "__main__":
    setup()

#!/usr/bin/env python
import schedule, time, subprocess, baseDriver, databaseDriver, os
root_path = os.path.split(os.path.realpath(__file__))[0]


def job():
    subprocess.Popen(['python', os.path.join(root_path, 'BioCommander.py')], stdin=None, stdout=None, stderr=None)

cpu, mem, disk = baseDriver.get_init_resource()
databaseDriver.init_resource(cpu, mem, disk)
schedule.every(1).minutes.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)

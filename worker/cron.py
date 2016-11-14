#!/usr/bin/env python
import schedule, time, subprocess, baseDriver, databaseDriver


def job():
    subprocess.Popen(['python', 'BioCommander.py'], stdin=None, stdout=None, stderr=None)

cpu, mem, disk = baseDriver.get_init_resource()
databaseDriver.init_resource(cpu, mem, disk)
schedule.every(1).minutes.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)

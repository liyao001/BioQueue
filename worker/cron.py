#!/usr/bin/env python
import schedule, time, subprocess, baseDriver, databaseDriver

def job():
    subprocess.Popen(['python', 'BioCommander.py'], stdin=None, stdout=None, stderr=None)

cpu, mem, disk = baseDriver.getInitResource()
databaseDriver.initResource(cpu, mem, disk)
schedule.every(1).minutes.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)

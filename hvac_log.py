'''
This program collects energy consumpion information from the HVAC
system every 15 minutes and logs it along with the outside temperature

The goal is to use this information to determine:
- energy usage vs outside temperature
- energy use compared to original gas system using PG&E gas usage data

'''
import platform
import argparse
import logging
import picow_peacefair.pp_read as pp
import time
from datetime import datetime, timedelta
import socket
import sys
import os

if platform.system() == 'Darwin':
    macos = True
else:
    macos = False 
    import mariadb

# process command line options
parser = argparse.ArgumentParser()
# create the default name of the logfile from argv[0]
default_logfile = os.path.splitext(parser.prog)[0] + '.log'
parser.add_argument("--log", help=f'logfile location/name (default {default_logfile}',
    default=f'{default_logfile}')
parser.add_argument('--debug', help='enables printing to console, no database connection',
    action='store_true')
args = parser.parse_args()
    
# set up logging
log = logging.getLogger(__name__)
if args.debug:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(filename=args.log, encoding='utf-8', level=logging.WARN)

# work around intermittent T-Moble DHCP problem
# cache the address lookups here for later use while polling
devices = (
    'condenser',
    'evaporator',
    )
addresses = {}
for device in devices:
    addresses[device] = socket.gethostbyname(f'{device}.lan')

# connect to the local Mariadb database where results are recorded
if not macos:
    try:
        mdb = mariadb.connect(user='power_update', database='elpowerdb')
        mc = mdb.cursor()
    except mariadb.Error as e:
        log.exception(f'Error connecting to the database: {e}')
        sys.exit(1)

# data collection occurs on the quarter hour
# determine when the next quarter hour will occur
interval = 15
now = datetime.now()
log.debug(f'Current time is {now}')
next_second = -now.second
next_microsecond = -now.microsecond
next_minute = ((now.minute//interval) + 1) * interval
delta = timedelta(minutes=next_minute-now.minute, seconds=next_second, microseconds=next_microsecond)
target_time = now + delta
log.info(f'First target time is {target_time}')

# main polling loop collecting data
prev_energy = {}
while True:
    # wait for the quarter hour
    now = datetime.now()
    delta = target_time - now
    delay = delta.total_seconds()
    # delay can become negative if system sleeps (i.e. laptop on battery)
    if delay < 0:
        log.warning(f'{now=} {target_time=} {delta=} {delay=}')
    else:
        log.debug(f'Sleeping for {delay} seconds')
        time.sleep(delay)

    # collect data
    energy = {}
    insert_fields = []
    insert_values = []
    for device in devices:
        values = pp.read_dev(addresses[device])
        log.debug(values)
        if not values:
            log.warning(f'read from {device} failed')
            continue
        if 'energy' in values:
            energy = values['energy']
            if device in prev_energy:
                delta_energy = energy - prev_energy[device]
                insert_fields.append(f'{device}_energy')
                insert_values.append(f'{delta_energy*1000:4.0f}')
            prev_energy[device] = energy
        else:
            log.warning(f'Missing energy value for {device}')
        if device=='condenser' and 'temperature' in values:
            temperature = values['temperature']
            insert_fields.append('temperature')
            insert_values.append(f'{temperature:0.1f}')

    if insert_fields:
        insert_fields.append('time')
        timestamp = target_time.strftime('%Y-%m-%d %H:%M:%S')
        insert_values.append(f'"{timestamp}"')
        sql = f'INSERT INTO hvac_power ({",".join(insert_fields)}) VALUES ({",".join(insert_values)});'
        log.debug(sql)
            
        if not macos:
            try:
                mc.execute(sql)
                mdb.commit()
            except mariadb.Error as e:
                log.error(f'Error adding row to database: {e}')
        else:
            log.debug(sql)
    else:
        log.info('No database fields for INSERT - skipping')

    # enter date-time, energy increment, and outside temp in database
    target_time += timedelta(minutes=interval)

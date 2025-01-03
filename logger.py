#

import argparse
import logging
import time
import datetime
import subprocess
import sys
import os
import mariadb
import picow_peacefair.pp_read as pp
import modbus_solar.sEdge as se

parser = argparse.ArgumentParser()
parser.add_argument("--log", help="logfile location/name (default $CWD/energy_logger.log",
    default='energy_logger.log')
args = parser.parse_args()

# database accounts:
# power_update  for writing to database locally
# power_view    for reading database, even remotely

log = logging.getLogger(__name__)
logging.basicConfig(filename=args.log, encoding='utf-8', level=logging.WARN)

# create a timestamp for yesterday as we are summerizing yesterday's usage
date = (datetime.datetime.today()-datetime.timedelta(hours=12)).strftime('%Y-%m-%d')
log.debug(f'{date=}')

# INSERT the timestamp into the database; other fields will be NULL until later
try:
    mdb = mariadb.connect(user='power_update', database='elpowerdb')
    mc = mdb.cursor()
    sql = f'INSERT INTO daily_energy (day) VALUES ("{date}")'
    log.debug(sql)
    mc.execute(sql)
except mariadb.Error as e:
    log.exception(f'Error connecting to the database: {e}')
    sys.exit(1)

cwd = os.path.dirname(__file__)
pp_read = os.path.join(cwd, '../picow-peacefair/pp-read.py')

modbus_solar = os.path.join(cwd, 'modbus_solar')
sEdge = os.path.join(modbus_solar, 'sEdge.py')

# readings are from either Peacefair devices or from the solar inverter
# first read the Peacefair devices via HTTP/JSON
peacefair_list = {
    'waterheater':  'waterheater.lan',
    'condenser':    'condenser.lan',
    'evaporator':   'evaporator.lan',
}

# peacefair meters read via a picow are read individually via HTTP
for d in peacefair_list:
    pf_response = pp.read_dev(peacefair_list[d])
    if not pf_response or 'energy' not in pf_response:
        log.warning(f'read from {d} failed')
        continue
    value = pf_response['energy']

    log.debug(f'{pf_response=}, {value=}')

    sql = f'UPDATE daily_energy SET {d}={value} WHERE day = "{date}"'
    log.debug(sql)
    try:
        mc.execute(sql)
    except mariadb.Error as e:
        log.exception(f'Error updating {d} in database: {e}')
        sys.exit(1)
mdb.commit()

# now read the inverter values via modbus/TCP
sedge_list = {
    'SE11400H.inverter.WH': 'solar_inv_pro',
    'SE-RGMTR.ac_meter.TotWhImp': 'solar_inv_imp',
    'SE-RGMTR.ac_meter.TotWhExp': 'solar_inv_exp',
    'SE-MTR.ac_meter.TotWhImp': 'house_imp',
    'SE-MTR.ac_meter.TotWhExp': 'house_exp',
    }

# the solar inverter provides several meters that can read in a single query
solar_edge_inverter_address = '192.168.12.186'          # TODO move to command line parameter?
try:
    system = se.sEdge(solar_edge_inverter_address, 1502)
except RuntimeError as e:
    log.exception('failed to connect to inverter')
    sys.exit(1)
points = {}
for register in sedge_list:
    (device, module, reg) = register.split('.', maxsplit=3)
    try:
        points[register] = se.point(system, device, module, reg)
    except RuntimeError as e:
        log.exception(f'failed to find register {register}')
        continue
try:
    system.refresh_readings()
except RuntimeError as e:
    log.exception('Unable to fetch register data')
    sys.exit(1)

set_params = []
for point in points:
    value = points[point].read_point()[0]
    if value is None:
        log.error('unable to read data for {point}')
        continue
    set_params.append(f'{sedge_list[point]}={value}')

sql = f'UPDATE daily_energy SET {",".join(set_params)} WHERE day="{date}"'
log.debug(sql)
try:
    mc.execute(sql)
except mariadb.Error as e:
    log.exception(f'Error updating inverter values in database: {e}')
    sys.exit(1)
else:
    mdb.commit()

sys.exit(0)

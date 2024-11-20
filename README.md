This project updates a database table daily energy consumption/production/import/export measured by a variety of devices.

### Measurement devices include:
- Peacefair PZEM-004T via pico W
- solarEdge via modbus/TCP

### Devices monitored include:
- solar production
- home utility export
- home utility import
- HVAC condenser consumption
- HVAC evaporator consumption

The table columns include the date of the measurement (primary key) and a column for each device measurement. Null values are used for readings that failed.

The measurement value is the cumulative measured energy value at the time that the value is read. To determine the amount of energy for the day the previous day's value must be subtracted from the day's value

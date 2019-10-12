# petsafe-rpi-feeder

Controls "PetSafe Simply Feed" motor via RPi GPIO, communicates with Home Assistant via MQTT, implementing a switch and sensor. Turning the switch "on" initiates a manual feed. Currently turning the switch "off" is not supported... and wont be supported until I can decide on some mechanisms to prevent starving animals in the case of an accidental deactivation of the feeder.

Installation instructions:

1. Remove SoC from feeder

2. Insert RPi

3. Wire RPi to motor

4. ???
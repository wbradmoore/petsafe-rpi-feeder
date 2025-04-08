#/usr/bin/python3

import sys
import time
import json
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import argparse
import pickle, os

logging.basicConfig(level=logging.INFO)



class Feeder():

  """Controls "PetSafe Simply Feed" motor via RPi GPIO, communicates with Home Assistant via MQTT, implementing a switch and sensor. Turning the switch "on" initiates a manual feed.
  
  Attributes:
      backward (int): GPIO pin to move motor backward
      forward (int): GPIO pin to move motor forward
      ticker (int): GPIO pin of input from motor (cycles on off as motor spins)
      feed_timestamps (list): list of timestamps of recent feedings 
      max_daily_feeds (int): number of times feeds should occur daily
      mqtt_client (paho.mqtt.client: MQTT client for communicating with Home Assistant
      server (str): url[:port] of MQTT server
      username (str): MQTT username
      password (str): MQTT password
  """
  
  def __init__(self,server,username,password):
    """Summary
    
    Args:
        server (str): url[:port] of MQTT server
        username (str): MQTT username
        password (str): MQTT password
    """
    self.server=server
    self.username=username
    self.password=password
    self.switch_state="ON"
    self.button_state="ON"

    mode=GPIO.getmode()

    GPIO.cleanup()

    GPIO.setmode(GPIO.BCM) 

    #turn pinout numbers into words
    self.forward=26
    self.backward=20
    self.ticker=2
    GPIO.setup(self.forward, GPIO.OUT)
    GPIO.setup(self.backward, GPIO.OUT)
    GPIO.setup(self.ticker, GPIO.IN)

    if os.path.exists("feed_timestamps.pickle"):
      self.feed_timestamps = pickle.load( open("feed_timestamps.pickle", "rb") )
      logging.debug("Using existing pickle with timestamps: "+str(self.feed_timestamps))
    else:
      self.feed_timestamps=[]
    self.max_daily_feeds=9

  def mqtt_connect(self):
    """Connect to MQTT client, set callbacks, announce self
    """
    self.mqtt_client = mqtt.Client()
    self.mqtt_client.tls_set(ca_certs="/etc/ssl/certs/ca-certificates.crt")
    self.mqtt_client.username_pw_set(self.username, password=self.password)
    self.mqtt_client.on_connect = self.callback_on_connect
    self.mqtt_client.on_disconnect = self.callback_on_disconnect
    self.mqtt_client.on_message = self.callback_on_message
    if ":" in self.server:
      host=self.server[:self.server.find(":")]
      port=int(self.server[self.server.find(":")+1:])
    else:
      host=self.server
      port=8883  
    self.mqtt_client.connect(host,port,60)
    self.mqtt_client.loop_start()

  def feed(self,x=1):
    """Summary
    
    Args:
        x (TYPE): Number of times to feed
    """
    logging.info("FEEDING: "+str(x))
    for i in range(x):
      GPIO.output(self.forward, GPIO.HIGH)
      logging.debug("Moving forward")
      self.wait_for_pattern("10101",self.ticker)
      GPIO.output(self.forward, GPIO.LOW)
      logging.debug("Done moving forward")
      #now bookkeeping:
      self.button_state={"ON":"OFF","OFF":"ON"}[self.button_state]
      self.feed_timestamps = self.feed_timestamps + [time.time()]
      pickle.dump(self.feed_timestamps, open("feed_timestamps.pickle","wb") )
      self.send_mqtt_update()
      time.sleep(.1)

  def wait_for_pattern(self,pattern_str, gpio_pin):
    """Summary
    
    Args:
        pattern_str (str): The pattern to wait to see on the input pin. (The input pin should be switching between 0 and 1 as the motor spins)
        gpio_pin (int): the input pin
    """
    for index in range(len(pattern_str)):
      logging.debug("Waiting for: "+"-"*index+pattern_str[index:])
      status_int = int(pattern_str[index])
      while(GPIO.input(gpio_pin) != status_int):
        time.sleep(.1)
    logging.info("Motor successfully turned, pattern: "+pattern_str)

  def num_recent_feeds(self,hours=24):
    """
    Returns number of feeds in last hours hours
    """
    num_feeds = len([t for t in self.feed_timestamps if time.time() - t < hours*60*60])
    logging.info(str(num_feeds)+" feeds in the last "+str(hours)+" hours.")
    return num_feeds

  def mqtt_discovery_broadcast(self,available=True):
    """Summary
    
    Args:
        availability (str, optional): Whether feeder is available ("on" or "off")
    """
    logging.info("Announcing for discovery ("+str(available)+")")
    if available:
      payload = json.dumps({
        "name": "feeder",
        "command_topic": "homeassistant/switch/feeder/set",
        "state_topic": "homeassistant/switch/feeder/state"
        })
      self.mqtt_client.publish("homeassistant/switch/feeder/config",payload=payload,qos=0,retain=True)
      payload = json.dumps({
        "name": "feeder_button",
        "command_topic": "homeassistant/switch/feeder_button/set",
        "state_topic": "homeassistant/switch/feeder_button/state"
        })
      self.mqtt_client.publish("homeassistant/switch/feeder_button/config",payload=payload,qos=0,retain=True)
      payload = json.dumps({
        "name": "feeder_24hr_feeds",
        # "device_class": None,
        "state_topic": "homeassistant/sensor/feeder_24hr_feeds/state",
        "unit_of_measurement": " feeds",
        "force_update": True
        })
      self.mqtt_client.publish("homeassistant/sensor/feeder_24hr_feeds/config",payload=payload,qos=0,retain=True)
      payload = json.dumps({
        "name": "feeder_168hr_feeds",
        # "device_class": None,
        "state_topic": "homeassistant/sensor/feeder_168hr_feeds/state",
        "unit_of_measurement": " feeds",
        "force_update": True
        })
      self.mqtt_client.publish("homeassistant/sensor/feeder_168hr_feeds/config",payload=payload,qos=0,retain=True)
    else:
      self.mqtt_client.publish("homeassistant/switch/feeder/config",payload=None,qos=0,retain=True)
      self.mqtt_client.publish("homeassistant/switch/feeder_button/config",payload=None,qos=0,retain=True)
      self.mqtt_client.publish("homeassistant/sensor/feeder_24hr_feeds/config",payload=None,qos=0,retain=True)
      self.mqtt_client.publish("homeassistant/sensor/feeder_168hr_feeds/config",payload=None,qos=0,retain=True)

  def send_mqtt_update(self):
    """Summary
    
    Args:
    """
    self.feed_timestamps = [t for t in self.feed_timestamps if time.time() - t < 240*60*60]
    pickle.dump(self.feed_timestamps, open("feed_timestamps.pickle","wb") )
    lastfeed = len(self.feed_timestamps) and int(max(self.feed_timestamps)) or None

    self.mqtt_client.publish("homeassistant/switch/feeder/state",payload=self.switch_state,qos=0,retain=True)
    self.mqtt_client.publish("homeassistant/switch/feeder_button/state",payload=self.button_state,qos=0,retain=True)
    self.mqtt_client.publish("homeassistant/sensor/feeder_24hr_feeds/state",payload=self.num_recent_feeds(24),qos=0,retain=True)
    self.mqtt_client.publish("homeassistant/sensor/feeder_168hr_feeds/state",payload=self.num_recent_feeds(168),qos=0,retain=True)

  def send_refresh(self):
    """Re-sends all pertinent info to MQTT server
    """
    self.mqtt_discovery_broadcast()
    if self.num_recent_feeds(24) <= 2:
      self.turn_on()
    self.send_mqtt_update()

  def callback_on_connect(self,mqtt_client, userdata, flags, rc):
    """Connect Callback
    """
    logging.info("Connected with result code "+str(rc))
    mqtt_client.subscribe("homeassistant/switch/feeder/set")
    mqtt_client.subscribe("homeassistant/switch/feeder_button/set")
    self.send_refresh()

  def callback_on_disconnect(self,mqtt_client, userdata,rc=0):
    """Disconnect Callback
    """
    logging.warning("Disconnected (rc=%s). The client will try auto-reconnect.", str(rc))

  def callback_on_message(self,mqtt_client, userdata, msg):
    """Message Callback. Handles requests for updates, and manual feed requests
    
    Args:
        msg (utf8 payload): request received via MQTT
    """
    logging.info("Message Received: "+msg.topic+" "+str(msg.payload))
    if msg.topic == "homeassistant/switch/feeder/set":
      try:
        payload_str = msg.payload.decode("utf-8")
      except Exception as e:
        logging.error("Parsing switch payload failed: "+payload_str)
        logging.error(e)
      if payload_str == "ON":
        self.turn_on()
      elif payload_str == "OFF":
        self.turn_off()
    elif msg.topic == "homeassistant/switch/feeder_button/set":
      try:
        payload_str = msg.payload.decode("utf-8")
      except Exception as e:
        logging.error("Parsing button payload failed: "+payload_str)
        logging.error(e)
      if payload_str in ["ON","OFF"]:
        self.feed(1)

  def turn_on(self):
    self.switch_state = 'ON'
    self.send_mqtt_update()

  def turn_off(self):
    self.switch_state = 'OFF'
    self.send_mqtt_update()

  def feed_if_appropriate(self):
    """Handles scheduled feeds. Every time the scheduler calls this, a feed is initiated if the number of feeds in the last 24 hours is not more than the max daily feeds
    """
    if self.switch_state == 'ON':
      if self.num_recent_feeds(24) <= self.max_daily_feeds:
        self.feed(1)
        return
    elif self.num_recent_feeds(48) <= self.max_daily_feeds:
        self.feed(1)
        return

  def shutdown(self):
    """Shutdown cleanly / announce unavailability
    """
    self.send_mqtt_update("off")
    time.sleep(.5)
    self.mqtt_discovery_broadcast(available=False)
    GPIO.cleanup()
    #todo: save feedings to disk

def main(args):
  """Init feeder, init scheduler, then send an update every 30 minutes forever
  """
  print("Starting feeder with args:")
  print("Server: "+args.server)
  print("Username: "+args.username)
  print("Password: "+args.password)
  my_feeder = Feeder(\
    server=args.server,
    username=args.username,\
    password=args.password\
    )
  my_feeder.mqtt_connect()

  sched = BackgroundScheduler()
  @sched.scheduled_job('cron', hour='*')
  def scheduled_job():
    """Summary
    """
    logging.info("RUNNING SCHEDULED JOB - - - - -")
    my_feeder.feed_if_appropriate()
  sched.start()


  while True:
    my_feeder.send_refresh()
    time.sleep(1800)

  # todo; catch sigterm in while True loop above ^
  my_feeder.shutdown()
  exit(0)

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='~~~~~')
  parser.add_argument('-s','--server', help='MQTT server (eg mqtt.aol.com:8883)',required=True)
  parser.add_argument('-u','--username',help='MQTT username', required=True)
  parser.add_argument('-p','--password',help='MQTT password', required=True)
  args = parser.parse_args()
  main(args)

#/usr/bin/python3
import sys
import time
import json
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logging.basicConfig(level=logging.INFO)



class Feeder():

  def __init__(self):
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

    self.feed_timestamps=[]
    self.max_daily_feeds=10

  def mqtt_connect(self):
    #todo: read config externally
    USERNAME="feeder"
    PASSWORD="password"
    HOST="mqtt.example.com"
    PORT=8883
    self.mqtt_client = mqtt.Client()
    self.mqtt_client.tls_set(ca_certs="/etc/ssl/certs/ca-certificates.crt")
    self.mqtt_client.username_pw_set(USERNAME, password=PASSWORD)
    self.mqtt_client.on_connect = self.callback_on_connect
    self.mqtt_client.on_disconnect = self.callback_on_disconnect
    self.mqtt_client.on_message = self.callback_on_message
    self.mqtt_client.connect(HOST, PORT, 60)
    self.mqtt_client.loop_start()
    self.mqtt_update()

  def feed(self,x):
    logging.info("FEEDING: "+str(x))
    for i in range(x):
      GPIO.output(self.forward, GPIO.HIGH)
      logging.debug("Moving forward")
      self.wait_for_pattern("10101",self.ticker)
      GPIO.output(self.forward, GPIO.LOW)
      logging.debug("Done moving forward")
      time.sleep(.1)
      self.feed_timestamps = self.feed_timestamps + [time.time()]
    self.mqtt_update(new_feed=True)

  def wait_for_pattern(self,pattern_str, gpio_pin):
    for index in range(len(pattern_str)):
      logging.debug("Waiting for: "+"-"*index+pattern_str[index:])
      status_int = int(pattern_str[index])
      while(GPIO.input(gpio_pin) != status_int):
        time.sleep(.1)
    logging.info("Motor successfully turned, pattern: "+pattern_str)

  def mqtt_update(self,new_feed=False):
    self.feed_timestamps = [t for t in self.feed_timestamps if time.time() - t < 24*60*60]
    logging.info(str(len(self.feed_timestamps))+" feeds in the last 24 hours.")
    lastfeed = len(self.feed_timestamps) and int(max(self.feed_timestamps)) or None
    payload = json.dumps({
      "type":["update","new_feed"][new_feed],
      "last_feed":lastfeed,
      "next_feed":None,
      "24hr_self.feed_timestamps":self.feed_timestamps
      })
    self.mqtt_client.publish("custom/feeder",payload=payload,qos=0,retain=True)

  def mqtt_update_availability(self,availability="on"):
    logging.info("Announcing availability ("+availability+")")
    payload = json.dumps({
      "availability":availability
      })
    self.mqtt_client.publish("custom/feeder/availability",payload=payload,qos=0,retain=True)

  def mqtt_update_state(self,state="on"):
    logging.info("Announcing state ("+state+")")
    payload = json.dumps({
      "state":state
      })
    self.mqtt_client.publish("custom/feeder/state",payload=payload,qos=0,retain=True)

  def send_refresh(self):
    self.mqtt_update_availability()
    self.mqtt_update_state()

  def callback_on_connect(self,mqtt_client, userdata, flags, rc):
    logging.info("Connected with result code "+str(rc))
    mqtt_client.subscribe("custom/feeder/request")

  def callback_on_disconnect(self,mqtt_client, userdata,rc=0):
    logging.warn("DisConnected result code "+str(rc))
    mqtt_client.loop_stop()

  def callback_on_message(self,mqtt_client, userdata, msg):
    logging.info("Message Received: "+msg.topic+" "+str(msg.payload))
    try:
      payload_str = msg.payload.decode("utf-8")
      payload = json.loads(payload_str)
    except Exception as e:
      logging.error("Parsing payload as JSON failed: "+payload_str)
      logging.error(e)
      return
    if payload["type"] == "feed_request":
      self.feed(1)
    if payload["type"] == "update_request":
      self.mqtt_update()

  def feed_if_appropriate(self):
    if len(self.feed_timestamps) <= self.max_daily_feeds:
      self.feed(1)
    else:
      self.mqtt_update()

  def shutdown(self):
    my_feeder.mqtt_update()
    my_feeder.mqtt_update_availability("off")
    my_feeder.mqtt_update_state("off")
    GPIO.cleanup()
    #todo: save feedings to disk

my_feeder = Feeder()
my_feeder.mqtt_connect()

sched = BackgroundScheduler()
@sched.scheduled_job('cron', hour='*/2')
def scheduled_job():
  logging.info("RUNNING SCHEDULED JOB - - - - -")
  my_feeder.feed_if_appropriate()
sched.start()


while True:
  my_feeder.send_refresh()
  time.sleep(1800)

# todo; catch sigterm in while True loop above ^
my_feeder.shutdown()


#!/usr/bin/python3

import logging
import json
import time
import sys
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
import requests
import geocoder
import asyncio
import os

from bimmer_connected.account import ConnectedDriveAccount
from bimmer_connected.account import MyBMWAccount
from bimmer_connected.api.regions import Regions
from bimmer_connected.vehicle import VehicleViewDirection

### Get the values from environment variables or use default values
TOPIC = "Mobility/" + os.environ.get("TOPIC", "CarName") + "/"
MQTT_SERVER = os.environ.get("MQTT_SERVER", "192.168.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
REGION = os.environ.get("REGION", "REST_OF_WORLD")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

region_mapping = {
    "NORTH_AMERICA": Regions.NORTH_AMERICA,
    "EUROPE": Regions.EUROPE,
    "REST_OF_WORLD": Regions.REST_OF_WORLD
}
REGION = region_mapping.get(REGION, Regions.REST_OF_WORLD)

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    datefmt='%Y-%m-%d %H:%M:%S')

class MQTT_Handler(object):
    def __init__(self):
        self.mqtt_server = MQTT_SERVER
        self.mqtt_port = MQTT_PORT
        self.mqtt_sub_remote_service = TOPIC + "cmd"
        self.mqtt_pub_serviceState = TOPIC + "state"
        self.client = mqtt.Client()

    def on_connect(self, client, userdata, flags, rc):
        logging.info("Connected with result code "+str(rc))
        client.subscribe(self.mqtt_sub_remote_service)
        client.message_callback_add(self.mqtt_sub_remote_service, self.car_execute)
        client.publish(self.mqtt_pub_serviceState, "Online", retain = True)

    def on_disconnect(self, client, userdata, rc):
        logging.info("Disconnected with result code "+str(rc))
        client.publish(self.mqtt_pub_serviceState, "Offline", retain = True)

    def car_execute(self, client, userdata, message):
        logging.info("car_execute: " + message.topic + " " + str(message.payload))
        payload = str(message.payload).strip('\'').split()
        sw = ServiceWrapper(payload[0], payload[1], payload[2], payload[3])
        client.publish(TOPIC + "status", sw.runCmd())

    def run(self):
        # Set MQTT username and password from environment variables if they are defined
        mqtt_username = os.environ.get("MQTT_USERNAME")
        mqtt_password = os.environ.get("MQTT_PASSWORD")
        if mqtt_username and mqtt_password:
            self.client.username_pw_set(username=mqtt_username, password=mqtt_password)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.will_set(self.mqtt_pub_serviceState, "Offline", retain = True)
        self.client.connect(self.mqtt_server, self.mqtt_port, 60)
        self.client.loop_forever()

class ServiceWrapper(object):
    def __init__(self, cmd, username, password, vin):
        self.Cmd = cmd
        self.User = username
        self.Password = password
        self.Region = REGION
        self.VIN = vin

    def runCmd(self):
        if 'state' in self.Cmd.lower() or 'status' in self.Cmd.lower():
            return self.get_status()
        elif 'light' in self.Cmd.lower():
            return self.light_flash()
        elif 'unlock' in self.Cmd.lower():
            return self.unlock_doors()
        elif 'lock' in self.Cmd.lower():
            return self.lock_doors()
        elif 'air' in self.Cmd.lower():
            return self.air_conditioning()
        elif 'horn' in self.Cmd.lower():
            return self.blow_horn()
        elif 'charge' in self.Cmd.lower():
            return self.charge_now()
        else:
            return "{ executionState : INVALID_COMMAND }"

    def get_vehicle(self):
        account = MyBMWAccount(self.User, self.Password, REGION)
        status = asyncio.run(account.get_vehicles())
        return account.get_vehicle(self.VIN)

    def get_status(self):
        """Get the vehicle status."""
        return json.dumps(self.get_vehicle().data, default=lambda o: '<not serializable>')

    def light_flash(self):
        """Trigger the vehicle to flash its lights."""
        vehicle = self.get_vehicle()
        if vehicle:
            status = asyncio.run(vehicle.remote_services.trigger_remote_light_flash())
            return "{ executionState : "+ status.state.value + " }"
        return "{ executionState : INVALID_VIN }"

    def lock_doors(self):
        """Trigger the vehicle to lock its doors."""
        vehicle = self.get_vehicle()
        if vehicle:
            status = asyncio.run(vehicle.remote_services.trigger_remote_door_lock())
            return "{ executionState : "+ status.state.value + " }"
        return "{ executionState : INVALID_VIN }"

    def unlock_doors(self):
        """Trigger the vehicle to unlock its doors."""
        vehicle = self.get_vehicle()
        if vehicle:
            status = asyncio.run(vehicle.remote_services.trigger_remote_door_unlock())
            return "{ executionState : "+ status.state.value + " }"
        return "{ executionState : INVALID_VIN }"

    def air_conditioning(self):
        """Trigger the vehicle to enable air conditioning"""
        vehicle = self.get_vehicle()
        if vehicle:
            status = asyncio.run(vehicle.remote_services.trigger_remote_air_conditioning())
            return "{ executionState : "+ status.state.value + " }"
        return "{ executionState : INVALID_VIN }"

    def blow_horn(self):
        """Trigger the vehicle to blow its horn"""
        vehicle = self.get_vehicle()
        if vehicle:
            status = asyncio.run(vehicle.remote_services.trigger_remote_horn())
            return "{ executionState : "+ status.state.value + " }"
        return "{ executionState : INVALID_VIN }"

    def charge_now(self):
        """Trigger the vehicle to charge now."""
        vehicle = self.get_vehicle()
        if vehicle:
            status = asyncio.run(vehicle.remote_services.trigger_charge_now())
            return "{ executionState : "+ status.state.value + " }"
        return "{ executionState : INVALID_VIN }"

mqtt_handler = MQTT_Handler()
mqtt_handler.run()


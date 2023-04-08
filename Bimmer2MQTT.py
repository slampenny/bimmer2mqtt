#!/usr/bin/python3

import logging
import json
import time
import sys
import paho.mqtt.client as mqtt
import paho.mqtt.publish as mqtt_publish
import requests
import geocoder
import asyncio
import os

from bimmer_connected.account import ConnectedDriveAccount
from bimmer_connected.account import MyBMWAccount
from bimmer_connected.api.regions import Regions
from bimmer_connected.vehicle import VehicleViewDirection

### Get the values from environment variables or use default values
TOPIC = "Mobility/" + os.environ.get("CAR_NAME", "1") + "/"
MQTT_SERVER = os.environ.get("MQTT_SERVER", "192.168.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
REGION = os.environ.get("REGION", "ROW")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

REGION_MAPPING = {
    "NORTH_AMERICA": Regions.NORTH_AMERICA,
    "CHINA": Regions.CHINA,
    "REST_OF_WORLD": Regions.REST_OF_WORLD,
}

REGION = REGION_MAPPING.get(REGION, Regions.REST_OF_WORLD)

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
    
    def on_message(self, client, userdata, message):
        payload = str(message.payload).strip('\'').split()
        sw = self.serviceWrapper.execute_command(payload)
        result = sw.runCmd()
        if result:
            client.publish(TOPIC + "status", result)
    
    def run(self):
        # Set MQTT username and password from environment variables if they are defined
        mqtt_username = os.environ.get("MQTT_USERNAME")
        mqtt_password = os.environ.get("MQTT_PASSWORD")
        if mqtt_username and mqtt_password:
            self.client.username_pw_set(username=mqtt_username, password=mqtt_password)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        
        self.service_wrapper = ServiceWrapper()
        self.client.will_set(self.mqtt_pub_serviceState, "Offline", retain = True)
        self.client.connect(self.mqtt_server, self.mqtt_port, 60)
        self.client.loop_forever()

class ServiceWrapper(object):
    def __init__(self):
        self.User = os.environ.get("BMW_USERNAME")
        self.Password = os.environ.get("BMW_PASSWORD")
        self.Region = REGION
        self.VIN = os.environ.get("VIN")

        logging.info(f"Connecting to BMW account with username {self.User} and password {self.Password}")

        # Get the VIN of the BMW vehicle associated with the specified car name
        account = MyBMWAccount(self.User, self.Password, self.Region)
        try:    
            asyncio.run(account.get_vehicles())
        except MyBMWAccount.APIError as e:
            logging.warning(f"MyBMW API error: {e}")
            return

        self.vehicle = account.get_vehicle(self.VIN)
        self.vehicle.add_observer(self.on_vehicle_update)

        self.mqtt_pub_state = TOPIC + "state"
        self.mqtt_pub_location = TOPIC + "location"

    def execute_command(self, payload):
        if self.VIN is None:
            return "{ executionState : VEHICLE_NOT_FOUND }"

        cmd = payload[0]

        if 'state' in cmd.lower() or 'status' in cmd.lower():
            return self.get_status()
        elif 'light' in cmd.lower():
            return self.light_flash()
        elif 'unlock' in cmd.lower():
            return self.unlock_doors()
        elif 'lock' in cmd.lower():
            return self.lock_doors()
        elif 'air' in cmd.lower():
            return self.air_conditioning()
        elif 'horn' in cmd.lower():
            return self.blow_horn()
        elif 'charge' in cmd.lower():
            return self.charge_now()
        elif 'location' in cmd.lower():
            return self.get_location()
        else:
            return "{ executionState : INVALID_COMMAND }"

    def get_vehicle(self):
        status = asyncio.run(self.account.get_vehicles())
        return self.account.get_vehicle(self.VIN)


    def get_status(self):
        """Get the vehicle status."""
        return json.dumps(self.vehicle.state, default=lambda o: '<not serializable>')

    def on_vehicle_update(self, vehicle):
        """Callback function that is called whenever the vehicle state changes."""
        status = json.dumps(vehicle.state, default=lambda o: '<not serializable>')
        mqtt_publish.single(self.mqtt_pub_state, status, hostname=MQTT_SERVER, port=MQTT_PORT)
    
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

    def get_location(self):
        """Get the vehicle's location."""
        location = self.vehicle.drive_state.position
        lat, lon = location['latitude'], location['longitude']
        g = geocoder.osm([lat, lon], method='reverse')
        address = g.address
        location_data = {'latitude': lat, 'longitude': lon, 'address': address}
        mqtt_payload = json.dumps(location_data)
        mqtt_publish.single(TOPIC + "location", mqtt_payload, hostname=MQTT_SERVER, port=MQTT_PORT)
        return "{ executionState : SUCCESS }"


mqtt_handler = MQTT_Handler()
mqtt_handler.run()


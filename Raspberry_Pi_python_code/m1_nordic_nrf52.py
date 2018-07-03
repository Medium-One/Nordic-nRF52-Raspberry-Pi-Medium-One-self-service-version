from __future__ import division

import json
import struct
import subprocess
from datetime import datetime
from uuid import getnode
import socket
from time import sleep

import requests
from bluepy.btle import *
from requests.exceptions import ConnectionError, ReadTimeout

REST_WRITE_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

LOGIN_INFO = {
    'login_id': 'nordic',
    'password': 'Samplepw1',
    'api_key': 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
}

ENDPOINT = 'https://api-sandbox.mediumone.com'
DEVICE_ADDR = 'ab:cd:ef:gh:ij:kl'
INTERVAL_SECONDS = 5
SLEEP_ON_RESET = 5
DEBUG = False
FIRMWARE_VERSION = '032618a'

BATT_SERVICE = '180F'
HEART_RATE_SERVICE = '180D'

HEART_RATE_CHAR = '2A37'
BODY_SENSOR_LOCATION_CHAR = '2A38'
BATTERY_CHAR = "2a19"


def login(session, login_id, user_pass, api_key, debug = None):
    """
    Logs in to the sandbox as the user passed in
    :param session: Requests session to log in from
    :param login_id: API user to log in as
    :param user_pass: Password
    :param api_key: API key
    :param debug: Optional file to write to if you are in debug mode
    :return: nothing
    """
    user_dict = {
        "login_id": login_id,
        "password": user_pass,
        "api_key": api_key
    }
    if debug:
        debug.write("{}: Logging in. login ID {}, api key {}\n".format(datetime.utcnow(), login_id, api_key))

    session.post('{}/v2/login'.format(ENDPOINT), data=json.dumps(user_dict),
                 headers=REST_WRITE_HEADERS, timeout=30)


def create_event(session, stream, data, add_ip=False, debug = None):
    """
    Sends an event to the sandbox
    :param session: Requests session to post to
    :param stream: Stream to send the data to
    :param data: JSON data
    :param add_ip: String of an IP address. If included, is sent along with the data
    :param debug: Optional file to write to if you are in debug mode
    :return: nothing
    """
    all_data = {"event_data": data}
    if add_ip:
        all_data['add_client_ip'] = add_ip

    data = json.dumps(all_data)
    if debug:
        debug.write("{}: Sending event. data: {}".format(datetime.utcnow(), data))
    response = session.post('{}/v2/events/{}/'.format(ENDPOINT, stream) + LOGIN_INFO['login_id'], data=data,
                            headers=REST_WRITE_HEADERS, timeout = 30)
    if response.status_code != 200:
        login(session, LOGIN_INFO['login_id'], LOGIN_INFO['password'], LOGIN_INFO['api_key'])
        if debug:
            debug.write("{}: Sending event after logging in. data: {}".format(datetime.utcnow(), data))
        response = session.post('{}/v2/events/{}/'.format(ENDPOINT, stream) + LOGIN_INFO['login_id'], data=data,
                                headers=REST_WRITE_HEADERS, timeout = 30)
        if response.status_code != 200:
            print(response.content)
            if debug:
                debug.write("{}: Problem posting to cloud. response: {}".format(datetime.utcnow(), response.content))
            raise ConnectionError("Could not send to cloud, restarting\n")


def twos_comp(val, bits):
    if (val & (1 << (bits - 1))) != 0:
        val -= 1 << bits
    return val


def get_lan_addr():
    """
    This gets the LAN address from ifconfig on a raspberry pi running full rasbian
    :return: String lap address if exists, else None
    """
    p1 = subprocess.Popen("/sbin/ifconfig", stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["grep", "inet addr:"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p3 = subprocess.Popen(["grep", "-v", "127.0.0.1"], stdin=p2.stdout, stdout=subprocess.PIPE)
    p1.stdout.close()
    p2.stdout.close()
    result = p3.communicate()[0]
    p1.wait()
    p2.wait()
    split = result.split('inet addr:')
    if len(split) >=2 :
        addr = split[1].split(' ')
        if len(addr) >= 1:
            return addr[0]
    return None

def get_lan_addr_rpi_lite():
    """
    This gets the LAN address from ifconfig on a raspberry pi running rasbpian lite.
    :return: String lap address if exists, else None
    """
    p1 = subprocess.Popen("/sbin/ifconfig", stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["grep", "inet"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p3 = subprocess.Popen(["grep", "-v", "127.0.0.1"], stdin=p2.stdout, stdout=subprocess.PIPE)
    p4 = subprocess.Popen(["grep", "-v", "inet6"], stdin=p3.stdout, stdout=subprocess.PIPE)
    p1.stdout.close()
    p2.stdout.close()
    p3.stdout.close()
    result = p4.communicate()[0]
    p1.wait()
    p2.wait()
    p3.wait()
    split = result.split('inet ')
    if len(split) >=2 :
        addr = split[1].split(' ')
        if len(addr) >= 1:
            return addr[0]
    return None

def send_initialization_event(session):
    """
    Sends the initialization event to Medium One once the pi has paired with the thundersense.
    :param session:
    :return:
    """
    print(socket.gethostname())
    lan = get_lan_addr()
    if not lan:
        lan = get_lan_addr_rpi_lite()
    initial_event = {
        'connected' : True,
        'lan_ip_address' : lan,
        'mac_address' : getnode(),
        'firmware_version' : FIRMWARE_VERSION,
        'device_id' : DEVICE_ADDR,
    }
    print(initial_event)
    create_event(session, 'device_data', initial_event, add_ip= True)

class HeartRateDelegate(DefaultDelegate):
    """
    This class reads the acceleration data from the board as it comes in as notifications.
    We manually put in a limit of sending max 1 event containing acceleration data to the cloud to avoid using
    too many credits. We also calculate a min, max, and average as the data comes in.
    For more information see: https://ianharvey.github.io/bluepy-doc/delegate.html
    """
    def __init__(self, session, heartRateGATT, debug = None):
        DefaultDelegate.__init__(self)
        self.session = session
        self.motionGATT = heartRateGATT
        self.message = ''
        self.debug = debug

    def handleNotification(self, cHandle, data):
        if cHandle == self.motionGATT and type(data) == str:
            # num_bytes = len(data)
            print(data)
            if (data[0] == '\x14'):
                self.message = "Connection Lost"
            if (data[0] == '\x16'):
                self.message ="success"
                val = str(struct.unpack("B", data[1])[0])
                try:
                    int_val = int(val)
                    json_data = {"heart_rate" : int_val}
                    create_event(self.session, 'sensor_data', json_data)
                except Exception as e:
                    print('failed to convert: ' + e.message)
            if (data[0] == '\x06'):
                self.message = "Booting"

def run(ble, debug=None):
    """
    Once connected to the nordic board, tries to connect to Medium One through the internet. If it cannot connect,
    it will maintain the connection with the nordic board and keep trying to connect to the cloud until it is successful.
    After that, it collects the data and sends it to the cloud as long as the connection is maintained
    :param ble:
    :param debug:
    :return:
    """
    session = requests.session()
    while True: # Keep trying to send init event until you can connect
        try:
            send_initialization_event(session)
            break
        except ConnectionError as ce:
            print("Connection error, resetting session: {}\n".format(ce.message))
            if debug:
                debug.write("Connection error, resetting session: {}\n".format(ce.message))
                debug.flush()
            session.close()
            session = requests.session()
            sleep(INTERVAL_SECONDS)
        except ReadTimeout as re:
            print("Internet connection lost during read, resetting session: {}\n".format(re.message))
            if debug:
                debug.write("Internet connection lost during read, resetting session: {}\n".format(re.message))
                debug.flush()
            session.close()
            session = requests.session()
            sleep(SLEEP_ON_RESET)
    heartRateService = ble.getServiceByUUID(HEART_RATE_SERVICE)
    battService = ble.getServiceByUUID(BATT_SERVICE)

    heart_rate_chars = heartRateService.getCharacteristics(forUUID=HEART_RATE_CHAR)
    bat_chars = battService.getCharacteristics(forUUID=BATTERY_CHAR)

    ble.setDelegate(HeartRateDelegate(requests.session(), heart_rate_chars[0].getHandle(), debug= debug))

    # Turn on acceleration data
    for heart_rate_char in heart_rate_chars:
        if 'NOTIFY' in heart_rate_char.propertiesToString():
            setup_data = b"\x01\x00"
            notify_handle = heart_rate_char.getHandle() + 1
            ble.writeCharacteristic(notify_handle, setup_data, withResponse=True)

    while True:
        # sleep(SLEEP_ON_RESET) # todo is this weird
        json_data = {}
        for bat_char in bat_chars:
            if bat_char.supportsRead():
                bat_data = bat_char.read()
                if type(bat_data) == str:
                    bat_data_value = ord(bat_data[0])
                    json_data['battery'] = bat_data_value

        try:
            create_event(session, 'sensor_data', json_data)
            sleep(INTERVAL_SECONDS)
        except ConnectionError as ce:
            print("Connection error, resetting session: {}\n".format(ce.message))
            if debug:
                debug.write("Connection error, resetting session: {}\n".format(ce.message))
                debug.flush()
            session.close()
            session = requests.session()
            sleep(SLEEP_ON_RESET)
        except ReadTimeout as re:
            print("Internet connection lost during read, resetting session: {}\n".format(re.message))
            if debug:
                debug.write("Internet connection lost during read, resetting session: {}\n".format(re.message))
                debug.flush()
            session.close()
            session = requests.session()
            sleep(SLEEP_ON_RESET)

while True:
    f = open('/m1/debug.txt', 'a') if DEBUG else None
    with open('/m1/login.txt', 'r') as config:
        login_info = config.read().splitlines()
        if len(login_info) >= 2:
            LOGIN_INFO['login_id'] = login_info[0]
            LOGIN_INFO['password'] = login_info[1]
            LOGIN_INFO['api_key'] = login_info[2]
            DEVICE_ADDR = login_info[3]
    ble = Peripheral()

    try:
        while True:
            try:
                ble.connect(DEVICE_ADDR, 'random')
                break
            except BTLEException as be:
                print("Could not connect to device : " + be.message)
                if DEBUG:
                    f.write("{}: Could not connect to device : {}\n".format(datetime.utcnow(), be.message))
                    f.flush()
                sleep(SLEEP_ON_RESET)
        run(ble, debug=f)
    except BTLEException as be:
        print("BTLE Exception: {}. Reconnecting to the board".format(be.message))
        try:
            ble.disconnect()
        except BTLEException as be2:
            print("{}: BTLE exception while disconnecting: {}. Continuing...".format(datetime.utcnow(), be2.message))
        if DEBUG:
            f.write("{}: BTLE Exception: {}. Reconnecting to the board\n".format(datetime.utcnow(), be.message))
            f.flush()
            f.close()
        sleep(SLEEP_ON_RESET)
    except Exception as e:
        err_type = type(e).__name__
        print("Unexpected error of type {}: {}".format(err_type, e.message))
        try:
            ble.disconnect()
        except BTLEException as be2:
            print("{}: BTLE exception while disconnecting after unexepcted error: {}. Continuing...".format(datetime.utcnow(), be2.message))
        if DEBUG:
            f.write("{}: Unexpected error of type {}: {}\n".format(datetime.utcnow(), err_type, e.message))
            f.flush()
            f.close()
        sleep(SLEEP_ON_RESET)

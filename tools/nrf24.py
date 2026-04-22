'''
  Python 3 port of Bastille Networks' nrf24.py (tools/lib/nrf24.py).
  Original: Copyright (C) 2016 Bastille Networks, GPLv3.
  Changes: Python 3 syntax, bytes vs str handling, libusb_package backend.
'''

import logging
import usb
import usb.core

try:
    import libusb_package
    _backend = libusb_package.get_libusb1_backend()
except ImportError:
    _backend = None


TRANSMIT_PAYLOAD               = 0x04
ENTER_SNIFFER_MODE             = 0x05
ENTER_PROMISCUOUS_MODE         = 0x06
ENTER_TONE_TEST_MODE           = 0x07
TRANSMIT_ACK_PAYLOAD           = 0x08
SET_CHANNEL                    = 0x09
GET_CHANNEL                    = 0x0A
ENABLE_LNA_PA                  = 0x0B
TRANSMIT_PAYLOAD_GENERIC       = 0x0C
ENTER_PROMISCUOUS_MODE_GENERIC = 0x0D
RECEIVE_PAYLOAD                = 0x12

RF_CH = 0x05

RF_RATE_250K = 0
RF_RATE_1M   = 1
RF_RATE_2M   = 2


def _to_ints(data):
    """Accept bytes, list[int], str (ASCII) — return list[int]."""
    if isinstance(data, (bytes, bytearray)):
        return list(data)
    if isinstance(data, str):
        return [ord(c) for c in data]
    return [int(x) for x in data]


class nrf24:

    usb_timeout = 2500

    def __init__(self, index=0):
        try:
            dongles = list(usb.core.find(idVendor=0x1915, idProduct=0x0102,
                                         find_all=True, backend=_backend))
            if not dongles:
                raise Exception('Cannot find USB dongle (1915:0102 not present — flash and Zadig done?).')
            self.dongle = dongles[index]
            self.dongle.set_configuration()
        except usb.core.USBError as ex:
            raise ex

    def enter_promiscuous_mode(self, prefix=b''):
        prefix_ints = _to_ints(prefix)
        self.send_usb_command(ENTER_PROMISCUOUS_MODE, [len(prefix_ints)] + prefix_ints)
        self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)
        if prefix_ints:
            logging.debug('Entered promiscuous mode with address prefix {0}'.format(
                ':'.join('{:02X}'.format(b) for b in prefix_ints)))
        else:
            logging.debug('Entered promiscuous mode')

    def enter_promiscuous_mode_generic(self, prefix=b'', rate=RF_RATE_2M, payload_length=32):
        prefix_ints = _to_ints(prefix)
        self.send_usb_command(ENTER_PROMISCUOUS_MODE_GENERIC,
                              [len(prefix_ints), rate, payload_length] + prefix_ints)
        self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)
        if prefix_ints:
            logging.debug('Entered generic promiscuous mode with address prefix {0}'.format(
                ':'.join('{:02X}'.format(b) for b in prefix_ints)))
        else:
            logging.debug('Entered promiscuous mode')

    def enter_sniffer_mode(self, address):
        address_ints = _to_ints(address)
        self.send_usb_command(ENTER_SNIFFER_MODE, [len(address_ints)] + address_ints)
        self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)
        logging.debug('Entered sniffer mode with address {0}'.format(
            ':'.join('{:02X}'.format(b) for b in reversed(address_ints))))

    def enter_tone_test_mode(self):
        self.send_usb_command(ENTER_TONE_TEST_MODE, [])
        self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)
        logging.debug('Entered continuous tone test mode')

    def receive_payload(self):
        self.send_usb_command(RECEIVE_PAYLOAD, [])
        return self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)

    def transmit_payload_generic(self, payload, address=b"\x33\x33\x33\x33\x33"):
        pl = _to_ints(payload)
        ad = _to_ints(address)
        data = [len(pl), len(ad)] + pl + ad
        self.send_usb_command(TRANSMIT_PAYLOAD_GENERIC, data)
        return self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)[0] > 0

    def transmit_payload(self, payload, timeout=4, retransmits=15):
        pl = _to_ints(payload)
        data = [len(pl), timeout, retransmits] + pl
        self.send_usb_command(TRANSMIT_PAYLOAD, data)
        return self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)[0] > 0

    def transmit_ack_payload(self, payload):
        pl = _to_ints(payload)
        data = [len(pl)] + pl
        self.send_usb_command(TRANSMIT_ACK_PAYLOAD, data)
        return self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)[0] > 0

    def set_channel(self, channel):
        if channel > 125:
            channel = 125
        self.send_usb_command(SET_CHANNEL, [channel])
        self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)
        logging.debug('Tuned to {0}'.format(channel))

    def get_channel(self):
        self.send_usb_command(GET_CHANNEL, [])
        return self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)

    def enable_lna(self):
        self.send_usb_command(ENABLE_LNA_PA, [])
        self.dongle.read(0x81, 64, timeout=nrf24.usb_timeout)

    def send_usb_command(self, request, data):
        self.dongle.write(0x01, [request] + list(data), timeout=nrf24.usb_timeout)

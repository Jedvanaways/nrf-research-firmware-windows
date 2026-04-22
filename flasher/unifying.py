'''
  Python 3 port of Bastille Networks' unifying.py
  Original: Copyright (C) 2016 Bastille Networks, GPLv3.
  Changes: Python 3 syntax (print fn, `as`-except), bytes literals for
  USB control-transfer payloads, libusb_package backend for Windows.
'''

import logging
import sys
import time

import usb
import usb.core

try:
    import libusb_package
    _backend = libusb_package.get_libusb1_backend()
except ImportError:
    _backend = None

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s.%(msecs)03d]  %(message)s',
    datefmt="%Y-%m-%d %H:%M:%S",
)

usb_timeout = 2500


def _find(idVendor, idProduct):
    return usb.core.find(idVendor=idVendor, idProduct=idProduct, backend=_backend)


class unifying_dongle:

    def __init__(self):
        self.dongle = _find(0x046d, 0xc52b)
        if self.dongle:
            logging.info("Found Logitech Unifying dongle - HID mode")

            logging.info("Detaching kernel driver from Logitech dongle - HID mode")
            for ep in range(3):
                try:
                    if self.dongle.is_kernel_driver_active(ep):
                        self.dongle.detach_kernel_driver(ep)
                except (NotImplementedError, usb.core.USBError):
                    pass

            self.dongle.set_configuration()
            self.enter_firmware_update_mode()
            return

        self.dongle = _find(0x1915, 0x0102)
        if self.dongle:
            logging.info("Found dongle with research firmware, attempting to load Logitech bootloader")
            self.dongle.set_configuration()
            self.dongle.write(0x01, b"\xFE", timeout=usb_timeout)
            try:
                self.dongle.reset()
            except usb.core.USBError:
                pass

            start = time.time()
            while time.time() - start < 5:
                try:
                    self.dongle = _find(0x046d, 0xaaaa)
                    if self.dongle:
                        logging.info("Found Logitech Unifying dongle - firmware update mode")
                        for ep in range(3):
                            try:
                                if self.dongle.is_kernel_driver_active(ep):
                                    self.dongle.detach_kernel_driver(ep)
                            except (NotImplementedError, usb.core.USBError):
                                pass
                        self.dongle.set_configuration(1)
                        break
                except AttributeError:
                    continue

            if not self.dongle:
                raise Exception("Dongle failed to reset into firmware update mode")

        else:
            self.dongle = _find(0x046d, 0xaaaa)
            if not self.dongle:
                raise Exception("Unable to find Logitech Unifying USB dongle.")

            for ep in range(3):
                try:
                    if self.dongle.is_kernel_driver_active(ep):
                        self.dongle.detach_kernel_driver(ep)
                except (NotImplementedError, usb.core.USBError):
                    pass

            self.dongle.set_configuration()

    def enter_firmware_update_mode(self):
        logging.info("Putting dongle into firmware update mode")

        try:
            self.send_command(0x21, 0x09, 0x0210, 0x0002,
                              b"\x10\xFF\x81\xF1\x00\x00\x00", ep=0x83)
        except Exception:
            pass

        response = self.send_command(0x21, 0x09, 0x0210, 0x0002,
                                     b"\x10\xFF\x81\xF1\x01\x00\x00", ep=0x83)
        if response[5] != 0x12:
            logging.info('Incompatible Logitech Unifying dongle (type {:02X}). '
                         'Only Nordic Semiconductor based dongles are supported.'.format(response[5]))
            sys.exit(1)

        try:
            self.send_command(0x21, 0x09, 0x0210, 0x0002,
                              b"\x10\xFF\x80\xF0\x49\x43\x50", ep=0x83)
        except usb.core.USBError:
            pass

        start = time.time()
        while time.time() - start < 5:
            try:
                self.dongle = _find(0x046d, 0xaaaa)
                if self.dongle:
                    logging.info("Found Logitech Unifying dongle - firmware update mode")
                    for ep in range(3):
                        try:
                            if self.dongle.is_kernel_driver_active(ep):
                                self.dongle.detach_kernel_driver(ep)
                        except (NotImplementedError, usb.core.USBError):
                            pass
                    self.dongle.set_configuration(1)
                    break
            except AttributeError:
                continue

        if not self.dongle:
            raise Exception("Dongle failed to reset into firmware update mode")

    def send_command(self, request_type, request, value, index, data,
                     ep=0x81, timeout=usb_timeout):
        self.dongle.ctrl_transfer(request_type, request, value, index, data, timeout=timeout)
        response = self.dongle.read(ep, 32, timeout=timeout)
        logging.info(':'.join("{:02X}".format(c) for c in response))
        return response

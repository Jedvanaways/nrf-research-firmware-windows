#!/usr/bin/env python3
'''
  Python 3 port of Bastille Networks' logitech-usb-restore.py
  Restores the original Logitech firmware (RQR012 .hex file) to the dongle.
  Original: Copyright (C) 2016 Bastille Networks, GPLv3.
'''

import logging
import sys

from unifying import unifying_dongle


def main():
    if len(sys.argv) < 2:
        print("Usage: logitech-usb-restore.py [original-firmware.hex]")
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        lines = f.readlines()
    lines = [line.strip()[1:] for line in lines]
    lines = [line[2:6] + line[0:2] + line[8:-2] for line in lines]
    lines = ["20" + line + "0" * (62 - len(line)) for line in lines]
    payloads = [bytes.fromhex(line) for line in lines]
    p0 = payloads[0]
    payloads[0] = p0[0:2] + bytes([p0[2] + 1, p0[3] - 1]) + p0[5:]

    dongle = unifying_dongle()

    logging.info("Initializing firmware update")
    dongle.send_command(0x21, 0x09, 0x0200, 0x0000, b"\x80" + b"\x00" * 31)

    logging.info("Clearing existing flash memory up to bootloader")
    for x in range(0, 0x70, 2):
        dongle.send_command(0x21, 0x09, 0x0200, 0x0000,
                            b"\x30" + bytes([x]) + b"\x00\x01" + b"\x00" * 28)

    logging.info("Transferring the new firmware")
    for payload in payloads:
        dongle.send_command(0x21, 0x09, 0x0200, 0x0000, payload)
    dongle.send_command(0x21, 0x09, 0x0200, 0x0000, payloads[0])

    logging.info("Mark firmware update as completed")
    dongle.send_command(0x21, 0x09, 0x0200, 0x0000,
                        b"\x20\x00\x00\x01\x02" + b"\x00" * 27)

    logging.info("Restarting dongle")
    dongle.send_command(0x21, 0x09, 0x0200, 0x0000, b"\x70" + b"\x00" * 31)


if __name__ == "__main__":
    main()

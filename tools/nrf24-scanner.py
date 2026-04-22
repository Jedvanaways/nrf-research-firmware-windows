#!/usr/bin/env python3
'''
  Python 3 port of Bastille Networks' nrf24-scanner.py.
  Original: Copyright (C) 2016 Bastille Networks, GPLv3.
'''

import logging
import time

import common


def main():
    common.init_args('./nrf24-scanner.py')
    common.parser.add_argument('-p', '--prefix', type=str,
                               help='Promiscuous mode address prefix (hex, e.g. AA:BB or AABB)',
                               default='')
    common.parser.add_argument('-d', '--dwell', type=float,
                               help='Dwell time per channel, in milliseconds', default=100.0)
    common.parse_and_init()

    prefix_address = bytes.fromhex(common.args.prefix.replace(':', ''))
    if len(prefix_address) > 5:
        raise Exception('Invalid prefix address (max 5 bytes): {0}'.format(common.args.prefix))

    common.radio.enter_promiscuous_mode(prefix_address)

    dwell_time = common.args.dwell / 1000.0

    common.radio.set_channel(common.channels[0])

    last_tune = time.time()
    channel_index = 0
    while True:
        if len(common.channels) > 1 and time.time() - last_tune > dwell_time:
            channel_index = (channel_index + 1) % len(common.channels)
            common.radio.set_channel(common.channels[channel_index])
            last_tune = time.time()

        value = common.radio.receive_payload()
        if len(value) >= 5:
            address, payload = value[0:5], value[5:]
            logging.info('{0: >2}  {1: >2}  {2}  {3}'.format(
                common.channels[channel_index],
                len(payload),
                ':'.join('{:02X}'.format(b) for b in address),
                ':'.join('{:02X}'.format(b) for b in payload)))


if __name__ == '__main__':
    main()

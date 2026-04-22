#!/usr/bin/env python3
'''
  Python 3 port of Bastille Networks' nrf24-sniffer.py.
  Original: Copyright (C) 2016 Bastille Networks, GPLv3.
'''

import logging
import time

import common


def main():
    common.init_args('./nrf24-sniffer.py')
    common.parser.add_argument('-a', '--address', type=str,
                               help='Address to sniff, following as it changes channels',
                               required=True)
    common.parser.add_argument('-t', '--timeout', type=float,
                               help='Channel timeout, in milliseconds', default=100)
    common.parser.add_argument('-k', '--ack_timeout', type=int,
                               help='ACK timeout in microseconds [250,4000], step 250',
                               default=250)
    common.parser.add_argument('-r', '--retries', type=int,
                               help='Auto retry limit [0,15]',
                               default=1, choices=range(0, 16), metavar='RETRIES')
    common.parser.add_argument('-p', '--ping_payload', type=str,
                               help='Ping payload, ex 0F:0F:0F:0F',
                               default='0F:0F:0F:0F', metavar='PING_PAYLOAD')
    common.parse_and_init()

    raw = bytes.fromhex(common.args.address.replace(':', ''))
    address = raw[::-1][:5]
    address_string = ':'.join('{:02X}'.format(b) for b in address[::-1])
    if len(address) < 2:
        raise Exception('Invalid address: {0}'.format(common.args.address))

    common.radio.enter_sniffer_mode(address)

    timeout = common.args.timeout / 1000.0
    ping_payload = bytes.fromhex(common.args.ping_payload.replace(':', ''))

    ack_timeout = max(0, min(int(common.args.ack_timeout / 250) - 1, 15))
    retries = max(0, min(common.args.retries, 15))

    last_ping = time.time()
    channel_index = 0
    while True:
        if time.time() - last_ping > timeout:
            if not common.radio.transmit_payload(ping_payload, ack_timeout, retries):
                success = False
                for channel_index in range(len(common.channels)):
                    common.radio.set_channel(common.channels[channel_index])
                    if common.radio.transmit_payload(ping_payload, ack_timeout, retries):
                        last_ping = time.time()
                        logging.debug('Ping success on channel {0}'.format(common.channels[channel_index]))
                        success = True
                        break
                if not success:
                    logging.debug('Unable to ping {0}'.format(address_string))
            else:
                logging.debug('Ping success on channel {0}'.format(common.channels[channel_index]))
                last_ping = time.time()

        value = common.radio.receive_payload()
        if value[0] == 0:
            last_ping = time.time()
            payload = value[1:]
            logging.info('{0: >2}  {1: >2}  {2}  {3}'.format(
                common.channels[channel_index],
                len(payload),
                address_string,
                ':'.join('{:02X}'.format(b) for b in payload)))


if __name__ == '__main__':
    main()

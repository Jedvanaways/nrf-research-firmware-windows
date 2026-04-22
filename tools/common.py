'''
  Python 3 port of Bastille Networks' common.py (tools/lib/common.py).
  Original: Copyright (C) 2016 Bastille Networks, GPLv3.
'''

import argparse
import logging

from nrf24 import nrf24

channels = []
args = None
parser = None
radio = None


def init_args(description):
    global parser
    parser = argparse.ArgumentParser(
        description,
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=50, width=120),
    )
    parser.add_argument('-c', '--channels', type=int, nargs='+',
                        help='RF channels', default=list(range(2, 84)), metavar='N')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output', default=False)
    parser.add_argument('-l', '--lna', action='store_true',
                        help='Enable the LNA (for CrazyRadio PA dongles)', default=False)
    parser.add_argument('-i', '--index', type=int, help='Dongle index', default=0)


def parse_and_init():
    global parser, args, channels, radio

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level,
                        format='[%(asctime)s.%(msecs)03d]  %(message)s',
                        datefmt="%Y-%m-%d %H:%M:%S")

    channels = args.channels
    logging.debug('Using channels {0}'.format(', '.join(str(c) for c in channels)))

    radio = nrf24(args.index)
    if args.lna:
        radio.enable_lna()

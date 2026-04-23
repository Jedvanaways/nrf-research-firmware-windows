#!/usr/bin/env python3
"""
Mock external-adapter transmitter.

Pretends to be an ESP32+LT8910 sending captured packets to the web app.
Useful for testing the UI, Learn mode, and recordings without real hardware.

Usage:
  py external-adapters/mock-transmitter.py
  py external-adapters/mock-transmitter.py --host 127.0.0.1 --port 8787
  py external-adapters/mock-transmitter.py --rate 5   # 5 packets per second
"""

from __future__ import annotations

import argparse
import random
import time
import urllib.error
import urllib.request
import json


def send(url: str, packet: dict) -> None:
    data = json.dumps(packet).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"POST failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--rate", type=float, default=2.0,
                        help="Packets per second (default 2)")
    parser.add_argument("--source", default="mock-lt8910",
                        help="Source label shown in the UI")
    args = parser.parse_args()

    endpoint = f"http://{args.host}:{args.port}/api/external/packet"
    interval = 1.0 / args.rate

    # Simulate a real-looking ThermaSleep-ish device: two addresses dominating,
    # one "base station" and one "remote", each with a small set of payloads
    # that rotate through button presses.
    addrs = ["AA:BB:CC:DD:EE", "11:22:33:44:55"]
    payloads_by_addr = {
        "AA:BB:CC:DD:EE": [
            "01:10:00:22:FF:A5",    # temp up
            "01:10:00:23:FF:A4",    # temp down
            "01:10:00:24:FF:A3",    # power on
            "01:10:00:25:FF:A2",    # power off
        ],
        "11:22:33:44:55": [
            "AA:55:01:FF",          # heartbeat
            "AA:55:02:FF",
        ],
    }

    # On Windows, console default codec is cp1252 which chokes on non-ASCII;
    # force UTF-8 when we can.
    try:
        import sys as _sys
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"Mock transmitter -> {endpoint}")
    print(f"Rate: {args.rate} pkt/s  source='{args.source}'")
    print("Press Ctrl-C to stop.")

    try:
        while True:
            addr = random.choices(addrs, weights=[0.7, 0.3])[0]
            payload = random.choice(payloads_by_addr[addr])
            ch = random.choice([42, 42, 42, 43, 41])  # mostly ch 42
            send(endpoint, {
                "source": args.source,
                "addr": addr,
                "payload": payload,
                "ch": ch,
                "rssi": random.randint(-70, -40),
            })
            time.sleep(interval)
    except KeyboardInterrupt:
        print("stopped.")


if __name__ == "__main__":
    main()

"""
Dedicated worker thread that owns the nRF24 receiver for its lifetime.

Design:
  - FastAPI handlers never touch the radio directly.
  - Handlers post Command objects to `command_queue`.
  - Worker runs a small state machine (IDLE / SCANNING / SNIFFING).
  - Events (packets, mode changes, channel ticks, errors) are pushed to the
    asyncio side via loop.call_soon_threadsafe(), which places them on
    `event_queue`.
  - The HTTP layer consumes `event_queue` and fans events out to WebSocket
    clients.
  - Recording is orthogonal: a RecordingTee can be attached/detached at any
    time and writes events to a JSONL file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Make the sibling `tools/` package importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from tools.nrf24 import nrf24 as Nrf24  # noqa: E402  (path hack above)

log = logging.getLogger("radio_worker")


# -----------------------------------------------------------------------------
# Commands (HTTP → worker)
# -----------------------------------------------------------------------------


@dataclass
class Command:
    name: str
    params: dict = field(default_factory=dict)


# -----------------------------------------------------------------------------
# Event helper
# -----------------------------------------------------------------------------


def _event(type_: str, **fields) -> dict:
    ev = {"type": type_, "t": time.time()}
    ev.update(fields)
    return ev


# -----------------------------------------------------------------------------
# Recording tee
# -----------------------------------------------------------------------------


class RecordingTee:
    """
    Write structured events to a JSON-Lines file. Thread-safe because the
    worker thread is the only writer. File handle is flushed after every
    record so crashes don't lose data.
    """

    def __init__(self, path: Path, device_id: str) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("w", encoding="utf-8")
        header = {
            "type": "header",
            "version": 1,
            "started": datetime.now(timezone.utc).isoformat(),
            "device": device_id,
        }
        self._fh.write(json.dumps(header) + "\n")
        self._fh.flush()

    def write(self, event: dict) -> None:
        try:
            self._fh.write(json.dumps(event) + "\n")
            self._fh.flush()
        except Exception:
            log.exception("recording write failed")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Worker thread
# -----------------------------------------------------------------------------


class RadioWorker(threading.Thread):

    IDLE = "idle"
    SCANNING = "scanning"
    SNIFFING = "sniffing"
    TRANSMITTING = "transmitting"

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(daemon=True, name="radio-worker")
        self.loop = loop
        self.command_queue: queue.Queue[Command] = queue.Queue()
        self.event_queue: asyncio.Queue[dict] = asyncio.Queue()

        self.mode = self.IDLE
        self.connected = False
        self.current_channel: Optional[int] = None
        self.packet_count = 0
        self.started_at = time.time()

        self._radio: Optional[Nrf24] = None
        self._stop_requested = False
        self._recording: Optional[RecordingTee] = None
        self._recording_path: Optional[Path] = None

        # Ring buffer of recent events (packets, channels, etc.) for the AI
        # assistant and anyone else who wants a historical window without
        # subscribing to the WS stream. Thread-safe via deque's C impl.
        self.recent_events: deque[dict] = deque(maxlen=5000)

        # Scan state
        self._scan_channels: list[int] = []
        self._scan_dwell_s: float = 0.1
        self._scan_prefix: bytes = b""

        # Sniff state
        self._sniff_address: bytes = b""
        self._sniff_address_str: str = ""
        self._sniff_timeout_s: float = 0.1
        self._sniff_ack_timeout_raw: int = 0
        self._sniff_retries: int = 1
        self._sniff_ping_payload: bytes = bytes.fromhex("0F0F0F0F")

    # -------------------------------------------------------------- events --

    def _emit(self, event: dict) -> None:
        """
        Push an event to the asyncio side AND to the recording tee if active
        AND to the in-memory ring buffer. Safe to call from the worker thread.
        """
        if self._recording is not None:
            self._recording.write(event)

        self.recent_events.append(event)

        try:
            self.loop.call_soon_threadsafe(self.event_queue.put_nowait, event)
        except RuntimeError:
            # Loop has been closed — shutting down.
            pass

    # --------------------------------------------------------- radio lifecycle --

    def _connect_radio(self) -> None:
        try:
            self._radio = Nrf24()
            self.connected = True
            self._emit(_event("status", connected=True, mode=self.mode,
                              channel=self.current_channel,
                              message="radio opened"))
            log.info("radio opened: 1915:0102")
        except Exception as exc:
            self.connected = False
            self._radio = None
            self._emit(_event("error", where="connect", detail=str(exc)))
            log.exception("failed to open radio")

    def _reconnect_radio(self) -> None:
        if self._radio is not None:
            try:
                import usb.util
                usb.util.dispose_resources(self._radio.dongle)
            except Exception:
                log.debug("dispose_resources failed", exc_info=True)
            self._radio = None
            # Give Windows/WinUSB a beat to free the handle before reopen.
            time.sleep(0.3)
        self._connect_radio()

    # ------------------------------------------------------------- run loop --

    def run(self) -> None:
        self._connect_radio()

        while True:
            # Service commands between mode ticks.
            try:
                cmd: Optional[Command] = self.command_queue.get(timeout=0.05)
            except queue.Empty:
                cmd = None

            if cmd is not None:
                self._handle_command(cmd)

            if not self.connected:
                # Without a radio we can't do anything useful; idle-spin.
                time.sleep(0.2)
                continue

            if self.mode == self.SCANNING:
                self._scan_tick()
            elif self.mode == self.SNIFFING:
                self._sniff_tick()
            # IDLE and TRANSMITTING are handled inside _handle_command.

    # --------------------------------------------------------- command dispatch --

    def _handle_command(self, cmd: Command) -> None:
        log.debug("command: %s %s", cmd.name, cmd.params)
        try:
            if cmd.name == "scan_start":
                self._start_scan(cmd.params)
            elif cmd.name == "sniff_start":
                self._start_sniff(cmd.params)
            elif cmd.name == "transmit":
                self._do_transmit(cmd.params)
            elif cmd.name == "stop":
                self._set_mode(self.IDLE)
            elif cmd.name == "recording_start":
                self._start_recording(cmd.params)
            elif cmd.name == "recording_stop":
                self._stop_recording()
            elif cmd.name == "reconnect":
                self._reconnect_radio()
        except Exception as exc:
            log.exception("command failed: %s", cmd.name)
            self._emit(_event("error", where=cmd.name, detail=str(exc)))
            self._set_mode(self.IDLE)

    def _set_mode(self, new_mode: str) -> None:
        if new_mode == self.mode:
            return
        self.mode = new_mode
        self._emit(_event("mode", mode=new_mode))
        log.info("mode → %s", new_mode)

    # ------------------------------------------------------------- scanning --

    def _start_scan(self, params: dict) -> None:
        if self._radio is None:
            raise RuntimeError("radio not connected")

        channels = params.get("channels") or list(range(2, 84))
        dwell_ms = float(params.get("dwell_ms", 100))
        prefix_hex = (params.get("prefix") or "").replace(":", "")
        prefix = bytes.fromhex(prefix_hex) if prefix_hex else b""
        if len(prefix) > 5:
            raise ValueError("prefix address max 5 bytes")

        self._scan_channels = [int(c) for c in channels]
        self._scan_dwell_s = dwell_ms / 1000.0
        self._scan_prefix = prefix
        self._scan_index = 0
        self._scan_last_tune = time.time()

        self._radio.enter_promiscuous_mode(prefix)
        self._radio.set_channel(self._scan_channels[0])
        self.current_channel = self._scan_channels[0]
        self._emit(_event("channel", channel=self.current_channel))
        self._set_mode(self.SCANNING)

    def _scan_tick(self) -> None:
        # Channel hop if dwell elapsed.
        if (len(self._scan_channels) > 1
                and time.time() - self._scan_last_tune > self._scan_dwell_s):
            self._scan_index = (self._scan_index + 1) % len(self._scan_channels)
            ch = self._scan_channels[self._scan_index]
            self._radio.set_channel(ch)
            self.current_channel = ch
            self._scan_last_tune = time.time()
            self._emit(_event("channel", channel=ch))

        try:
            value = self._radio.receive_payload()
        except Exception as exc:
            self._emit(_event("error", where="scan_rx", detail=str(exc)))
            self._set_mode(self.IDLE)
            self.connected = False
            return

        if len(value) >= 5:
            address = bytes(value[0:5])
            payload = bytes(value[5:])
            self.packet_count += 1
            self._emit(_event(
                "packet",
                mode="scan",
                ch=self.current_channel,
                addr=":".join(f"{b:02X}" for b in address),
                payload=":".join(f"{b:02X}" for b in payload),
                length=len(payload),
            ))

    # ------------------------------------------------------------- sniffing --

    def _start_sniff(self, params: dict) -> None:
        if self._radio is None:
            raise RuntimeError("radio not connected")

        addr_str = params.get("address", "")
        raw = bytes.fromhex(addr_str.replace(":", ""))
        address = raw[::-1][:5]
        if len(address) < 2:
            raise ValueError("address must be at least 2 bytes")

        timeout_ms = float(params.get("timeout_ms", 100))
        ack_timeout_us = int(params.get("ack_timeout_us", 250))
        retries = int(params.get("retries", 1))
        ping_hex = (params.get("ping_payload") or "0F0F0F0F").replace(":", "")

        self._sniff_address = address
        self._sniff_address_str = ":".join(f"{b:02X}" for b in address[::-1])
        self._sniff_timeout_s = timeout_ms / 1000.0
        self._sniff_ack_timeout_raw = max(0, min(int(ack_timeout_us / 250) - 1, 15))
        self._sniff_retries = max(0, min(retries, 15))
        self._sniff_ping_payload = bytes.fromhex(ping_hex)

        # Use the caller-supplied channel list or default to scan range.
        channels = params.get("channels") or list(range(2, 84))
        self._scan_channels = [int(c) for c in channels]
        self._scan_index = 0

        self._radio.enter_sniffer_mode(address)
        self._radio.set_channel(self._scan_channels[0])
        self.current_channel = self._scan_channels[0]
        self._sniff_last_ping = time.time()
        self._emit(_event("channel", channel=self.current_channel))
        self._set_mode(self.SNIFFING)

    def _sniff_tick(self) -> None:
        # Ping-based channel following — mirrors nrf24-sniffer.py.
        if time.time() - self._sniff_last_ping > self._sniff_timeout_s:
            try:
                ok = self._radio.transmit_payload(
                    self._sniff_ping_payload,
                    self._sniff_ack_timeout_raw,
                    self._sniff_retries,
                )
            except Exception as exc:
                self._emit(_event("error", where="sniff_ping", detail=str(exc)))
                self._set_mode(self.IDLE)
                self.connected = False
                return

            if not ok:
                # Sweep all channels until the target acks.
                found = False
                for i in range(len(self._scan_channels)):
                    ch = self._scan_channels[i]
                    self._radio.set_channel(ch)
                    self.current_channel = ch
                    self._emit(_event("channel", channel=ch))
                    try:
                        if self._radio.transmit_payload(
                            self._sniff_ping_payload,
                            self._sniff_ack_timeout_raw,
                            self._sniff_retries,
                        ):
                            self._scan_index = i
                            found = True
                            break
                    except Exception:
                        continue
                if found:
                    self._sniff_last_ping = time.time()
            else:
                self._sniff_last_ping = time.time()

        try:
            value = self._radio.receive_payload()
        except Exception as exc:
            self._emit(_event("error", where="sniff_rx", detail=str(exc)))
            self._set_mode(self.IDLE)
            self.connected = False
            return

        if value and value[0] == 0:
            payload = bytes(value[1:])
            self.packet_count += 1
            self._sniff_last_ping = time.time()
            self._emit(_event(
                "packet",
                mode="sniff",
                ch=self.current_channel,
                addr=self._sniff_address_str,
                payload=":".join(f"{b:02X}" for b in payload),
                length=len(payload),
            ))

    # ----------------------------------------------------------- transmit --

    def _do_transmit(self, params: dict) -> None:
        if self._radio is None:
            raise RuntimeError("radio not connected")
        if self.mode != self.IDLE:
            raise RuntimeError(f"radio busy ({self.mode})")

        self._set_mode(self.TRANSMITTING)
        try:
            payload = bytes.fromhex((params.get("payload_hex", "")).replace(":", ""))
            address_str = params.get("address") or ""
            address = bytes.fromhex(address_str.replace(":", ""))[::-1][:5]

            mode = params.get("mode", "esb")  # "esb" or "generic"
            retries = int(params.get("retries", 5))

            # For ESB the radio should be in sniffer mode on the target address.
            if mode == "esb":
                self._radio.enter_sniffer_mode(address)
                ok = self._radio.transmit_payload(payload, 4, retries)
            else:
                ok = self._radio.transmit_payload_generic(payload, address)

            self._emit(_event(
                "transmit_result",
                ok=bool(ok),
                addr=":".join(f"{b:02X}" for b in address[::-1]),
                payload=":".join(f"{b:02X}" for b in payload),
                mode=mode,
            ))
        finally:
            self._set_mode(self.IDLE)

    # ---------------------------------------------------------- recording --

    def _start_recording(self, params: dict) -> None:
        if self._recording is not None:
            raise RuntimeError("already recording")
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = params.get("filename") or f"{stamp}.jsonl"
        # Strip any path separators caller may have passed.
        filename = Path(filename).name
        path = _REPO_ROOT / "recordings" / filename
        self._recording = RecordingTee(path, device_id="1915:0102")
        self._recording_path = path
        self._emit(_event("recording", state="started", path=str(path)))

    def _stop_recording(self) -> None:
        if self._recording is None:
            return
        path = self._recording_path
        self._recording.close()
        self._recording = None
        self._recording_path = None
        self._emit(_event("recording", state="stopped", path=str(path) if path else None))

    # ------------------------------------------------------------- status --

    def status_snapshot(self) -> dict:
        return {
            "connected": self.connected,
            "mode": self.mode,
            "channel": self.current_channel,
            "packet_count": self.packet_count,
            "uptime_s": round(time.time() - self.started_at, 2),
            "recording": {
                "active": self._recording is not None,
                "path": str(self._recording_path) if self._recording_path else None,
            },
        }

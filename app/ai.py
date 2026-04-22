"""
AI assistant — drives the nRF24 console via Claude tool use.

Requires ANTHROPIC_API_KEY in the environment. If not set, the assistant
degrades gracefully (endpoint returns a clear error; UI hides the tab).

Claude gets tool access to:
  - scan / sniff / transmit / stop / get_status
  - list_recordings / analyse_recording

Tools that run the radio are synchronous from Claude's perspective — we
block the request for the scan/sniff duration, collect events from the
worker's ring buffer, and return a summary. That way Claude can reason
over actual captured data in the same turn.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

from radio_worker import Command, RadioWorker

log = logging.getLogger("ai")


MODEL = "claude-sonnet-4-6"
MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """You are the in-app assistant for an nRF24 RF research console.

You can drive a flashed Logitech Unifying receiver (running Bastille's
nrf-research-firmware) to scan channels in the 2.4 GHz ISM band, sniff
specific 5-byte nRF24 addresses, record captures to disk, and transmit
payloads. The receiver is a hard singleton — only one mode runs at a time.

Typical user goals:
  - "Find nearby nRF24 devices" → run a scan and list addresses + channels
  - "Capture from my <device>" → scan, pick the active address, sniff it
  - "What's in this recording?" → use analyse_recording
  - "Send this command" → transmit (be careful; only on user-owned devices)

Guidelines:
  - When the user asks for a scan without specifics, default to 10-15 seconds
    covering channels 2-83 with 100 ms dwell.
  - If scan returns 0 packets, say so plainly — don't invent addresses.
  - When showing addresses or payloads, keep them in the colon-separated hex
    format the rest of the console uses (AA:BB:CC:DD:EE).
  - If you transmit, state exactly what you transmitted and to where.
  - Concise. Lead with the answer, then supporting detail.
"""


TOOLS = [
    {
        "name": "scan",
        "description": (
            "Run a promiscuous-mode channel sweep for a given duration. Returns "
            "the number of packets captured, unique transmitter addresses, and "
            "channel activity counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_s": {
                    "type": "number",
                    "description": "Scan duration in seconds (1-60). Default 10.",
                },
                "channels": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Channels to sweep (2-83). Default = full range.",
                },
                "dwell_ms": {
                    "type": "number",
                    "description": "Milliseconds per channel. Default 100.",
                },
                "prefix_hex": {
                    "type": "string",
                    "description": "Optional address prefix filter, e.g. 'AA:BB'. Empty for no filter.",
                },
            },
        },
    },
    {
        "name": "sniff",
        "description": (
            "Follow a specific nRF24 address across channels and capture its packets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "5-byte address in hex, e.g. 'AA:BB:CC:DD:EE'",
                },
                "duration_s": {
                    "type": "number",
                    "description": "How long to sniff (1-60 s). Default 10.",
                },
            },
            "required": ["address"],
        },
    },
    {
        "name": "transmit",
        "description": (
            "Send a single payload to an address. Use only on devices the user owns. "
            "ESB mode includes ACK handshake; Generic mode blasts without ACK."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "payload_hex": {"type": "string"},
                "mode": {"type": "string", "enum": ["esb", "generic"], "default": "esb"},
                "retries": {"type": "integer", "default": 5},
            },
            "required": ["address", "payload_hex"],
        },
    },
    {
        "name": "stop",
        "description": "Stop any active scan/sniff/transmit and return the radio to idle.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_status",
        "description": "Query radio connection state, current mode, channel, and packet counter.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_recordings",
        "description": "List saved JSONL capture files in the recordings/ directory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyse_recording",
        "description": (
            "Load a saved JSONL capture and return a summary: total events, packet "
            "count, unique addresses, sample payloads per address. Useful for "
            "reverse-engineering a protocol from a prior scan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
            },
            "required": ["filename"],
        },
    },
]


class AIAssistant:
    def __init__(self, worker: RadioWorker) -> None:
        self.worker = worker
        self.client = None
        self._init_error: str | None = None
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self._init_error = "ANTHROPIC_API_KEY is not set"
            return
        if Anthropic is None:
            self._init_error = "anthropic package is not installed"
            return
        try:
            self.client = Anthropic(api_key=api_key)
        except Exception as exc:
            self._init_error = f"failed to init Anthropic client: {exc}"

    @property
    def available(self) -> bool:
        return self.client is not None

    def availability_reason(self) -> str | None:
        return self._init_error

    # -------------------------------------------------------- conversation --

    def run(self, user_message: str, history: list | None = None) -> dict:
        if not self.client:
            return {"error": self._init_error or "assistant not available"}

        messages: list = list(history or [])
        messages.append({"role": "user", "content": user_message})
        steps: list[dict] = []

        for _round in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            blocks = response.content
            messages.append({"role": "assistant", "content": [b.model_dump() for b in blocks]})

            tool_uses = [b for b in blocks if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in blocks if b.type == "text")
                return {"message": text, "history": messages, "steps": steps,
                        "stop_reason": response.stop_reason}

            tool_results = []
            for tu in tool_uses:
                try:
                    result = self._execute_tool(tu.name, dict(tu.input))
                    steps.append({"tool": tu.name, "input": tu.input, "result": result})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(result)[:8000],
                    })
                except Exception as exc:
                    log.exception("tool %s failed", tu.name)
                    steps.append({"tool": tu.name, "input": tu.input, "error": str(exc)})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

        return {"error": "max tool rounds exceeded", "history": messages, "steps": steps}

    # ------------------------------------------------------------- tools --

    def _execute_tool(self, name: str, args: dict) -> Any:
        dispatcher = {
            "scan": self._tool_scan,
            "sniff": self._tool_sniff,
            "transmit": self._tool_transmit,
            "stop": self._tool_stop,
            "get_status": self._tool_get_status,
            "list_recordings": self._tool_list_recordings,
            "analyse_recording": self._tool_analyse_recording,
        }
        if name not in dispatcher:
            raise ValueError(f"unknown tool: {name}")
        return dispatcher[name](**args)

    def _tool_scan(self, duration_s: float = 10, channels: list | None = None,
                   dwell_ms: float = 100, prefix_hex: str = "") -> dict:
        duration_s = max(1.0, min(60.0, float(duration_s)))
        # If radio is busy doing something else, stop first.
        if self.worker.mode != self.worker.IDLE:
            self.worker.command_queue.put(Command("stop", {}))
            time.sleep(0.2)

        start_t = time.time()
        self.worker.command_queue.put(Command("scan_start", {
            "channels": channels,
            "dwell_ms": dwell_ms,
            "prefix": prefix_hex or "",
        }))
        time.sleep(duration_s)
        self.worker.command_queue.put(Command("stop", {}))
        time.sleep(0.15)

        packets = [e for e in list(self.worker.recent_events)
                   if e.get("type") == "packet" and e.get("t", 0) >= start_t]
        by_addr: dict[str, list] = {}
        by_ch: dict[int, int] = {}
        for p in packets:
            by_addr.setdefault(p.get("addr", "?"), []).append(p)
            ch = p.get("ch")
            if ch is not None:
                by_ch[ch] = by_ch.get(ch, 0) + 1

        return {
            "duration_s": duration_s,
            "packets_captured": len(packets),
            "unique_addresses": [
                {"addr": addr, "count": len(pkts),
                 "sample_payloads": [p.get("payload") for p in pkts[:3]]}
                for addr, pkts in by_addr.items()
            ],
            "channels_with_activity": sorted(by_ch.items(), key=lambda x: -x[1])[:20],
        }

    def _tool_sniff(self, address: str, duration_s: float = 10) -> dict:
        duration_s = max(1.0, min(60.0, float(duration_s)))
        if self.worker.mode != self.worker.IDLE:
            self.worker.command_queue.put(Command("stop", {}))
            time.sleep(0.2)

        start_t = time.time()
        self.worker.command_queue.put(Command("sniff_start", {"address": address}))
        time.sleep(duration_s)
        self.worker.command_queue.put(Command("stop", {}))
        time.sleep(0.15)

        packets = [e for e in list(self.worker.recent_events)
                   if e.get("type") == "packet" and e.get("t", 0) >= start_t]
        return {
            "address": address,
            "duration_s": duration_s,
            "packets_captured": len(packets),
            "packets": packets[:30],
        }

    def _tool_transmit(self, address: str, payload_hex: str, mode: str = "esb",
                       retries: int = 5) -> dict:
        if self.worker.mode != self.worker.IDLE:
            self.worker.command_queue.put(Command("stop", {}))
            time.sleep(0.2)

        start_t = time.time()
        self.worker.command_queue.put(Command("transmit", {
            "address": address, "payload_hex": payload_hex,
            "mode": mode, "retries": retries,
        }))
        time.sleep(0.6)

        result_events = [e for e in list(self.worker.recent_events)
                         if e.get("type") == "transmit_result" and e.get("t", 0) >= start_t]
        return {
            "submitted": True,
            "result": result_events[-1] if result_events else None,
        }

    def _tool_stop(self) -> dict:
        self.worker.command_queue.put(Command("stop", {}))
        time.sleep(0.2)
        return {"stopped": True, "mode": self.worker.mode}

    def _tool_get_status(self) -> dict:
        return self.worker.status_snapshot()

    def _tool_list_recordings(self) -> dict:
        base = Path(__file__).resolve().parent.parent / "recordings"
        base.mkdir(parents=True, exist_ok=True)
        files = []
        for p in sorted(base.glob("*.jsonl")):
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
            })
        return {"recordings": files}

    def _tool_analyse_recording(self, filename: str) -> dict:
        base = Path(__file__).resolve().parent.parent / "recordings"
        path = base / Path(filename).name
        if not path.exists():
            return {"error": f"not found: {filename}"}

        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return {"error": "empty file"}

        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError:
            header = {"note": "first line was not valid JSON header"}

        events = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        packets = [e for e in events if e.get("type") == "packet"]
        channels = [e for e in events if e.get("type") == "channel"]
        modes = [e for e in events if e.get("type") == "mode"]

        by_addr: dict[str, list] = {}
        for p in packets:
            by_addr.setdefault(p.get("addr", "?"), []).append(p)

        addr_summary = {}
        for addr, pkts in by_addr.items():
            lengths = [p.get("length", 0) for p in pkts]
            addr_summary[addr] = {
                "packet_count": len(pkts),
                "length_min": min(lengths) if lengths else 0,
                "length_max": max(lengths) if lengths else 0,
                "channels_seen": sorted({p.get("ch") for p in pkts if p.get("ch") is not None}),
                "sample_payloads": [p.get("payload") for p in pkts[:5]],
            }

        return {
            "header": header,
            "total_events": len(events),
            "channel_events": len(channels),
            "mode_events": len(modes),
            "packet_events": len(packets),
            "addresses": addr_summary,
        }

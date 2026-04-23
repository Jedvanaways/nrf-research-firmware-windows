"""
FastAPI backend for the nRF24 console.

Usage:
  py app/app.py                   # bind 127.0.0.1:8787 (default)
  py app/app.py --expose          # bind 0.0.0.0 (with a loud warning)
  py app/app.py --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from radio_worker import Command, RadioWorker
from ai import AIAssistant

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
RECORDINGS_DIR = REPO_ROOT / "recordings"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("app")


# -----------------------------------------------------------------------------
# Request models
# -----------------------------------------------------------------------------


class ScanStart(BaseModel):
    channels: list[int] | None = None
    dwell_ms: float = 100.0
    prefix: str = ""
    scan_mode: str = "esb"  # "esb" | "generic_2m" | "generic_1m" | "generic_250k"


class SniffStart(BaseModel):
    address: str = Field(..., description="Address in hex, e.g. AA:BB:CC:DD:EE")
    timeout_ms: float = 100.0
    ack_timeout_us: int = 250
    retries: int = 1
    ping_payload: str = "0F0F0F0F"
    channels: list[int] | None = None


class TransmitReq(BaseModel):
    address: str
    payload_hex: str
    mode: str = "esb"  # "esb" or "generic"
    retries: int = 5


class RecordingStart(BaseModel):
    filename: str | None = None


class AIChatReq(BaseModel):
    message: str
    history: list = Field(default_factory=list)


class ExternalPacket(BaseModel):
    """
    Packet pushed from an external radio source (e.g. ESP32 + LT8910).
    Only `payload` is required; everything else is best-effort metadata.
    """
    payload: str                              # hex, optionally colon-separated
    addr: str | None = None                   # same convention as local packets
    ch: int | None = None
    length: int | None = None
    source: str = "external"                  # label shown in the UI
    rssi: int | None = None                   # optional signal strength
    t: float | None = None                    # optional timestamp (else server time)


# -----------------------------------------------------------------------------
# App + worker wiring
# -----------------------------------------------------------------------------


worker: RadioWorker | None = None
assistant: AIAssistant | None = None
ws_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker, assistant
    loop = asyncio.get_running_loop()
    worker = RadioWorker(loop)
    worker.start()
    assistant = AIAssistant(worker)
    if assistant.available:
        log.info("AI assistant ready")
    else:
        log.info("AI assistant disabled: %s", assistant.availability_reason())

    pump_task = asyncio.create_task(_event_pump())
    log.info("worker started; event pump running")
    try:
        yield
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        # Worker is a daemon thread; uvicorn exit will reap it.


app = FastAPI(title="nRF24 console", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


# -----------------------------------------------------------------------------
# Event pump: drain worker.event_queue → broadcast to WS clients
# -----------------------------------------------------------------------------


async def _event_pump() -> None:
    assert worker is not None
    while True:
        try:
            event = await worker.event_queue.get()
        except asyncio.CancelledError:
            raise
        if not ws_clients:
            continue
        message = json.dumps(event)
        stale = []
        for ws in list(ws_clients):
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            ws_clients.discard(ws)


# -----------------------------------------------------------------------------
# Busy-guard
# -----------------------------------------------------------------------------


def _require_idle() -> None:
    assert worker is not None
    if worker.mode != worker.IDLE:
        raise HTTPException(
            status_code=409,
            detail={"error": "busy", "current_mode": worker.mode},
        )


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/status")
async def status():
    assert worker is not None
    return worker.status_snapshot()


@app.post("/api/scan/start")
async def scan_start(req: ScanStart):
    assert worker is not None
    _require_idle()
    worker.command_queue.put(Command("scan_start", req.model_dump()))
    return {"ok": True}


@app.post("/api/sniff/start")
async def sniff_start(req: SniffStart):
    assert worker is not None
    _require_idle()
    worker.command_queue.put(Command("sniff_start", req.model_dump()))
    return {"ok": True}


@app.post("/api/transmit")
async def transmit(req: TransmitReq):
    assert worker is not None
    _require_idle()
    worker.command_queue.put(Command("transmit", req.model_dump()))
    return {"ok": True}


@app.post("/api/stop")
async def stop():
    assert worker is not None
    worker.command_queue.put(Command("stop", {}))
    return {"ok": True}


@app.post("/api/reconnect")
async def reconnect():
    assert worker is not None
    worker.command_queue.put(Command("reconnect", {}))
    return {"ok": True}


@app.post("/api/recording/start")
async def recording_start(req: RecordingStart):
    assert worker is not None
    worker.command_queue.put(Command("recording_start", req.model_dump()))
    return {"ok": True}


@app.post("/api/recording/stop")
async def recording_stop():
    assert worker is not None
    worker.command_queue.put(Command("recording_stop", {}))
    return {"ok": True}


@app.post("/api/external/packet")
async def external_packet(pkt: ExternalPacket):
    """
    Ingest a packet from an external radio source. Normalises the payload,
    emits it as a 'packet' event on the same pipeline as local captures
    (ring buffer + recording tee + WS broadcast + Learn-mode visibility).
    """
    assert worker is not None
    payload = pkt.payload.replace(":", "").replace(" ", "")
    # Pretty-print with colons for UI consistency
    try:
        b = bytes.fromhex(payload)
        payload_disp = ":".join(f"{x:02X}" for x in b)
        length = pkt.length if pkt.length is not None else len(b)
    except ValueError:
        payload_disp = pkt.payload
        length = pkt.length or 0

    import time as _time
    event = {
        "type": "packet",
        "t": pkt.t if pkt.t is not None else _time.time(),
        "mode": "external",
        "source": pkt.source,
        "ch": pkt.ch,
        "addr": (pkt.addr or "").upper(),
        "payload": payload_disp,
        "length": length,
    }
    if pkt.rssi is not None:
        event["rssi"] = pkt.rssi

    worker.packet_count += 1
    worker._emit(event)
    return {"ok": True}


@app.post("/api/external/packets")
async def external_packets(payload: list[ExternalPacket]):
    """Batch version of /api/external/packet for ESP32s pushing many packets."""
    for p in payload:
        await external_packet(p)
    return {"ok": True, "count": len(payload)}


@app.get("/api/recent_packets")
async def recent_packets(since: float | None = None, until: float | None = None,
                          limit: int = 500):
    """
    Snapshot of packets from the worker's in-memory ring buffer within a
    time window. Used by the Learn tab to correlate button presses with
    RF captures.
    """
    assert worker is not None
    packets = [
        e for e in list(worker.recent_events)
        if e.get("type") == "packet"
        and (since is None or e.get("t", 0) >= since)
        and (until is None or e.get("t", 0) <= until)
    ]
    return {"packets": packets[-limit:]}


@app.get("/api/recordings")
async def recordings_list():
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for p in sorted(RECORDINGS_DIR.glob("*.jsonl")):
        stat = p.stat()
        files.append({
            "name": p.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        })
    return {"recordings": files}


@app.get("/api/recordings/{name}")
async def recording_get(name: str):
    # Strip path separators — we only serve files in RECORDINGS_DIR.
    safe = Path(name).name
    path = RECORDINGS_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "not found")
    return JSONResponse(
        {"name": safe, "content": path.read_text(encoding="utf-8")}
    )


@app.get("/api/ai/available")
async def ai_available():
    assert assistant is not None
    return {
        "available": assistant.available,
        "reason": assistant.availability_reason(),
    }


@app.post("/api/ai/chat")
async def ai_chat(req: AIChatReq):
    assert assistant is not None
    if not assistant.available:
        raise HTTPException(503, {
            "error": "ai_unavailable",
            "reason": assistant.availability_reason(),
        })
    # Claude calls + radio waits are blocking; run off the event loop.
    result = await asyncio.to_thread(assistant.run, req.message, req.history)
    return result


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    assert worker is not None
    try:
        # Send an initial status snapshot so newly-connected clients draw right away.
        await ws.send_text(json.dumps({"type": "status_snapshot",
                                       **worker.status_snapshot()}))
        while True:
            # We don't accept messages from the client yet; just keep the
            # socket open and let the event pump push events.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="nRF24 web console")
    parser.add_argument("--host", default=None,
                        help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--expose", action="store_true",
                        help="Bind 0.0.0.0 (LAN accessible — use with care)")
    parser.add_argument("--reload", action="store_true",
                        help="Uvicorn auto-reload (dev only)")
    args = parser.parse_args()

    host = args.host or ("0.0.0.0" if args.expose else "127.0.0.1")
    if args.expose:
        print("\n*** --expose: binding 0.0.0.0 — reachable on your LAN. "
              "No auth implemented. Don't run this on hostile networks. ***\n",
              file=sys.stderr)

    import uvicorn
    uvicorn.run(
        "app:app",
        host=host,
        port=args.port,
        reload=args.reload,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()

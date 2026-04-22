# nRF24 console

Browser-based console for the flashed nRF24 receiver. Scan channels, lock
onto an address and sniff, record sessions to disk, and transmit arbitrary
payloads.

## Prerequisites

Receiver already flashed + bound to WinUSB at `1915:0102`. See the repo
root's [flashing guide](../docs/flashing.md) if not.

## Run

```powershell
py app/app.py
```

Opens <http://127.0.0.1:8787>. By default only localhost can reach it.

```powershell
py app/app.py --expose           # bind 0.0.0.0 (LAN accessible — no auth)
py app/app.py --port 9000
```

### Enable the AI assistant (optional)

Set `ANTHROPIC_API_KEY` before launching. The Assistant tab then uses Claude
with tool-use to drive scans, sniffs, and recording analysis in natural
language.

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
py app/app.py
```

Without the key, the Assistant tab is replaced with a notice; the rest of
the app works normally.

## What each tab does

- **Scan** — puts the receiver into promiscuous mode and hops channels.
  Packets from any nearby nRF24 transmitter show up; click any row to lock
  onto that address in the Sniff tab. Tick "Record this session to JSONL"
  to tee everything to a file under `recordings/`.
- **Sniff** — enters ESB sniffer mode on a specific address and follows it
  across channels using the same ping-based algorithm as
  `tools/nrf24-sniffer.py`.
- **Transmit** — send an arbitrary hex payload. ESB mode sniffs the target
  first (with ACKs); Generic mode blasts the payload without ACK checks.
- **Recordings** — list of JSONL captures on disk.
- **Assistant** — natural-language interface powered by Claude with tool use.
  Ask things like "scan for 30 seconds and tell me what you find" or "analyse
  my most recent recording". Requires `ANTHROPIC_API_KEY`.

## Recording format

One JSON object per line. The first line is a header; subsequent lines are
events.

```jsonl
{"type":"header","version":1,"started":"2026-04-23T09:14:00+00:00","device":"1915:0102"}
{"type":"channel","t":1745399640.123,"channel":42}
{"type":"packet","t":1745399640.224,"mode":"scan","ch":42,"addr":"AA:BB:CC:DD:EE","payload":"01:02:03","length":3}
{"type":"mode","t":1745399650.001,"mode":"idle"}
```

JSONL is `grep`-able, `jq`-able, and can be tailed mid-capture.

## Architecture

- `app.py` — FastAPI + uvicorn, REST endpoints and a single WebSocket at
  `/ws/events`.
- `radio_worker.py` — dedicated thread that owns the `nrf24` object. HTTP
  handlers enqueue `Command` objects; the worker runs a state machine
  (`idle` / `scanning` / `sniffing` / `transmitting`) and emits events onto
  an asyncio queue via `loop.call_soon_threadsafe`.
- `static/` — vanilla JS + handwritten CSS. No build step.
- `templates/index.html` — single page, four tabs.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | `{connected, mode, channel, packet_count, uptime_s, recording}` |
| POST | `/api/scan/start` | `{channels?, dwell_ms?, prefix?}` — 409 if not idle |
| POST | `/api/sniff/start` | `{address, timeout_ms?, retries?, channels?, ...}` — 409 if not idle |
| POST | `/api/transmit` | `{address, payload_hex, mode, retries?}` — 409 if not idle |
| POST | `/api/stop` | Returns the radio to idle |
| POST | `/api/reconnect` | Reopen the USB device |
| POST | `/api/recording/start` | `{filename?}` |
| POST | `/api/recording/stop` | |
| GET | `/api/recordings` | List saved captures |
| GET | `/api/recordings/{name}` | Get the raw JSONL content of one capture |
| GET | `/api/ai/available` | `{available, reason}` — whether Claude is configured |
| POST | `/api/ai/chat` | `{message, history}` → `{message, steps, history}` or 503 if AI unavailable |
| WS | `/ws/events` | `packet`, `mode`, `channel`, `status`, `error`, `recording`, `transmit_result` |

## Security note

No authentication. Default binding is `127.0.0.1` for exactly this reason.
If you need LAN access, wrap it in an SSH tunnel or a reverse proxy with
auth — don't rely on `--expose` in anything but a trusted network.

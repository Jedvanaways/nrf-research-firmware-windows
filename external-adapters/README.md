# External adapters

The web app (`../app/`) can ingest packets from sources other than the local
flashed Logitech receiver, via a simple HTTP API. This lets you use the same
UI — Scan view, Addresses panel, Learn mode with countdown-and-press
capture, Recordings — for any radio whose hardware can talk JSON over HTTP.

Use cases:
- An ESP32 + LT8910 module capturing traffic from non-nRF24 devices (the
  original motivation — bed remotes, 2.4 GHz appliances that the Bastille
  firmware can't see)
- An RTL-SDR running `rtl_433` and piping decoded 433 MHz packets in
- A Raspberry Pi with a CC1101 module
- Any future radio; the protocol is intentionally trivial

## Wire protocol

POST a JSON object (or an array for batched) to the running app:

```http
POST http://<app-host>:8787/api/external/packet
Content-Type: application/json

{
  "source":  "esp32-lt8910",        // label shown in the UI
  "payload": "01:10:00:22:FF:A5",   // hex, colons optional
  "addr":    "AA:BB:CC:DD:EE",      // optional
  "ch":      42,                    // optional
  "length":  6,                     // optional, inferred from payload hex
  "rssi":    -54,                   // optional
  "t":       1745400000.123         // optional, defaults to server time
}
```

For many packets at once:

```http
POST http://<app-host>:8787/api/external/packets
Content-Type: application/json

[ { ... }, { ... }, ... ]
```

Both endpoints return `{"ok": true}` on success. Any packet ingested this
way appears immediately in the Scan tab's "Packet stream" with a coloured
"EXT" source chip, flows into the Addresses panel, hits Learn-mode's
time-window capture, and is written to any active recording.

## Contents

- `mock-transmitter.py` — a tiny Python script that fires plausible-looking
  fake packets at the app so you can test the UI end-to-end without any
  real hardware. Run it while the app is up:

  ```powershell
  py external-adapters/mock-transmitter.py --rate 3
  ```

- `esp32-lt8910/esp32-lt8910.ino` — Arduino sketch for ESP32 + LT8910 /
  LT8920 module. It's a working skeleton — `setup()` connects to WiFi,
  `loop()` drains captured packets and POSTs them in batches — but the
  actual LT8910 driver calls are stubbed with `// TODO:` comments because
  there are several competing community libraries. Edit the three
  `TODO:` sites with calls from whichever LT8910 library you pick.

  Recommended libraries to start with:
  - <https://github.com/Kiwisincebirth/Arduino-LT8900>
  - <https://github.com/JimQode/LT8900>

  Both need light porting for ESP32 (they were written for AVR).

## Finding the right sync word for an LT8910 device

The LT8910 will only surface packets whose first bytes match its configured
sync word — otherwise it behaves as if nothing transmitted. For
reverse-engineering a device you don't have docs for, the usual approach is:

1. **Start with the common defaults**: `0x7262D547`, `0x7162D547`,
   `0x52626263` are all sync words that some devices use.
2. **Try sync-word brute-force**: there are Arduino sketches that sweep
   likely sync words while a remote is being pressed; see
   <https://github.com/omriiluz/NRF24-BTLE-Decoder> for the kind of pattern,
   adapted for LT8910.
3. **Datasheet / FCC filing**: if the product has an FCC ID, the filing
   sometimes includes "technical brief" PDFs that state the link parameters.
4. **Community**: someone may have already done the work — search the
   product's model number + "LT8910" / "LT8920" / "RF protocol".

When you find the sync word, set `LT_SYNC_WORD_H/L` in the sketch.

## Why not connect the ESP32 directly to the browser?

You could make the ESP32 host its own WebSocket server that a browser
connects to, but:

- You'd lose the Scan/Sniff/Transmit/Recordings/Learn UI we already have
- The ESP32's WiFi AP has to share airtime with its receive loop, which
  is less reliable than HTTP client bursts
- Combining nRF24 + LT8910 sources in one UI needs *something* to merge
  the streams; the app already does that.

HTTP POST to the app, then let the app do the fan-out.

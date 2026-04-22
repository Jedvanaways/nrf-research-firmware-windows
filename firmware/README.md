# Prebuilt firmware

- `dongle.formatted.bin` — padded raw binary used for the CRC calculation
- `dongle.formatted.ihx` — Intel-hex payload flashed to the receiver

Both files are produced by the upstream Makefile under `bin/`. Do not modify
them — the flasher computes a CRC over `.bin` and streams `.ihx` record-by-record.

See [`../upstream/README.md`](../upstream/README.md) for rebuild instructions.

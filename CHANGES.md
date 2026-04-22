# Changes vs upstream Bastille nrf-research-firmware

Upstream base: commit `02b84d1c4e59c0fb98263c83b2e7c7f9863a3b93` (2016-07-26)
from [BastilleResearch/nrf-research-firmware](https://github.com/BastilleResearch/nrf-research-firmware).

This fork targets Windows and Python 3. The nRF24LU1+ firmware itself is
**built from upstream source unmodified**; all differences below are in the
host tooling that talks to the flashed dongle.

## Summary of modifications

### `flasher/` — Python 3 port of the USB flasher

Upstream `prog/usb-flasher/` is Python 2 and assumes a Linux environment
with kernel USB drivers that can be detached. Ported files:

- `flasher/unifying.py` — Python 3 port of `unifying.py`
- `flasher/logitech-usb-flash.py` — Python 3 port of `logitech-usb-flash.py`
- `flasher/logitech-usb-restore.py` — Python 3 port of `logitech-usb-restore.py`

Changes applied:

- `print X` → `print(X)`
- `except Exception, e:` → `except Exception as e:`
- `str.decode('hex')` → `bytes.fromhex(...)`
- Removed `ord()` calls on `bytes` indices (Python 3 already yields ints)
- Rebuilt USB payloads with `bytes(...)` / `bytes([...])` instead of string
  concatenation, so `struct.pack` results splice cleanly
- `is_kernel_driver_active` / `detach_kernel_driver` calls wrapped in
  `try/except (NotImplementedError, usb.core.USBError)` — on Windows these
  raise rather than silently returning false when WinUSB owns the device
- Added `libusb_package.get_libusb1_backend()` wiring so pyusb finds the
  bundled `libusb-1.0.dll` without a separate system install

### `tools/` — Python 3 port of the research sniffer toolkit

Upstream `tools/lib/` and the top-level sniffer scripts are Python 2. Ported:

- `tools/nrf24.py` — radio driver class
- `tools/common.py` — argparse / logging / radio init helpers
- `tools/nrf24-scanner.py` — promiscuous-mode channel sweeper
- `tools/nrf24-sniffer.py` — ESB address-locked sniffer

Changes applied:

- Python 3 syntax fixes as above
- `map(ord, prefix)` patterns replaced with a single `_to_ints()` helper in
  `tools/nrf24.py` that accepts `bytes`, `str`, or `list[int]` and returns a
  list of ints — decouples callers from Py2-era byte/str ambiguity
- `libusb_package` backend, same rationale as the flasher
- `xrange` → `range`
- `choices=xrange(0, 16)` → `choices=range(0, 16)`
- Removed hard dependency on the `lib.*` sub-package; tools import siblings
  directly so the flattened Windows layout Just Works
- Scripts are `#!/usr/bin/env python3` and wrap their body in `main()`

### `firmware/` — prebuilt binaries

Produced on an Ubuntu 24.04 box with:

```
apt install -y sdcc binutils make
git clone https://github.com/BastilleResearch/nrf-research-firmware.git
cd nrf-research-firmware
make          # SDCC 4.2.0, no flags beyond the upstream Makefile
```

Output: `bin/dongle.formatted.bin`, `bin/dongle.formatted.ihx`.

Redistributing these as binaries is GPLv3-compliant because the source is
upstream, unmodified, and you can rebuild the exact same files from the
commit SHA above.

### `app/` — new, not in upstream

Web-based console for driving the flashed receiver from a browser. See
`app/README.md`. Imports `tools.nrf24` directly; no fork of the radio code.

### Documentation

Upstream ships a single `readme.md` focused on Linux. This repo ships:

- `README.md` — Windows-first quickstart
- `docs/windows-setup.md` — Python env, venv, pip
- `docs/zadig-driver-swap.md` — the three-stage WinUSB swap
  (`046D:C52B` → `046D:AAAA` → `1915:0102`)
- `docs/flashing.md` — end-to-end flash walkthrough
- `docs/restoring.md` — getting back to stock Logitech firmware

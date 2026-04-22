# Flashing walkthrough

## Prerequisites

- A flashable Logitech receiver (`046D:C52B` and similar — see README table)
  with **unpatched** firmware. Patched firmware (`RQR012.09` or later)
  blocks the exploit and the flash will hang in the "firmware update mode"
  stage. You can check the version in Logi Options / Unifying Software
  before starting.
- Python env set up — see [windows-setup.md](windows-setup.md).
- A second pointer device (Bluetooth or wired) — once the receiver is
  swapped to WinUSB, it stops being a mouse dongle.

## Step 1 — swap the factory `C52B` to WinUSB

See [zadig-driver-swap.md](zadig-driver-swap.md) → Stage 1.

## Step 2 — run the flasher (first pass)

```powershell
cd <repo root>
py flasher/logitech-usb-flash.py firmware/dongle.formatted.bin firmware/dongle.formatted.ihx
```

You'll see log lines up to `Found Logitech Unifying dongle - firmware update mode`,
then an error similar to:

```
NotImplementedError: Operation not supported or unimplemented on this platform
```

That's fine. The receiver is now in bootloader mode (`046D:AAAA`) — we just
need to point WinUSB at that new PID.

## Step 3 — swap `046D:AAAA` to WinUSB

Zadig → Stage 2 in the driver-swap doc.

## Step 4 — run the flasher (second pass)

```powershell
py flasher/logitech-usb-flash.py firmware/dongle.formatted.bin firmware/dongle.formatted.ihx
```

This time it runs the full flash. Expect a stream of 32-byte hex responses
and these milestones:

```
Computing the CRC of the firmware image
Preparing USB payloads
Found Logitech Unifying dongle - firmware update mode
Initializing firmware update
Clearing existing flash memory up to bootloader
Transferring the new firmware
Mark firmware update as completed
Restarting dongle into research firmware mode
```

Completion looks like no exceptions + that final "Restarting dongle" line.

## Step 5 — swap `1915:0102` to WinUSB

Zadig → Stage 3. If the device doesn't appear in Zadig, reboot Windows and
try again — a reboot is a reliable workaround for post-flash enumeration
quirks.

## Step 6 — verify

```powershell
py -c "from tools.nrf24 import nrf24; r = nrf24(); print('ok, channel:', list(r.get_channel())[0])"
```

Prints a channel number = flash worked, drivers are bound, tooling can talk
to the radio.

```powershell
py tools/nrf24-scanner.py -v
```

Shows channel tuning logs even if no RF traffic is in range. Ctrl-C to quit.

## If the flash fails

| Symptom | Likely cause | Fix |
|---|---|---|
| `Incompatible Logitech Unifying dongle (type XX)` where XX ≠ `12` | Not a Nordic-based receiver (TI-based dongle) | Can't flash this one |
| Hang on "Putting dongle into firmware update mode", no `AAAA` PID appears | Firmware is patched (`RQR012.09` or later) — USB DFU exploit blocked | No software flash path; would need Teensy-based SPI flashing. Easier to buy a CrazyRadio PA |
| `Access denied` | Zadig swap didn't take, or a Logitech app has the HID handle | Close Logi Options / LGS; re-run Zadig on the right PID |
| `No backend available` | `libusb-package` not installed | `pip install libusb-package` |

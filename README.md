# nrf-research-firmware-windows

Windows port of [Bastille Networks' nRF24 research firmware tooling](https://github.com/BastilleResearch/nrf-research-firmware), with a browser-based console for scanning, sniffing, and transmitting nRF24 traffic.

The firmware itself is Bastille's, built from unmodified upstream source. This repo adds:

- **Python 3 ports** of the Logitech Unifying flasher and the `nrf24-scanner` / `nrf24-sniffer` tools
- **Prebuilt firmware binaries** (`firmware/dongle.formatted.bin` + `.ihx`) so you don't need to install SDCC on Windows
- **Windows driver-swap runbook** (Zadig → WinUSB, three-stage for C52B → AAAA → 1915:0102)
- **Web app** (`app/`) that drives the flashed receiver from a browser, with
  an optional Claude-powered assistant that can scan, sniff, and analyse
  captures in natural language

> **Use this only on devices you own.** Sniffing and transmitting on unlicensed 2.4 GHz hardware you don't own is the same conversation as lockpicking someone else's door. This project exists for home-automation reverse-engineering on your own kit. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Hardware supported

| Product ID | Description | Flashable? |
|---|---|---|
| `046D:C52B` | Logitech Unifying Receiver (Nordic-based, pre-Bolt) | ✅ if firmware is pre-`RQR012.09` |
| `046D:C532` | Unifying Receiver (newer) | ✅ if unpatched |
| `046D:C534` | Unifying Receiver (Logi C-U0008) | ✅ if unpatched |
| `046D:C539` / `C53A` / `C53F` | Lightspeed G Receiver | ✅ if unpatched |
| `046D:C548` / `C547` / `C54D` | **Bolt** receiver (BLE) | ❌ not nRF24 |
| `1915:0007` | Nordic Semiconductor nRF24LU1+ breakout | ✅ (native) |

The check script at `tools/check-logitech-receiver.ps1` (in the sister repo if present, or you can lift it from the upstream `.github`) tells you which category your plugged dongle is in.

## Quickstart

1. **Install Python 3.10+** from [python.org](https://www.python.org/downloads/windows/) — the Microsoft Store build works too.
2. **Install deps** (inside a venv recommended):

   ```powershell
   git clone https://github.com/Jedvanaways/nrf-research-firmware-windows
   cd nrf-research-firmware-windows
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Plug in a flashable Logitech receiver** and confirm:

   ```powershell
   Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_046D.*PID_C52B' }
   ```

4. **Flash the firmware** — see [`docs/flashing.md`](docs/flashing.md). Short version:

   - Zadig-swap `046D:C52B` to WinUSB ([docs/zadig-driver-swap.md](docs/zadig-driver-swap.md))
   - `py flasher/logitech-usb-flash.py firmware/dongle.formatted.bin firmware/dongle.formatted.ihx`
   - Zadig-swap the new `046D:AAAA` bootloader to WinUSB, re-run the flasher
   - Zadig-swap the final `1915:0102` research firmware to WinUSB

5. **Launch the console:**

   ```powershell
   py app/app.py
   ```

   Opens on <http://127.0.0.1:8787>. See [`app/README.md`](app/README.md).

6. **Or use the CLI tools directly:**

   ```powershell
   py tools/nrf24-scanner.py -v
   py tools/nrf24-sniffer.py -a AA:BB:CC:DD:EE
   ```

## Layout

```
firmware/       Prebuilt firmware .bin + .ihx for the Logitech Unifying receiver
flasher/        Python 3 port of Bastille's Logitech flash/restore scripts
tools/          Python 3 port of Bastille's nrf24-scanner and nrf24-sniffer
app/            Browser-based console (FastAPI + vanilla JS)
docs/           Windows-specific runbooks
upstream/       Provenance — commit SHA + link to Bastille upstream
```

## Restoring the original Logitech firmware

See [`docs/restoring.md`](docs/restoring.md). Short version: obtain the stock
`RQR_012_005_00028.hex` from Logitech support archives and run
`py flasher/logitech-usb-restore.py RQR_012_005_00028.hex` with WinUSB still
bound. The receiver goes back to being a normal HID mouse dongle.

## Attribution

All radio-protocol smarts and the firmware itself are Bastille's work. This
repo is a Windows-host-tooling wrapper. See [NOTICE](NOTICE) for full
provenance and [CHANGES.md](CHANGES.md) for the list of modifications.

## Licence

GPLv3, inherited from upstream. See [LICENSE](LICENSE).

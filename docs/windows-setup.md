# Windows setup

## 1. Python

Install Python 3.10 or newer. The `py` launcher is what the examples assume.

- [python.org Windows installer](https://www.python.org/downloads/windows/) — during install, tick **Add python.exe to PATH**.
- Microsoft Store Python also works. If you use it, `py -3.13` / `py -3.12` / etc. still resolves correctly.

Verify:

```powershell
py --version        # expect 3.10+
py -m pip --version # expect a recent pip
```

## 2. Virtual environment (recommended)

Keeps pyusb / fastapi out of your global Python.

```powershell
cd <wherever you cloned this repo>
py -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution the first time, run this once per user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 3. Dependencies

```powershell
pip install -r requirements.txt
```

This pulls:

- `pyusb` — Python USB wrapper
- `libusb-package` — bundles `libusb-1.0.dll` so pyusb finds a backend without a separate libusb install
- `fastapi` + `uvicorn[standard]` — web-app server

## 4. Zadig

Needed once per receiver to swap the Logitech HID driver for WinUSB. See
[zadig-driver-swap.md](zadig-driver-swap.md). Download from
<https://zadig.akeo.ie/>.

## 5. Sanity check

After the Zadig swap (see next doc) and the flash (see `flashing.md`):

```powershell
py -c "from tools.nrf24 import nrf24; r = nrf24(); print('ok, channel:', list(r.get_channel())[0])"
```

If you see a channel number, your radio is alive.

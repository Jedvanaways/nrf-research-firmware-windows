# Zadig driver swap — the three-stage dance

Windows binds the Logitech receiver to its HID driver by default. For
`pyusb` / `libusb` to talk to the dongle directly, you need to swap it to
**WinUSB**. You'll do this **three times** during a fresh flash because the
dongle re-enumerates as different USB IDs along the way:

1. **`046D:C52B`** — the factory Unifying receiver, HID mode
2. **`046D:AAAA`** — the Logitech bootloader mode (appears mid-flash)
3. **`1915:0102`** — Nordic Semiconductor / research firmware (after flashing)

Each of these is a distinct USB device to Windows and needs its own WinUSB
binding.

## Installing Zadig

1. Download `zadig-2.9.exe` (or later) from <https://zadig.akeo.ie/>.
2. Right-click → **Run as administrator**. Zadig needs admin to install
   drivers.

## Stage 1 — swap the factory `C52B` to WinUSB

Before starting: connect a **second pointer device** (Bluetooth mouse,
trackpad, or a wired mouse). Once you swap the driver, the Logitech dongle
stops acting as a mouse dongle.

1. **Options** menu → tick **List All Devices**
2. **Options** menu → *untick* "Ignore Hubs or Composite Parents"
3. In the dropdown, select **USB Receiver (Composite Parent)**. Confirm the
   grey `USB ID` reads `046D C52B`.
4. Set the right-hand target driver to **WinUSB**.
5. Click **Replace Driver**. Wait ~60 seconds for "successfully installed".

Verify:

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_046D.*PID_C52B' } |
    Select-Object FriendlyName, Service
```

`Service` should now read **WinUSB** (was `HidUsb` / `usbccgp`).

## Stage 2 — mid-flash, the bootloader (`046D:AAAA`) appears

Run the flasher once — it'll get the dongle into bootloader mode then error
out trying to open the new USB ID. That's expected:

```powershell
py flasher/logitech-usb-flash.py firmware/dongle.formatted.bin firmware/dongle.formatted.ihx
```

At that point a new device appears. Verify:

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_046D.*PID_AAAA' } |
    Select-Object FriendlyName, Service
# -> "USB BootLoader", Service=HidUsb (needs swapping)
```

Relaunch Zadig as admin and do the same driver-replace flow as Stage 1, but
this time picking the entry whose `USB ID` reads `046D AAAA`. The name will
probably show as "USB BootLoader" or "HID-compliant vendor-defined device".
Swap it to WinUSB.

Now re-run the flasher — it should progress past the bootloader handshake
and complete the full flash. You'll see a stream of command/response logs
ending with:

```
Mark firmware update as completed
Restarting dongle into research firmware mode
```

## Stage 3 — the research firmware (`1915:0102`)

After the flash succeeds the dongle re-enumerates as `1915:0102`. Windows
has no driver for it, so it shows up with `Status: Error` and no `Service`.
Zadig again:

1. If Zadig doesn't show it immediately, close and relaunch (or press **F5**).
2. Find the entry whose `USB ID` reads `1915 0102`. Name will be blank or
   "Unknown Device".
3. Target: **WinUSB**, click **Install Driver**.

Verify:

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_1915' } |
    Select-Object FriendlyName, Service
# -> "Unknown Device #1", Service=WinUSB
```

You're done. `tools/nrf24-scanner.py` and the web console can now talk to
the receiver.

## Troubleshooting

**Zadig can't see the device after flash.**
Reboot. The firmware is persistent, the dongle re-enumerates on boot and
Zadig usually sees it cleanly afterwards.

**`NotImplementedError: Operation not supported or unimplemented on this platform`.**
WinUSB isn't bound to the PID you're currently trying to open. Which PID is
present (`Get-PnpDevice` with the VID filters above) and was that PID
swapped? You probably need to do Stage 2 or Stage 3.

**`Access denied`.**
Another process has the device open (Logi Options+, LGS, a Chrome tab with
WebHID). Close it.

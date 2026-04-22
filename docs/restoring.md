# Restoring the original Logitech firmware

The research firmware is persistent — it survives reboot and re-plug. If you
want the receiver back as a normal Unifying mouse dongle, you have to flash
the original Logitech firmware over the top.

## Step 1 — obtain the original firmware HEX

Logitech's firmware is distributed as `.exe` updaters rather than raw HEX
files, but community archives have the extracted `.hex`. Search for:

- `RQR_012_005_00028.hex` — a known-working stock firmware for C52B
- (or whatever RQR version matches your dongle family)

Place the `.hex` somewhere local, e.g. `S:\logitech-original-firmware.hex`.

## Step 2 — ensure WinUSB is still bound to `1915:0102`

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_1915' } |
    Select-Object FriendlyName, Service
# -> Service should be WinUSB
```

If the receiver isn't running research firmware (e.g. because you flashed
and reverted before), plug it in; Windows should show it as `1915:0102` if
last flash was research firmware, or as `046D:C52B` if it's currently stock.

## Step 3 — run the restore

```powershell
py flasher/logitech-usb-restore.py S:\logitech-original-firmware.hex
```

Same general flow as the flash — CRC compute, bootloader entry, payload
stream, completed, restart. After it's done the receiver should re-enumerate
as `046D:C52B` again.

## Step 4 — give HID back

Zadig → pick `046D C52B` → select **HidUsb** (or whichever HID driver Zadig
offers in the dropdown) → **Replace Driver**. The receiver is now a plain
Unifying dongle again and your mouse / keyboard will pair with it as normal.

Alternatively, just uninstall the device in Device Manager and let Windows
rediscover it with default drivers.

## Why this is more annoying than flashing

The research firmware is tiny and trivial to redistribute; Logitech's stock
firmware isn't publicly archived in `.hex` form by Logitech themselves.
Factor that in before you flash: the restore requires sourcing a binary
that isn't legally hosted here. If that's a problem, buying a CrazyRadio
PA (~£30 from Bitcraze) gives you the same sniffing capability without
needing to touch a Logitech receiver.

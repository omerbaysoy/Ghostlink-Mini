# MT7612U Driver Strategy - Raspberry Pi 5 (Kernel 6.12+)

This document records the strategy for supporting the MT7612U USB Wi-Fi adapter as a second main pentest/access/uplink adapter in Ghostlink-Mini.

## Overview

The MT7612U is a MediaTek 802.11ac USB adapter (often found in Alfa AWUS036ACM and similar devices). It is supported by the **in-kernel `mt76` driver stack** on modern Linux/Raspberry Pi OS kernels — no third-party DKMS driver is needed.

## The Working Strategy

Modern Raspberry Pi OS (Debian Bookworm/Trixie) includes the `mt76` kernel stack as a built-in module. When an MT7612U device is plugged in, the kernel automatically loads the required modules and creates a wireless interface.

### Key Modules

| Module | Purpose |
|---|---|
| `mt76` | MediaTek mt76 core |
| `mt76_usb` | mt76 USB transport layer |
| `mt76x2_common` | MT7612/MT7662 shared code |
| `mt76x2u` | MT7612U USB-specific driver |

When an MT7612U device is plugged in, `mt76x2u` is the module that binds to it and creates the wireless interface.

### Firmware

MT7612U requires firmware files that are provided by the `firmware-misc-nonfree` package on Raspberry Pi OS / Debian:

```bash
sudo apt-get install firmware-misc-nonfree
```

The relevant firmware file is typically `mt7662u.bin` (and `mt7662u_rom_patch.bin`).

## Interface Detection

Ghostlink-Mini identifies the MT7612U using **stable sysfs USB vendor/product mapping**, not interface names (`wlan0`, `wlan1`, etc.), which can change between reboots.

Detection reads:
- `/sys/class/net/<iface>/device/idVendor`
- `/sys/class/net/<iface>/device/idProduct`

### Supported USB IDs

| USB ID | Device |
|---|---|
| `0e8d:7612` | MediaTek MT7612U reference design / Alfa AWUS036ACM |
| `0e8d:761a` | MediaTek MT7662U (same mt76x2u driver) |
| `2001:3a02` | D-Link DWA-182 rev D |
| `0b05:17d1` | ASUS USB-AC55 |
| `148f:7612` | Ralink/MediaTek MT7612U OEM |
| `13b1:003e` | Linksys WUSB6300 v2 |

The adapter is mapped to the stable key `mt7612u` in the adapter detection system. This key is preserved across reboots regardless of which `wlanX` interface Linux assigns.

## Adapter Roles

MT7612U is the **second main pentest/access/uplink adapter**:

- Default pentest priority: RTL8812AU → **MT7612U** → RTL8188EUS → RTL88x2BU
- Default scan priority: RTL8812AU → **MT7612U** → RTL8188EUS → RTL88x2BU
- Can be used as uplink for Ghostlink-AP when RTL8812AU is not present
- Must never be used as management interface (management is reserved for onboard brcmfmac)

## No DKMS Driver by Default

Unlike the RTL8812AU, the MT7612U does **not** require a third-party DKMS driver. The `setup.sh` script:

1. Checks whether `mt76x2u` is available via `modinfo`
2. Runs `modprobe mt76x2u` if available
3. Installs `firmware-misc-nonfree` if available from apt
4. Prints warnings if modules are unavailable
5. **Does not** clone or build any external MT7612U repository

This is intentional. The in-kernel driver is sufficient for monitor mode and packet injection on modern kernels.

## No Conflict with RTL8812AU

The MT7612U setup:

- Does **not** touch RTL8812AU DKMS modules (`88XXau`, `8812au`)
- Does **not** modify `/etc/modprobe.d/ghostlink-rtl8812au.conf`
- Does **not** blacklist any Realtek modules
- Does **not** unload any loaded modules

The RTL8812AU blacklist (`ghostlink-rtl8812au.conf`) only blacklists `rtw_8812au`, `rtw88_8812au`, and `rtl8xxxu`. None of these affect mt76 modules.

## Troubleshooting

### MT7612U USB device plugged in but no wireless interface appears

Run these checks:

```bash
# Is the device seen by USB subsystem?
lsusb | grep -i "0e8d\|7612\|mt76"

# Are mt76 modules loaded?
lsmod | grep mt76

# Is mt76x2u available in this kernel?
modinfo mt76x2u

# Try loading the module manually
sudo modprobe mt76x2u

# Check dmesg for errors
dmesg | grep -i mt76 | tail -20

# What wireless interfaces exist?
iw dev

# Run Ghostlink diagnostics
ghostlink -diag

# Check full adapter status
ghostlink -status
```

### firmware-misc-nonfree not available

On some minimal Raspberry Pi OS images, the non-free firmware repository may not be enabled. Add it:

```bash
# Raspberry Pi OS / Debian
sudo apt-get update
sudo apt-get install firmware-misc-nonfree
```

If the package is unavailable, check `/etc/apt/sources.list` and ensure `non-free` or `non-free-firmware` is included.

### Interface exists but no monitor mode

The mt76x2u driver on modern kernels supports monitor mode. Verify:

```bash
iw phy phy0 info | grep -A 10 "Supported interface modes"
```

Look for `* monitor` in the output.

If monitor mode is not listed, the adapter may have bound to a different driver. Check:

```bash
iw dev
# Note which phy the interface is on, then:
cat /sys/class/net/<iface>/device/driver/module/drivers
```

### Wifite or aircrack-ng doesn't see the MT7612U interface

Ensure Ghostlink detected it:

```bash
ghostlink -diag
```

If the mt7612u role shows "Missing", try:

```bash
sudo modprobe mt76x2u
iw dev
ghostlink -status
```

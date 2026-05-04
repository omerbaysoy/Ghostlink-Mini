# Ghostlink-Mini

Ghostlink-Mini is a Raspberry Pi 5 CLI tool for authorized/lab Wi-Fi workflows using multiple Wi-Fi adapters with fixed roles.

## Adapter Roles

| # | Adapter | Role | Key |
|---|---|---|---|
| 1 | Raspberry Pi 5 Onboard Wi-Fi (brcmfmac) | Management only — never used for scan, pentest, monitor, AP, or attack workflows | `management` |
| 2 | **RTL8812AU** (USB ID `0bda:8812`) | Main pentest/access/uplink adapter | `rtl8812au` |
| 3 | **MT7612U** (USB ID `0e8d:7612` and others) | Second main pentest/access/uplink adapter | `mt7612u` |
| 4 | RTL88x2BU (USB ID `0bda:b812`) | AP adapter — creates Ghostlink-AP | `rtl88x2bu` |
| 5 | RTL8188EUS (USB ID `2357:010c`) | Backup adapter | `rtl8188eus` |

## Supported USB Adapters

| Adapter | Chipset | USB IDs | Driver | Role |
|---|---|---|---|---|
| Alfa AWUS036ACS and similar | RTL8812AU | `0bda:8812` | `88XXau` (aircrack-ng DKMS), fallback `8812au` | Pentest / uplink |
| Alfa AWUS036ACM and similar | MT7612U | `0e8d:7612`, `0e8d:761a`, `2001:3a02`, `0b05:17d1`, `148f:7612`, `13b1:003e` | `mt76x2u` (in-kernel) | Pentest / uplink |
| RTL88x2BU adapters | RTL88x2BU | `0bda:b812` | `rtw_8822bu` / `rtw88_8822bu` | AP |
| RTL8188EUS adapters | RTL8188EUS | `2357:010c` | `8188eu` | Backup |

## Setup and Installation

**WARNING: Requires root access and an active internet connection.**

```bash
sudo ./setup.sh
```

Setup installs:
- RTL8812AU pentest driver (aircrack-ng/rtl8812au v5.6.4.2, fallback: morrownr/8812au-20210820)
- RTL88x2BU driver via lwfinger/rtw88
- RTL8188EUS backup driver
- MT7612U in-kernel mt76 module check and firmware (`firmware-misc-nonfree`)
- Wifite2, Airgeddon, aircrack-ng, nmap, and other toolchain dependencies

## Running the Tool

Interactive CLI menu:

```bash
ghostlink
```

## Direct Commands

```
ghostlink -status                              Show system and adapter status
ghostlink -db                                  Show database status
ghostlink -creds                               View saved credentials
ghostlink scan [--iface <interface>]           Scan for nearby networks
ghostlink pentest --ssid "<SSID>" [--iface <interface>] [--bssid <BSSID>]
                                               Start automated pentest
ghostlink -connect                             Connect to a recovered network
ghostlink -ap-start                            Start Ghostlink-AP on RTL88x2BU
ghostlink -ap-stop                             Stop Ghostlink-AP
ghostlink -diag                                Run system diagnostics
ghostlink -restart-net                         Restart networking services
ghostlink -update                              Pull latest version and update
ghostlink network-scan [--target <IP/CIDR>] [--type <type>]
                                               Run nmap network scan
```

## Scan and Pentest Examples

Auto-select best available adapter (RTL8812AU first, MT7612U second):

```bash
# Scan
sudo ghostlink scan

# Pentest
sudo ghostlink pentest --ssid "TargetNetwork"
```

Explicitly select MT7612U by interface:

```bash
# First find the MT7612U interface name
ghostlink -status

# Then use it explicitly
sudo ghostlink scan --iface wlan1
sudo ghostlink pentest --ssid "TargetNetwork" --iface wlan1
```

Explicitly select RTL8812AU:

```bash
sudo ghostlink scan --iface wlan2
sudo ghostlink pentest --ssid "TargetNetwork" --iface wlan2 --bssid AA:BB:CC:DD:EE:FF
```

## Scan and Pentest Adapter Priority

Both `scan` and `pentest` auto-select adapters in this order when `--iface` is not specified:

1. RTL8812AU (`88XXau` driver preferred)
2. MT7612U (`mt76x2u` in-kernel driver)
3. RTL8188EUS (backup)
4. RTL88x2BU (last resort)
5. Management interface — **never used**

## Diagnostics

Full adapter and driver status:

```bash
ghostlink -diag
```

Sample output includes:
- Adapter map (role → interface → driver → monitor mode support)
- RTL8812AU USB presence check and DKMS state if interface is missing
- MT7612U USB presence check and mt76 module state if interface is missing
- Loaded mt76 modules
- `mt76x2u` kernel availability via `modinfo`
- All toolchain dependencies

### MT7612U Troubleshooting Commands

```bash
# Check USB detection
lsusb | grep -i "0e8d\|7612"

# Check loaded mt76 modules
lsmod | grep mt76

# Check kernel module availability
modinfo mt76x2u

# Manually load the module
sudo modprobe mt76x2u

# Check dmesg for driver errors
dmesg | grep -i mt76 | tail -20

# Check wireless interfaces
iw dev

# Ghostlink diagnostics
ghostlink -diag
ghostlink -status
```

## Raspberry Pi 5 Validation Checklist

Run these checks on the Raspberry Pi 5 after setup:

- [ ] `ghostlink -status` shows management interface (onboard brcmfmac)
- [ ] `ghostlink -status` shows RTL8812AU Status: `wlanX (88XXau, ready)`
- [ ] `ghostlink -status` shows MT7612U Status: `wlanX (mt76x2u, ready)` (if adapter is plugged in)
- [ ] `ghostlink -status` shows RTL88x2BU Status: `wlanX (rtw_8822bu)`
- [ ] `ghostlink -diag` shows `88XXau: Available`
- [ ] `ghostlink -diag` shows `mt76x2u: Available`
- [ ] `sudo ghostlink scan` uses RTL8812AU or MT7612U (not management interface)
- [ ] `sudo ghostlink pentest --ssid "Test"` selects RTL8812AU or MT7612U
- [ ] Management interface (brcmfmac) is never used for scan or pentest
- [ ] `ghostlink -ap-start` starts AP on RTL88x2BU, uplink via RTL8812AU or MT7612U
- [ ] Internet is accessible through the uplink adapter during AP operation

## Updating

```bash
ghostlink -update
```

## Adapter Strategy Documents

- [docs/rtl8812au_strategy.md](docs/rtl8812au_strategy.md) — RTL8812AU DKMS driver install strategy for Raspberry Pi 5
- [docs/mt7612u_strategy.md](docs/mt7612u_strategy.md) — MT7612U in-kernel mt76 driver strategy

## Basic Troubleshooting

- **Adapters not showing up**: Run `ghostlink -diag` to verify drivers are loaded. Ensure the Pi has adequate power (Pi 5 requires 27W for full USB peripheral support).
- **MT7612U not detected**: Run `sudo modprobe mt76x2u`, replug the adapter, then `ghostlink -diag`. See [docs/mt7612u_strategy.md](docs/mt7612u_strategy.md).
- **RTL8812AU not detected**: Run `sudo modprobe 88XXau`, replug, then `ghostlink -diag`. See [docs/rtl8812au_strategy.md](docs/rtl8812au_strategy.md).
- **AP failing to start**: Check if `hostapd` or `dnsmasq` is crashing. Run `ghostlink -diag` and check `/var/log/syslog`.
- **Cannot connect to management network**: The tool uses NetworkManager. Check with `nmcli connection show`.

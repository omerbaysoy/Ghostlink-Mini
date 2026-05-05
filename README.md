# Ghostlink

Ghostlink is a Raspberry Pi / Debian SBC pentest CLI platform for multi-adapter wireless assessment, tool orchestration, AP/uplink workflows, network discovery, and field diagnostics.

The tools Ghostlink prepares (Wifite, Airgeddon, Nmap, aircrack-ng, hostapd, dnsmasq, tmux) are installed system-wide and remain usable outside Ghostlink. The CLI command is `ghostlink`. Setup installs the runtime to `/opt/ghostlink` and registers `/usr/local/bin/ghostlink`.

Validated on Raspberry Pi 5 / Debian Trixie / arm64 / kernel 6.12.x with all four supported USB Wi-Fi adapters (RTL8812AU, MT7612U, RTL88x2BU, RTL8188EUS) and onboard `brcmfmac` management Wi-Fi.

## Platform Support

Chapter 1 targets:

| Platform | Profile | Status | GPU Memory Policy |
|---|---|---|---|
| Raspberry Pi Zero W | `rpi_zero_w` | tested | 16MB headless floor |
| Raspberry Pi Zero 2 W | `rpi_zero_2_w` | tested | 16MB headless floor |
| Raspberry Pi 3B | `rpi_3b` | tested | 16MB headless floor |
| Raspberry Pi 5 | `rpi_5` | tested | Skipped / firmware-managed |
| Raspberry Pi 1 | `rpi_1` | supported/untested | 16MB headless floor |
| Raspberry Pi 2 | `rpi_2` | supported/untested | 16MB headless floor |
| Raspberry Pi 3B+ | `rpi_3b_plus` | supported/untested | 16MB headless floor |
| Raspberry Pi 4 | `rpi_4` | supported/untested | 16MB headless floor |
| Unknown Raspberry Pi | `unknown_rpi` | supported/untested | Skipped |
| Generic Debian-based Linux SBC | `debian_sbc` | best-effort | Skipped |

Target OS images:

- Raspberry Pi OS Lite 32-bit Bookworm
- Raspberry Pi OS Lite 64-bit Bookworm
- Raspberry Pi OS Lite 32-bit Trixie
- Raspberry Pi OS Lite 64-bit Trixie
- Generic Debian-based Linux SBCs on a best-effort basis

See [docs/raspberry_pi_compatibility.md](docs/raspberry_pi_compatibility.md) for the profile matrix, setup behavior, ZRAM/GPU/overclock notes, and known limitations.

## Adapter Roles

| # | Adapter | Role | Key |
|---|---|---|---|
| 1 | Onboard Wi-Fi, usually `brcmfmac` on Raspberry Pi | Management only; never used for scan, pentest, monitor, AP, or attack workflows | `management` |
| 2 | RTL8812AU (USB ID `0bda:8812`) | Main pentest/access/uplink adapter | `rtl8812au` |
| 3 | MT7612U (USB ID `0e8d:7612` and others) | Second main pentest/access/uplink adapter | `mt7612u` |
| 4 | RTL88x2BU (USB ID `0bda:b812`) | AP adapter; creates Ghostlink-AP | `rtl88x2bu` |
| 5 | RTL8188EUS (USB ID `2357:010c`) | Backup adapter | `rtl8188eus` |

## Supported USB Adapters

| Adapter | Chipset | USB IDs | Driver | Role |
|---|---|---|---|---|
| Alfa AWUS036ACS and similar | RTL8812AU | `0bda:8812` | `88XXau` (aircrack-ng DKMS), fallback `8812au` | Pentest / uplink |
| Alfa AWUS036ACM and similar | MT7612U | `0e8d:7612`, `0e8d:761a`, `2001:3a02`, `0b05:17d1`, `148f:7612`, `13b1:003e` | `mt76x2u` (in-kernel) | Pentest / uplink |
| RTL88x2BU adapters | RTL88x2BU | `0bda:b812` | `rtw_8822bu` / `rtw88_8822bu` | AP |
| RTL8188EUS adapters | RTL8188EUS | `2357:010c` | `8188eu` | Backup |

## Setup and Installation

WARNING: Requires root access and an active internet connection.

```bash
sudo ./setup.sh
```

Setup installs and prepares all supported driver paths even when the adapters are not plugged in:

- RTL8812AU pentest driver: aircrack-ng/rtl8812au v5.6.4.2, fallback morrownr/8812au-20210820
- RTL88x2BU driver via lwfinger/rtw88 for the AP role
- RTL8188EUS backup driver
- MT7612U in-kernel mt76 module check and `firmware-misc-nonfree`

System-wide tool installation (usable outside Ghostlink):

| Tool | Path | Source |
|---|---|---|
| `wifite` / `wifite2` | `/usr/local/bin/wifite` and `/usr/local/bin/wifite2` | wrappers to `python3 /opt/wifite2/Wifite.py` (kimocoder/wifite2) |
| `airgeddon` | `/usr/local/bin/airgeddon` | symlink to `/opt/airgeddon/airgeddon.sh` (v1s1t0r1sh3r3) |
| `nmap` | `/usr/bin/nmap` | apt package |
| `aircrack-ng` | `/usr/bin/aircrack-ng` | apt package |
| `tmux` | `/usr/bin/tmux` | apt package; required for Airgeddon headless mode |
| `hostapd`, `dnsmasq` | `/usr/sbin/...` | apt packages used by Ghostlink-AP |

Wifite dependency set (installed best-effort by setup):

| Tool | Purpose |
|---|---|
| `aircrack-ng` | WPA/WEP cracking, monitor mode helpers |
| `tshark` | Packet capture analysis (requires `wireshark-common`) |
| `hashcat` | GPU/CPU hash cracking |
| `hcxdumptool` | PMKID / EAPOL capture |
| `hcxtools` (provides `hcxpcapngtool`) | hashcat-format conversion |
| `reaver`, `bully` | WPS PIN attacks |
| `cowpatty` | WPA-PSK rainbow-table attacks |
| `macchanger` | MAC randomization |

Optional Wifite tools (`tshark`, `hashcat`, `hcxdumptool`, `hcxtools`) are installed best-effort; setup logs warnings and continues if any are unavailable on the running distribution.

System telemetry:

| Tool | Purpose |
|---|---|
| `lm-sensors` (provides `sensors`) | Pi 5 / SBC temperature and voltage telemetry |

Setup syncs the installed runtime to `/opt/ghostlink` and installs the global CLI command as `ghostlink`.

Setup also detects the platform profile and applies only compatible system tuning:

- Profile-aware ZRAM sizing
- Raspberry Pi `gpu_mem=16` only on exact older Pi profiles where this is safe for headless operation
- Raspberry Pi 5 GPU memory is skipped because it is firmware-managed/dynamic
- Existing user `gpu_mem` settings are preserved
- Safe default Raspberry Pi CPU profile where supported and no user overclock already exists
- Raspberry Pi filesystem expansion through `raspi-config nonint do_expand_rootfs` when available
- Pi 5 fan and PCIe tuning only on `rpi_5`
- No Raspberry Pi boot config changes on generic Debian SBCs

To skip Ghostlink's default Raspberry Pi CPU profile, run:

```bash
sudo GHOSTLINK_DISABLE_RPI_OC=1 ./setup.sh
```

## Running the Tool

Interactive CLI menu:

```bash
ghostlink
```

Interactive menu options include:

| # | Option |
|---|---|
| 1 | Status |
| 2 | Start Wifite |
| 3 | Start Airgeddon |
| 4 | Start Nmap |
| 5 | Show saved credentials |
| 6 | Connect to saved network |
| 7 | Start Ghostlink-AP on RTL88x2BU |
| 8 | Stop Ghostlink-AP |
| 9 | Restart networking services |
| 10 | Run diagnostics |
| 11 | Update Ghostlink |
| 12 | Adapter roles (view) |
| 13 | Monitor mode toggle |
| 14 | Exit |

> **Wifite launcher**: Start Wifite first lists external pentest-capable adapters (RTL8812AU, MT7612U, RTL8188EUS, RTL88x2BU as last resort) excluding the management interface. After adapter selection, you can optionally provide a target SSID/BSSID; pressing Enter at the SSID prompt launches Wifite interactively on the selected adapter so you can pick targets from a Wifite scan. The management interface is never offered.

> **Airgeddon headless on Raspberry Pi**: When `DISPLAY` and `WAYLAND_DISPLAY` are both unset (typical for SSH/serial sessions), Ghostlink expects `tmux` to be installed and warns if it is missing. Airgeddon may still report "no graphics system detected" on first launch — open its Options menu and enable headless/tmux mode, then return to the main menu. Ghostlink validates the selected external adapter and blocks the management interface before launching Airgeddon, but Airgeddon may still display its own interface picker — select the validated adapter inside Airgeddon. Never select the management/onboard Wi-Fi inside Airgeddon.

> **Nmap launcher**: Start Nmap requires nmap to be installed system-wide; if missing, it shows `Run sudo ./setup.sh --update`. Pressing Enter at the target prompt cancels with `Cancelled: no Nmap target provided.` (no silent return, no fake failed scan job).

> **Monitor mode**: The management/onboard Wi-Fi interface is never offered for monitor mode. Only external adapters that advertise monitor mode support can be toggled.

> **Adapter roles**: Role assignment is automatic based on USB ID. The management interface is permanently excluded from all active roles (scan, pentest, AP, monitor).

## Ghostlink-AP Routing (Phase 1)

When you start Ghostlink-AP, the launcher walks through:

1. **Select AP adapter** — RTL88x2BU is preferred; RTL8812AU / MT7612U / RTL8188EUS are accepted as fallbacks. The management interface is excluded.
2. **Select routing mode** — `Direct NAT` or `VPN Gateway`.
3. **Direct NAT** — pick any non-AP interface to NAT AP-client traffic through (`eth0`, `wlan0` management Wi-Fi, RTL8812AU, MT7612U, etc.). The default-route interface is flagged.
4. **VPN Gateway (Phase 1)** — pick an existing tunnel interface. Ghostlink detects interfaces matching `wg*`, `tun*`, `tailscale0`, `proton*`, `nordlynx*`, `mullvad*`, `ppp*`, `gpd*` and lists only those that are up. AP-client traffic is NAT'd through the chosen tunnel and a kill-switch (`iptables -A FORWARD -i <ap> -s 10.0.0.0/24 ! -o <vpn> -j DROP`) prevents AP clients from leaking to other interfaces.

**VPN Gateway Phase 1 scope:**

- Ghostlink does **not** configure VPN providers. Bring up your WireGuard / OpenVPN / Tailscale tunnel before starting the AP.
- Phase 1 routes AP clients through an already-up tunnel interface only.
- The kill-switch applies to AP-client traffic only (anchored on the AP subnet `10.0.0.0/24`); the Pi's own management connectivity (SSH, etc.) is untouched.
- If the chosen VPN interface is down or missing, Ghostlink-AP refuses to start (fail-closed).
- `Stop Ghostlink-AP` removes both the NAT/forwarding rules and the kill-switch.

**Not implemented in Phase 1** (future roadmap): Tor gateway, generic proxy gateway, VPN provider config import/management.

## Direct Commands

```text
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
                                               Run Nmap scan
```

## Scan and Pentest Examples

Auto-select best available adapter: RTL8812AU first, MT7612U second.

```bash
sudo ghostlink scan
sudo ghostlink pentest --ssid "TargetNetwork"
```

Explicitly select MT7612U by interface:

```bash
ghostlink -status
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
5. Management interface: never used

## Diagnostics

Full platform, adapter, and driver status:

```bash
ghostlink -diag
```

Sample output includes:

- Platform model, profile, tested/untested/best-effort status
- OS, codename, architecture, and kernel
- ZRAM status
- Overclock and GPU memory status
- Pi 5 fan config status and Pi 5 NVMe-aware filesystem expansion behavior
- Adapter map: role -> interface -> driver -> monitor mode support -> current mode
- Management interface protection status
- Detected USB Wi-Fi devices from `lsusb`
- RTL8812AU USB presence check and DKMS state if interface is missing
- MT7612U physical presence, mapped interface, driver binding, monitor support, and mt76 module state
- Driver compatibility warnings for headers, DKMS, and candidate modules
- Ghostlink-AP routing snapshot: mode (`Direct NAT` / `VPN Gateway` / `inactive`), AP interface, AP subnet, uplink or VPN interface, kill-switch state
- Toolchain dependency status: `wifite`, `wifite2`, `airgeddon`, `tmux`, `nmap`, `aircrack-ng`, `tshark`, `hashcat`, `hcxdumptool`, `hcxpcapngtool`, `reaver`, `bully`, `cowpatty`, `macchanger`, `sensors`, `hostapd`, `dnsmasq`, `iw`, `nmcli` (each with absolute path)
- Headless environment detection (`DISPLAY`/`WAYLAND_DISPLAY`) and Airgeddon tmux readiness

## Real Tested USB Adapter IDs

Confirmed on Raspberry Pi 5 / Trixie / arm64 with all four adapters connected simultaneously:

| USB ID | Chipset | Role | Driver bound |
|---|---|---|---|
| `0bda:8812` | RTL8812AU | Pentest/uplink #1 | `88XXau` |
| `0e8d:7612` | MT7612U | Pentest/uplink #2 | `mt76x2u` |
| `0bda:b812` | RTL88x2BU | Ghostlink-AP | `rtw_8822bu` |
| `2357:010c` | RTL8188EUS | Backup pentest | `8188eu` |

The onboard Pi 5 Wi-Fi (`brcmfmac`) is mapped to `management` and is excluded from every active role.

## MT7612U Troubleshooting Commands

```bash
lsusb | grep -i "0e8d\|7612"
lsmod | grep mt76
modinfo mt76x2u
sudo modprobe mt76x2u
dmesg | grep -i mt76 | tail -20
iw dev
ghostlink -diag
ghostlink -status
```

## Validation Checklist

Run these checks on target hardware after setup. Local Windows syntax checks do not count as hardware validation.

- [ ] `ghostlink -status` shows the correct platform profile and support status
- [ ] `ghostlink -status` shows a management interface, usually onboard `brcmfmac` on Raspberry Pi
- [ ] `ghostlink -status` shows RTL8812AU Status: `wlanX (88XXau, ready)` when plugged in
- [ ] `ghostlink -status` shows MT7612U Status: `wlanX (mt76x2u, ready)` when plugged in
- [ ] `ghostlink -status` shows RTL88x2BU Status: `wlanX (rtw_8822bu)` when plugged in
- [ ] `ghostlink -diag` shows platform, OS/codename/arch/kernel, ZRAM, overclock, GPU memory, and driver warnings
- [ ] `ghostlink -diag` shows `88XXau: Available` after RTL8812AU setup succeeds
- [ ] `ghostlink -diag` shows `mt76x2u: Available` on kernels with MT7612U support
- [ ] `sudo ghostlink scan` uses RTL8812AU or MT7612U, not the management interface
- [ ] `sudo ghostlink pentest --ssid "Test"` asks for authorized/lab-use confirmation
- [ ] Management interface is never used for scan or pentest
- [ ] `ghostlink -ap-start` starts AP on RTL88x2BU, uplink via RTL8812AU or MT7612U
- [ ] Internet is accessible through the uplink adapter during AP operation

## Known Limitations

- Airgeddon may still ask the user to select the validated adapter inside its own UI; Ghostlink does not enforce Airgeddon's interface picker.
- Raspberry Pi hardware validation must be performed per board and per kernel; Windows-local syntax checks do not count as hardware validation.
- DKMS-based drivers (RTL8812AU, RTL88x2BU, RTL8188EUS) require kernel headers that match the running kernel. Setup will skip DKMS driver builds if headers are missing and still continue with MT7612U setup.
- Pi 5 PCIe Gen 3 tuning only matters when compatible Pi 5 storage hardware is present.
- AP routing supports Direct NAT and VPN Gateway Phase 1 (existing up tunnel interfaces only). Tor gateway, proxy gateway, and VPN provider import/management are future roadmap items.

## Roadmap

These items are future work and are not claimed as implemented.

Wi-Fi:
- Stronger adapter role management
- Wifite workflow improvements
- Airgeddon workflow improvements
- Capture/session reporting
- Credential/database reporting
- AP/uplink automation

Bluetooth:
- Bluetooth adapter detection
- BLE scanning
- Device inventory
- Optional lab-only Bluetooth assessment workflows

RF / Sub-GHz:
- CC1101 support
- Signal capture/analysis helpers
- Replay-safe lab tooling
- Frequency/device inventory

GPS / Field Logging:
- GPS module support
- Scan/session geotagging
- Field notes
- Exportable reports

Network Discovery:
- Nmap workflow improvements
- Host inventory
- Local subnet mapping
- Service history

Hardware/SBC:
- Raspberry Pi Zero W / Zero 2 W / 3B / 5 validation
- Raspberry Pi 1 / 2 / 4 untested support tracking
- Generic Debian SBC best-effort support

Reporting/Database:
- Structured session reports
- Saved credentials view/export
- Adapter/session logs
- HTML/JSON/Markdown exports

Future Expansion:
- SDR support
- NRF24L01 support
- PN532/NFC support
- TUI dashboard
- Optional web dashboard
- Plugin/tool registry

## Updating

```bash
ghostlink -update
```

## Adapter Strategy Documents

- [docs/raspberry_pi_compatibility.md](docs/raspberry_pi_compatibility.md): Raspberry Pi and Debian SBC compatibility matrix
- [docs/rtl8812au_strategy.md](docs/rtl8812au_strategy.md): RTL8812AU DKMS driver install strategy
- [docs/mt7612u_strategy.md](docs/mt7612u_strategy.md): MT7612U in-kernel mt76 driver strategy

## Basic Troubleshooting

- Adapters not showing up: Run `ghostlink -diag` to verify drivers are loaded. Ensure the SBC has adequate power for multiple USB Wi-Fi adapters.
- MT7612U not detected: Run `sudo modprobe mt76x2u`, replug the adapter, then `ghostlink -diag`. See [docs/mt7612u_strategy.md](docs/mt7612u_strategy.md).
- RTL8812AU not detected: Run `sudo modprobe 88XXau`, replug, then `ghostlink -diag`. See [docs/rtl8812au_strategy.md](docs/rtl8812au_strategy.md).
- AP failing to start: Check if `hostapd` or `dnsmasq` is crashing. Run `ghostlink -diag` and check `/var/log/syslog`.
- Cannot connect to management network: The tool uses NetworkManager. Check with `nmcli connection show`.

# Raspberry Pi and Debian SBC Compatibility

This document describes the Chapter 1 platform compatibility layer for Ghostlink-Mini.

## Target Platforms

| Platform | Profile | Status | ZRAM | GPU Memory | Default CPU Profile | Fan/Storage Notes | Driver Notes |
|---|---|---|---|---|---|---|---|
| Raspberry Pi Zero W | `rpi_zero_w` | tested/owned | 512 MB | 16 MB | Stock-safe baseline; no automatic CPU overclock | No Pi 5 fan/PCIe tuning | All supported driver paths are prepared when headers are available; external powered USB is recommended |
| Raspberry Pi Zero 2 W | `rpi_zero_2_w` | tested/owned | 1024 MB | 16 MB | `arm_freq=1100` | No Pi 5 fan/PCIe tuning | All supported driver paths are prepared when headers are available |
| Raspberry Pi 3B | `rpi_3b` | tested/owned | 1024 MB | 16 MB | `arm_freq=1300`, `core_freq=500`, `over_voltage=2` | No Pi 5 fan/PCIe tuning | All supported driver paths are prepared when headers are available |
| Raspberry Pi 5 | `rpi_5` | tested/owned | 2048 MB | 32 MB | `arm_freq=2600` | Active Cooler thresholds and PCIe Gen 3 can be configured only on Pi 5 | All supported driver paths are prepared when headers are available |
| Raspberry Pi 1 | `rpi_1` | supported/untested | 512 MB | 16 MB | Not applied by default | No Pi 5 fan/PCIe tuning | Best effort; external powered USB is strongly recommended |
| Raspberry Pi 2 | `rpi_2` | supported/untested | 1024 MB | 16 MB | Not applied by default | No Pi 5 fan/PCIe tuning | Best effort |
| Raspberry Pi 3B+ | `rpi_3b_plus` | supported/untested | 1024 MB | 16 MB | Not applied by default | No Pi 5 fan/PCIe tuning | Best effort; auto-OC is skipped |
| Raspberry Pi 4 | `rpi_4` | supported/untested | 2048 MB | 32 MB | Not applied by default | No Pi 5 fan/PCIe tuning | Best effort |
| Unknown Raspberry Pi | `unknown_rpi` | supported/untested | 1024 MB | 16 MB | Not applied by default | No Pi 5 fan/PCIe tuning | Best effort |
| Generic Debian-based Linux SBC | `debian_sbc` | best-effort | 1024 MB | Skipped | Not applicable | Raspberry Pi boot config, fan, PCIe, and `raspi-config` steps are skipped | Driver preparation runs when Debian packages, headers, DKMS, and modules are available |

## Target OS Images

- Raspberry Pi OS Lite 32-bit Bookworm
- Raspberry Pi OS Lite 64-bit Bookworm
- Raspberry Pi OS Lite 32-bit Trixie
- Raspberry Pi OS Lite 64-bit Trixie
- Generic Debian-based Linux SBCs on a best-effort basis

`ghostlink -status` and `ghostlink -diag` show the detected model, profile, support status, OS codename, architecture, kernel, ZRAM status, overclock status, GPU memory status, and driver compatibility warnings.

## Platform Detection

Setup and runtime diagnostics detect the platform from:

- `/proc/device-tree/model` first
- `/proc/cpuinfo` as a Raspberry Pi fallback
- `/etc/os-release` for OS name and codename
- `dpkg --print-architecture` or `uname -m` for architecture
- `uname -r` for kernel version

Profiles emitted by the detection layer:

- `rpi_zero_w`
- `rpi_zero_2_w`
- `rpi_1`
- `rpi_2`
- `rpi_3b`
- `rpi_3b_plus`
- `rpi_4`
- `rpi_5`
- `unknown_rpi`
- `debian_sbc`

## Setup Behavior

Setup remains adapter-presence independent. It prepares RTL8812AU, MT7612U, RTL88x2BU, and RTL8188EUS support even when no USB adapters are plugged in.

Raspberry Pi-specific behavior:

- ZRAM size follows the detected profile.
- GPU memory is set only when no existing `gpu_mem` value is present.
- Default CPU profile is applied only on supported profiles and only when no user CPU/voltage setting exists.
- Filesystem expansion is requested through `raspi-config nonint do_expand_rootfs` when `raspi-config` is available. On Raspberry Pi 5 with NVMe root, expansion is skipped automatically.
- Ghostlink-managed boot config additions include `[all]` before Ghostlink lines so they are not appended inside a model-specific conditional section.
- Pi 5 Active Cooler thresholds are applied only on `rpi_5`.
- Pi 5 PCIe Gen 3 storage tuning is applied only on `rpi_5`.

Generic Debian SBC behavior:

- ZRAM is configured best-effort.
- Raspberry Pi boot config edits are skipped.
- `raspi-config` filesystem expansion is skipped.
- Pi 5 fan and PCIe tuning are skipped.
- Driver preparation proceeds when apt, DKMS, headers, and kernel modules are available.

To skip Ghostlink's default Raspberry Pi CPU profile:

```bash
sudo GHOSTLINK_DISABLE_RPI_OC=1 ./setup.sh
```

## Driver Compatibility

The Chapter 1 setup path preserves the existing adapter strategy:

- RTL8812AU uses aircrack-ng/rtl8812au `v5.6.4.2` first and falls back to morrownr/8812au-20210820.
- MT7612U uses the in-kernel `mt76x2u` stack and `firmware-misc-nonfree`.
- RTL88x2BU uses lwfinger/rtw88 for the AP role.
- RTL8188EUS uses the aircrack-ng RTL8188EUS driver as backup.
- The management Wi-Fi interface is protected from scan, pentest, monitor, AP, and attack workflows.

Setup logs driver compatibility state to `/var/log/ghostlink/setup.log`, including:

- Platform profile and support status
- OS codename, architecture, and kernel
- Kernel header status and candidate header packages
- DKMS status
- Candidate module availability for RTL8812AU, MT7612U, RTL88x2BU, RTL8188EUS, and onboard Broadcom Wi-Fi

## Known Limitations

- Hardware validation must be performed on the actual target boards. Windows-local checks only validate syntax and import safety.
- Raspberry Pi 1 and Zero W have limited CPU, RAM, and USB/power headroom. Use a powered USB hub when multiple adapters are attached.
- Third-party DKMS drivers require kernel headers that match the running kernel.
- Generic Debian SBC support depends on the board vendor kernel exposing compatible modules and headers.
- Pi 5 PCIe Gen 3 tuning only matters when compatible Pi 5 storage hardware is present.

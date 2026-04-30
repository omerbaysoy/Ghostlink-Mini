# RTL8812AU Driver Strategy - Raspberry Pi 5 (Kernel 6.12+)

This document records the exact steps and strategy required to successfully build and deploy the RTL8812AU driver with monitor mode and packet injection support on a Raspberry Pi 5 running a modern kernel (e.g., `6.12.75+rpt-rpi-2712 aarch64`).

## The Working Strategy

Through testing, we discovered that the `aircrack-ng/rtl8812au` (`v5.6.4.2` branch) driver is the most reliable driver for pentesting requirements on this kernel when properly configured.

### Key Implementation Details:

1. **Conflict Resolution:**
   Before installing the driver, all conflicting in-kernel modules and older DKMS variants must be cleanly stopped and blacklisted.
   *   Conflicting modules removed via `modprobe -r`: `rtw_8812au`, `rtw88_8812au`, `rtl8xxxu`, `8812au`, `88XXau`
   *   These modules are then blacklisted via `/etc/modprobe.d/ghostlink-rtl8812au.conf`.

2. **Platform Configuration for aarch64:**
   The `Makefile` inside the `aircrack-ng` repository defaults to PC architectures (`i386`). For the Raspberry Pi 5, these must be explicitly disabled and swapped to ARM64 configurations using `sed` before building:
   *   Set `CONFIG_PLATFORM_I386_PC = n`
   *   Set `CONFIG_PLATFORM_ARM64_RPI = y`
   *   Modify `dkms.conf` to explicitly pass `ARCH=arm64` to the make command.

3. **Installation Pipeline:**
   ```bash
   # Remove stale dkms
   dkms remove -m 8812au -v [stale_version] --all
   
   # Clone the target branch
   git clone -b v5.6.4.2 --single-branch https://github.com/aircrack-ng/rtl8812au.git /usr/src/rtl8812au
   
   # Modify platform config (as noted above)
   
   # Install via DKMS
   cd /usr/src/rtl8812au && make dkms_install
   
   # Blacklist conflicts and load the new module
   echo "blacklist rtw_8812au" >> /etc/modprobe.d/ghostlink-rtl8812au.conf
   echo "blacklist rtw88_8812au" >> /etc/modprobe.d/ghostlink-rtl8812au.conf
   echo "blacklist rtl8xxxu" >> /etc/modprobe.d/ghostlink-rtl8812au.conf
   echo "options 88XXau rtw_led_ctrl=0" >> /etc/modprobe.d/ghostlink-rtl8812au.conf
   
   modprobe 88XXau
   ```

4. **Interface Detection:**
   Relying solely on driver names (like `88XXau`) or interface names (`wlan1`, `wlan2`) is unreliable because Linux can unpredictably shuffle interface indices upon reboot.
   *   The solution is to map the physical USB path using `sysfs`.
   *   Read `/sys/class/net/<iface>/device/idVendor` and `idProduct`.
   *   The driver is considered successfully bound if an interface is physically mapped to USB ID `0bda:8812` and the `88XXau` driver is loaded.

## Fallback Strategy

If `aircrack-ng` fails to compile (e.g., due to missing kernel headers or unsupported bleeding-edge kernels), the setup script automatically falls back to:
*   `morrownr/8812au-20210820`
*   This driver handles basic uplink connectivity well but lacks full stability for frame injection and advanced `wifite` monitor mode features. It will bind the module as `8812au`.

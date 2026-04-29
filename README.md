# Ghostlink-Mini

Ghostlink-Mini is a Raspberry Pi 5 CLI tool for authorized/lab Wi-Fi workflows using multiple Wi-Fi adapters with fixed roles.

## Adapter Roles
1. **Raspberry Pi 5 Onboard Wi-Fi**: Management-only adapter. Ensures stable connectivity to the Pi.
2. **RTL8812AU**: Main pentest/access/uplink adapter. Used to perform Wi-Fi assessments and provide the internet uplink.
3. **RTL88x2BU**: Main AP adapter. Creates the `Ghostlink-AP` access point to share internet.
4. **RTL8188EUS**: Backup adapter.

## Setup and Installation
**WARNING: Requires root access and an active internet connection.**
```bash
sudo ./setup.sh
```

## Running the Tool
To launch the interactive CLI menu:
```bash
ghostlink
```

## Direct Commands
- `ghostlink -status` : Show system and adapter status
- `ghostlink -db` : Show database status
- `ghostlink -creds` : View saved credentials
- `ghostlink scan [--iface <interface>]` : Scan for nearby networks
- `ghostlink pentest --iface <interface> --ssid "<SSID>" [--bssid <BSSID>]` : Start automated pentest
- `ghostlink -connect` : Connect RTL8812AU to a recovered network
- `ghostlink -ap-start` : Start Ghostlink-AP on RTL88x2BU
- `ghostlink -ap-stop` : Stop Ghostlink-AP
- `ghostlink -diag` : Run system diagnostics
- `ghostlink -restart-net` : Restart networking services
- `ghostlink -update` : Pull latest version and update

## Updating
```bash
ghostlink -update
```

## Basic Troubleshooting
- **Adapters not showing up**: Run `ghostlink -diag` to verify the drivers are installed properly. Ensure the Pi has adequate power (Pi 5 requires 27W for full USB peripheral support).
- **AP failing to start**: Check if `hostapd` or `dnsmasq` is crashing. Run `ghostlink -diag` and check `/var/log/syslog`.
- **Cannot connect to management network**: The tool uses NetworkManager. You can manually check your connection with `nmcli connection show`.

#!/bin/bash

# Ghostlink-Mini Setup Script

set -o pipefail

INSTALL_DIR="/opt/ghostlink-mini"
SRC_ENTRY="src/ghostlink.py"
LAUNCHER="/usr/local/bin/ghostlink"
SETUP_LOG="/var/log/ghostlink/setup.log"

UPDATE_MODE=0

usage() {
    cat <<USAGE
Usage: sudo ./setup.sh [--update] [--help]

Options:
  --update        Reinstall/update files without prompting for management Wi-Fi
  -h, --help      Show this help
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --update)
            UPDATE_MODE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 2
            ;;
    esac
    shift
done

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup.sh). Use ./setup.sh --help for options."
    exit 1
fi

mkdir -p /var/log/ghostlink
touch "$SETUP_LOG" || {
    echo "[-] Cannot write setup log at $SETUP_LOG"
    exit 1
}

log() {
    echo "$@" | tee -a "$SETUP_LOG"
}

run_logged() {
    log "[cmd] $*"
    "$@" >>"$SETUP_LOG" 2>&1
}

require_entrypoint() {
    local base_dir="$1"
    if [ ! -f "$base_dir/$SRC_ENTRY" ]; then
        log "[-] Missing required file: $base_dir/$SRC_ENTRY"
        exit 1
    fi
}

sync_project() {
    local source_dir
    source_dir="$(pwd)"
    require_entrypoint "$source_dir"

    mkdir -p "$INSTALL_DIR"

    if [ "$source_dir" = "$INSTALL_DIR" ]; then
        log "[+] Running from $INSTALL_DIR; project files already in place."
        return
    fi

    log "[+] Syncing project to $INSTALL_DIR..."
    if command -v rsync >/dev/null 2>&1; then
        run_logged rsync -a --delete \
            --exclude '.pytest_cache/' \
            --exclude '__pycache__/' \
            "$source_dir/" "$INSTALL_DIR/"
    else
        log "[!] rsync not found; using cp fallback without deleting stale files."
        run_logged cp -a "$source_dir/." "$INSTALL_DIR/"
    fi

    require_entrypoint "$INSTALL_DIR"
}

install_launcher() {
    log "[+] Installing global command 'ghostlink'..."
    require_entrypoint "$INSTALL_DIR"
    chmod +x "$INSTALL_DIR/$SRC_ENTRY"

    local tmp_launcher
    tmp_launcher="$(mktemp)"
    cat >"$tmp_launcher" <<'LAUNCHER'
#!/bin/sh
export PYTHONPATH="/opt/ghostlink-mini/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 /opt/ghostlink-mini/src/ghostlink.py "$@"
LAUNCHER
    install -m 0755 "$tmp_launcher" "$LAUNCHER"
    rm -f "$tmp_launcher"
}

detect_onboard_wifi() {
    local iface driver type

    if ! command -v iw >/dev/null 2>&1; then
        return
    fi

    for iface in $(iw dev 2>/dev/null | awk '/Interface/ {print $2}'); do
        driver="$(basename "$(readlink "/sys/class/net/$iface/device/driver" 2>/dev/null)" 2>/dev/null)"
        type="$(cat "/sys/class/net/$iface/uevent" 2>/dev/null | awk -F= '/DEVTYPE/ {print $2}')"
        if [ "$driver" = "brcmfmac" ] || [ "$driver" = "brcmsmac" ]; then
            echo "$iface"
            return
        fi
        if [ "$type" = "wlan" ] && [ -z "$driver" ]; then
            echo "$iface"
            return
        fi
    done
}

configure_management_wifi() {
    if [ "$UPDATE_MODE" -eq 1 ]; then
        return
    fi

    echo ""
    log "--- Management Network Configuration ---"
    log "This step creates a NetworkManager profile for the onboard management Wi-Fi."
    log "Leave SSID empty to skip this step and preserve current connectivity."
    read -r -p "SSID: " MGMT_SSID
    if [ -z "$MGMT_SSID" ]; then
        log "[+] Skipping management Wi-Fi configuration."
        return
    fi
    read -r -s -p "Password: " MGMT_PASS
    echo ""
    read -r -p "Static IP (optional, e.g. 192.168.1.100/24): " MGMT_IP
    read -r -p "Gateway (required only with static IP): " MGMT_GW
    read -r -p "DNS (optional, e.g. 8.8.8.8): " MGMT_DNS

    local onboard_iface
    onboard_iface="$(detect_onboard_wifi)"
    if [ -z "$onboard_iface" ]; then
        log "[-] Could not identify onboard Wi-Fi. Management Wi-Fi not changed."
        return 1
    fi

    if ! command -v nmcli >/dev/null 2>&1; then
        log "[-] nmcli is missing. Management Wi-Fi not changed."
        return 1
    fi

    log "[+] Configuring $onboard_iface for management via NetworkManager..."
    nmcli connection delete "ghostlink-mgmt" >>"$SETUP_LOG" 2>&1 || true
    run_logged nmcli connection add type wifi ifname "$onboard_iface" con-name "ghostlink-mgmt" ssid "$MGMT_SSID" || return 1
    run_logged nmcli connection modify "ghostlink-mgmt" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$MGMT_PASS" connection.autoconnect yes

    if [ -n "$MGMT_IP" ]; then
        run_logged nmcli connection modify "ghostlink-mgmt" ipv4.addresses "$MGMT_IP" ipv4.method manual
        [ -n "$MGMT_GW" ] && run_logged nmcli connection modify "ghostlink-mgmt" ipv4.gateway "$MGMT_GW"
        [ -n "$MGMT_DNS" ] && run_logged nmcli connection modify "ghostlink-mgmt" ipv4.dns "$MGMT_DNS"
    else
        run_logged nmcli connection modify "ghostlink-mgmt" ipv4.method auto
    fi

    python3 - "$onboard_iface" >/etc/ghostlink/adapters.json <<'PY'
import json
import sys
print(json.dumps({"management": sys.argv[1]}, indent=4))
PY

    log "[+] Management profile saved as ghostlink-mgmt. Bring it up manually with: sudo nmcli connection up ghostlink-mgmt"
}

install_airgeddon() {
    if command -v airgeddon >/dev/null 2>&1; then
        log "[+] Airgeddon is already installed."
        return
    fi

    log "[+] Installing Airgeddon..."
    if [ -d /opt/airgeddon/.git ]; then
        run_logged git -C /opt/airgeddon pull --ff-only || return 1
    elif [ -e /opt/airgeddon ]; then
        log "[-] /opt/airgeddon exists but is not a git checkout. Move it aside and rerun setup."
        return 1
    else
        run_logged git clone --depth 1 https://github.com/v1s1t0r1sh3r3/airgeddon.git /opt/airgeddon || return 1
    fi
    ln -sf /opt/airgeddon/airgeddon.sh /usr/local/bin/airgeddon
}

kernel_headers_available() {
    local release
    release="$(uname -r)"
    [ -d "/lib/modules/$release/build" ]
}

install_driver() {
    local name="$1"
    local repo_url="$2"
    local dir_name="$3"
    local check_module="$4"
    local install_script="${5:-install-driver.sh}"

    if lsmod | grep -q "^$check_module" || modinfo "$check_module" >/dev/null 2>&1; then
        log "[+] Driver $name ($check_module) already installed."
        return
    fi

    if ! kernel_headers_available; then
        log "[-] Kernel headers for $(uname -r) are missing; cannot build required driver $name."
        return 1
    fi

    log "[+] Installing $name..."
    mkdir -p /usr/src

    if [ -d "/usr/src/$dir_name/.git" ]; then
        run_logged git -C "/usr/src/$dir_name" pull --ff-only || return 1
    elif [ -e "/usr/src/$dir_name" ]; then
        log "[-] /usr/src/$dir_name exists but is not a git checkout. Move it aside and rerun setup."
        return 1
    else
        run_logged git clone "$repo_url" "/usr/src/$dir_name" || return 1
    fi

    if [ -x "/usr/src/$dir_name/$install_script" ]; then
        (cd "/usr/src/$dir_name" && ./"$install_script") >>"$SETUP_LOG" 2>&1 || return 1
    else
        log "[-] Missing executable installer /usr/src/$dir_name/$install_script"
        return 1
    fi
}

install_rtl8188eus() {
    if lsmod | grep -q "^8188eu" || modinfo 8188eu >/dev/null 2>&1; then
        log "[+] Driver RTL8188EUS (8188eu) already installed."
        return
    fi

    if ! kernel_headers_available; then
        log "[-] Kernel headers for $(uname -r) are missing; cannot build required driver RTL8188EUS."
        return 1
    fi

    log "[+] Installing RTL8188EUS..."
    if [ -d /usr/src/rtl8188eus/.git ]; then
        run_logged git -C /usr/src/rtl8188eus pull --ff-only || return 1
    elif [ -e /usr/src/rtl8188eus ]; then
        log "[-] /usr/src/rtl8188eus exists but is not a git checkout. Move it aside and rerun setup."
        return 1
    else
        run_logged git clone https://github.com/aircrack-ng/rtl8188eus.git /usr/src/rtl8188eus || return 1
    fi

    echo "blacklist r8188eu" >/etc/modprobe.d/ghostlink-realtek.conf
    (cd /usr/src/rtl8188eus && make && make install && modprobe 8188eu) >>"$SETUP_LOG" 2>&1 || return 1
}

echo "======================================"
echo "    Ghostlink-Mini Setup Script"
echo "======================================"
[ "$UPDATE_MODE" -eq 1 ] && log "Running in UPDATE mode..."

if [ "$UPDATE_MODE" -eq 0 ]; then
    echo "This script installs Ghostlink-Mini for Raspberry Pi OS / Debian."
    echo "It will not bring down your current management connection automatically."
    read -r -p "Press Enter to continue or Ctrl+C to abort..."
fi

log "[+] Creating Ghostlink-Mini directories..."
mkdir -p /etc/ghostlink /var/lib/ghostlink /var/log/ghostlink
chmod 755 /etc/ghostlink /var/lib/ghostlink /var/log/ghostlink

log "[+] Updating apt repositories..."
run_logged apt-get update -y || { log "[-] Failed to update apt"; exit 1; }

log "[+] Installing system dependencies..."
DEPENDENCIES="git rsync dkms build-essential bc libelf-dev raspberrypi-kernel-headers aircrack-ng hostapd dnsmasq iw rfkill iproute2 wireless-tools python3 python3-pip wifite network-manager"
run_logged apt-get install -y $DEPENDENCIES || { log "[-] Failed to install dependencies. See $SETUP_LOG"; exit 1; }

install_airgeddon || { log "[-] Failed to install Airgeddon. See $SETUP_LOG"; exit 1; }

sync_project
install_launcher
python3 "$INSTALL_DIR/$SRC_ENTRY" -db >>"$SETUP_LOG" 2>&1 || log "[!] Database initialization/status check reported a warning. Run ghostlink -db for details."

configure_management_wifi || log "[!] Management Wi-Fi configuration was skipped or failed; existing network state was left alone."

echo ""
log "--- Driver Installation ---"
log "Build/install output is logged to $SETUP_LOG"
install_driver "RTL8812AU" "https://github.com/morrownr/8812au-20210820.git" "8812au" "8812au" || { log "[-] Required driver RTL8812AU failed. See $SETUP_LOG"; exit 1; }
install_driver "RTL88x2BU" "https://github.com/morrownr/88x2bu-20210702.git" "88x2bu" "88x2bu" || { log "[-] Required driver RTL88x2BU failed. See $SETUP_LOG"; exit 1; }
install_rtl8188eus || { log "[-] Required driver RTL8188EUS failed. See $SETUP_LOG"; exit 1; }

echo ""
log "--- Verification ---"
if command -v ghostlink >/dev/null 2>&1; then
    log "[+] 'ghostlink' command installed successfully at $(command -v ghostlink)."
else
    log "[-] 'ghostlink' command failed to install."
    exit 1
fi

ghostlink -diag >>"$SETUP_LOG" 2>&1 || log "[!] ghostlink -diag reported warnings. See $SETUP_LOG"

log "[+] Cleaning up..."
run_logged apt-get autoremove -y || true
run_logged apt-get clean || true

echo "======================================"
echo "    Setup Complete!"
echo "    Run 'ghostlink' to start."
echo "======================================"

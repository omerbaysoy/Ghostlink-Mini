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

set_runtime_permissions() {
    local owner="${SUDO_USER:-root}"
    if [ -n "$owner" ] && [ "$owner" != "root" ] && id "$owner" >/dev/null 2>&1; then
        chown -R "$owner:$owner" /etc/ghostlink /var/lib/ghostlink /var/log/ghostlink
    fi
    chmod 750 /etc/ghostlink /var/lib/ghostlink /var/log/ghostlink
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
            --delete-excluded \
            --exclude '.pytest_cache/' \
            --exclude '__pycache__/' \
            "$source_dir/" "$INSTALL_DIR/"
    else
        log "[!] rsync not found; using cp fallback without deleting stale files."
        run_logged cp -a "$source_dir/." "$INSTALL_DIR/"
    fi

    require_entrypoint "$INSTALL_DIR"
    find "$INSTALL_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
}

install_launcher() {
    log "[+] Installing global command 'ghostlink'..."
    require_entrypoint "$INSTALL_DIR"
    chmod +x "$INSTALL_DIR/$SRC_ENTRY"

    local tmp_launcher
    tmp_launcher="$(mktemp)"
    cat >"$tmp_launcher" <<'LAUNCHER'
#!/bin/bash
export PYTHONPATH=/opt/ghostlink-mini/src
export PYTHONDONTWRITEBYTECODE=1
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

apt_package_available() {
    local package="$1"
    local candidate
    candidate="$(apt-cache policy "$package" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')"
    [ -n "$candidate" ] && [ "$candidate" != "(none)" ]
}

install_kernel_headers() {
    local release arch checked package
    release="$(uname -r)"
    arch="$(dpkg --print-architecture 2>/dev/null || echo unknown)"
    checked="linux-headers-rpi-v8 linux-headers-$release"

    if kernel_headers_available; then
        log "[+] Kernel headers are available at /lib/modules/$release/build."
        return 0
    fi

    log "[+] Kernel headers are missing for $release; checking available packages..."
    for package in linux-headers-rpi-v8 "linux-headers-$release"; do
        if apt_package_available "$package"; then
            log "[+] Installing kernel headers package: $package"
            run_logged apt-get install -y "$package" || {
                log "[-] Failed to install kernel headers package: $package"
                return 1
            }
            if kernel_headers_available; then
                log "[+] Kernel headers are now available at /lib/modules/$release/build."
                return 0
            fi
            log "[!] Package $package installed, but /lib/modules/$release/build is still missing."
        else
            log "[!] Kernel header package is not available from apt: $package"
        fi
    done

    log "[-] Kernel headers are missing; required driver builds cannot continue."
    log "[-] Current kernel: $release"
    log "[-] Architecture: $arch"
    log "[-] Checked packages: $checked"
    log "[-] Log path: $SETUP_LOG"
    return 1
}

install_rtw88_driver() {
    local dir_name="rtw88"
    local repo_url="https://github.com/lwfinger/rtw88.git"
    local release dkms_name dkms_version
    release="$(uname -r)"

    if modinfo rtw_8812au >/dev/null 2>&1 && modinfo rtw_8822bu >/dev/null 2>&1; then
        log "[+] Driver rtw88 already provides RTL8812AU (rtw_8812au) and RTL88x2BU (rtw_8822bu)."
        return
    fi

    if ! kernel_headers_available; then
        log "[-] Kernel headers for $release are missing; cannot build required rtw88 driver."
        return 1
    fi

    log "[+] Installing RTL8812AU/RTL88x2BU via lwfinger/rtw88..."
    mkdir -p /usr/src

    if [ -d "/usr/src/$dir_name/.git" ]; then
        run_logged git -C "/usr/src/$dir_name" pull --ff-only || return 1
    elif [ -e "/usr/src/$dir_name" ]; then
        log "[-] /usr/src/$dir_name exists but is not a git checkout. Move it aside and rerun setup."
        return 1
    else
        run_logged git clone "$repo_url" "/usr/src/$dir_name" || return 1
    fi

    dkms_name="$(awk -F= '/^PACKAGE_NAME=/ {gsub(/"/, "", $2); print $2; exit}' "/usr/src/$dir_name/dkms.conf")"
    dkms_version="$(awk -F= '/^PACKAGE_VERSION=/ {gsub(/"/, "", $2); print $2; exit}' "/usr/src/$dir_name/dkms.conf")"
    dkms_name="${dkms_name:-rtw88}"
    dkms_version="${dkms_version:-0.6}"

    if dkms status "$dkms_name/$dkms_version" -k "$release" 2>/dev/null | grep -q "installed"; then
        log "[+] DKMS module $dkms_name/$dkms_version is already installed for $release."
    else
        (cd "/usr/src/$dir_name" && dkms install "$PWD") >>"$SETUP_LOG" 2>&1 || return 1
    fi

    (cd "/usr/src/$dir_name" && make install_fw) >>"$SETUP_LOG" 2>&1 || return 1
    install -m 0644 "/usr/src/$dir_name/rtw88.conf" /etc/modprobe.d/rtw88.conf || return 1

    modinfo rtw_8812au >/dev/null 2>&1 || {
        log "[-] rtw88 install completed, but module rtw_8812au is not available."
        return 1
    }
    modinfo rtw_8822bu >/dev/null 2>&1 || {
        log "[-] rtw88 install completed, but module rtw_8822bu is not available."
        return 1
    }
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
set_runtime_permissions

sync_project
install_launcher

log "[+] Updating apt repositories..."
run_logged apt-get update -y || { log "[-] Failed to update apt"; exit 1; }

log "[+] Installing system dependencies..."
DEPENDENCIES="git rsync dkms build-essential bc libelf-dev aircrack-ng hostapd dnsmasq iw rfkill iproute2 iptables wireless-tools python3 python3-pip wifite network-manager"
run_logged apt-get install -y $DEPENDENCIES || { log "[-] Failed to install dependencies. See $SETUP_LOG"; exit 1; }

PYTHONDONTWRITEBYTECODE=1 python3 "$INSTALL_DIR/$SRC_ENTRY" -db >>"$SETUP_LOG" 2>&1 || log "[!] Database initialization/status check reported a warning. Run ghostlink -db for details."
set_runtime_permissions

echo ""
log "--- Kernel Headers ---"
install_kernel_headers || exit 1

install_airgeddon || { log "[-] Failed to install Airgeddon. See $SETUP_LOG"; exit 1; }

configure_management_wifi || log "[!] Management Wi-Fi configuration was skipped or failed; existing network state was left alone."

echo ""
log "--- Driver Installation ---"
log "Build/install output is logged to $SETUP_LOG"
install_rtw88_driver || { log "[-] Required rtw88 driver install failed. See $SETUP_LOG"; exit 1; }
install_rtl8188eus || log "[!] Optional backup driver RTL8188EUS failed. Continuing; see $SETUP_LOG"

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

#!/bin/bash

# Ghostlink-Mini Setup Script

set -o pipefail

INSTALL_DIR="/opt/ghostlink-mini"
SRC_ENTRY="src/ghostlink.py"
LAUNCHER="/usr/local/bin/ghostlink"
SETUP_LOG="/var/log/ghostlink/setup.log"
DRIVER_TIMEOUT_SECONDS="${GHOSTLINK_DRIVER_TIMEOUT_SECONDS:-1800}"
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

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

run_logged_timeout() {
    local seconds="$1"
    shift
    log "[cmd timeout ${seconds}s] $*"
    timeout "$seconds" "$@" >>"$SETUP_LOG" 2>&1
    local code=$?
    if [ "$code" -eq 124 ]; then
        log "[-] Command timed out after ${seconds}s: $*"
    fi
    return "$code"
}

run_shell_logged_timeout() {
    local seconds="$1"
    local script="$2"
    log "[cmd timeout ${seconds}s] $script"
    timeout "$seconds" bash -lc "$script" >>"$SETUP_LOG" 2>&1
    local code=$?
    if [ "$code" -eq 124 ]; then
        log "[-] Command timed out after ${seconds}s: $script"
    fi
    return "$code"
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
        type="$(awk -F= '/DEVTYPE/ {print $2}' "/sys/class/net/$iface/uevent" 2>/dev/null)"
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

install_wifite2() {
    log "[+] Installing latest Wifite2 from source (kimocoder/wifite2)..."
    if command -v wifite >/dev/null 2>&1; then
        run_logged apt-get remove -y wifite || true
    fi
    if [ -d /opt/wifite2/.git ]; then
        run_logged git -C /opt/wifite2 pull --ff-only || return 1
    elif [ -e /opt/wifite2 ]; then
        log "[-] /opt/wifite2 exists but is not a git checkout. Move it aside and rerun setup."
        return 1
    else
        run_logged git clone https://github.com/kimocoder/wifite2.git /opt/wifite2 || return 1
    fi
    ln -sf /opt/wifite2/Wifite.py /usr/local/bin/wifite
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

module_available() {
    local module
    for module in "$@"; do
        modinfo "$module" >/dev/null 2>&1 && return 0
    done
    return 1
}

remove_dkms_module_versions() {
    local module="$1"
    local line version

    while IFS= read -r line; do
        version="${line#"$module/"}"
        version="${version%%:*}"
        version="${version%%,*}"
        if [ -n "$version" ] && [ "$version" != "$line" ]; then
            log "[+] Removing stale DKMS module $module/$version..."
            dkms remove -m "$module" -v "$version" --all >>"$SETUP_LOG" 2>&1 || true
        fi
    done < <(dkms status "$module" 2>/dev/null || true)
}

rtl8812au_ready() {
    module_available 8812au 88XXau rtw_8812au rtw88_8812au
}

rtl88x2bu_ready() {
    module_available rtw_8822bu rtw88_8822bu
}

install_rtl8812au_pentest_driver() {
    local arch
    arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"

    if module_available 88XXau; then
        log "[+] Driver RTL8812AU pentest module (88XXau) already installed."
        return 0
    elif module_available 8812au; then
        log "[+] Driver RTL8812AU fallback module (8812au) already installed."
        return 0
    fi

    if ! kernel_headers_available; then
        log "[-] Kernel headers for $(uname -r) are missing; cannot build RTL8812AU pentest driver."
        return 1
    fi

    local matrix_log="/var/log/ghostlink/rtl8812au-driver-matrix.log"
    echo "--- Driver Matrix State before rotation ---" >> "$matrix_log"
    date >> "$matrix_log"
    dkms status >> "$matrix_log" 2>&1 || true
    lsmod >> "$matrix_log" 2>&1 || true
    lsusb -t >> "$matrix_log" 2>&1 || true
    dmesg | tail -n 100 >> "$matrix_log" 2>&1 || true

    log "[+] Stopping any conflicting modules..."
    for mod in rtw_8812au rtw88_8812au rtl8xxxu 88XXau 8812au; do
        if lsmod | grep -q "^$mod"; then
            run_logged modprobe -r "$mod" || true
        fi
    done

    # 1. Try aircrack-ng first
    log "[+] Attempting to install aircrack-ng/rtl8812au (Primary pentest driver)..."
    local dir_name="rtl8812au"
    local repo_url="https://github.com/aircrack-ng/rtl8812au.git"
    local branch="v5.6.4.2"
    
    mkdir -p /usr/src
    if [ -d "/usr/src/$dir_name/.git" ]; then
        run_logged_timeout 300 git -C "/usr/src/$dir_name" fetch --tags origin || true
        run_logged git -C "/usr/src/$dir_name" checkout "$branch" || true
        run_logged git -C "/usr/src/$dir_name" reset --hard "$branch" || true
        run_logged_timeout 300 git -C "/usr/src/$dir_name" pull --ff-only || true
    elif [ -e "/usr/src/$dir_name" ]; then
        log "[-] /usr/src/$dir_name exists but is not a git checkout."
    else
        run_logged_timeout 600 git clone -b "$branch" --single-branch "$repo_url" "/usr/src/$dir_name" || true
    fi

    if [ -d "/usr/src/$dir_name" ]; then
        case "$arch" in
            arm64|aarch64)
                run_logged sed -i 's/CONFIG_PLATFORM_I386_PC = y/CONFIG_PLATFORM_I386_PC = n/g' "/usr/src/$dir_name/Makefile"
                run_logged sed -i 's/CONFIG_PLATFORM_ARM64_RPI = n/CONFIG_PLATFORM_ARM64_RPI = y/g' "/usr/src/$dir_name/Makefile"
                run_logged sed -i 's/^MAKE="\(ARCH=[^ ]* \)*/MAKE="ARCH=arm64 /' "/usr/src/$dir_name/dkms.conf"
                ;;
            armhf|armel|armv7l)
                run_logged sed -i 's/CONFIG_PLATFORM_I386_PC = y/CONFIG_PLATFORM_I386_PC = n/g' "/usr/src/$dir_name/Makefile"
                run_logged sed -i 's/CONFIG_PLATFORM_ARM_RPI = n/CONFIG_PLATFORM_ARM_RPI = y/g' "/usr/src/$dir_name/Makefile"
                run_logged sed -i 's/^MAKE="\(ARCH=[^ ]* \)*/MAKE="ARCH=arm /' "/usr/src/$dir_name/dkms.conf"
                ;;
        esac

        remove_dkms_module_versions 8812au
        if run_shell_logged_timeout "$DRIVER_TIMEOUT_SECONDS" "cd /usr/src/$dir_name && make dkms_install"; then
            cat >/etc/modprobe.d/ghostlink-rtl8812au.conf <<'CONF'
# Prefer aircrack-ng 88XXau for RTL8812AU monitor mode/frame injection.
blacklist rtw_8812au
blacklist rtw88_8812au
blacklist rtl8xxxu
options 88XXau rtw_led_ctrl=0
CONF
            run_logged modprobe 88XXau || true
            if module_available 88XXau; then
                log "[+] RTL8812AU pentest driver installed successfully as module 88XXau."
                log "[+] RTL8812AU driver path prepared. Plug in RTL8812AU adapter to activate."
                return 0
            fi
        fi
    fi

    log "[!] aircrack-ng build failed. Falling back to morrownr/8812au-20210820..."
    # 2. Try morrownr
    dir_name="8812au-20210820"
    repo_url="https://github.com/morrownr/8812au-20210820.git"
    
    if [ -d "/usr/src/$dir_name/.git" ]; then
        run_logged_timeout 300 git -C "/usr/src/$dir_name" pull --ff-only || true
    elif [ -e "/usr/src/$dir_name" ]; then
        log "[-] /usr/src/$dir_name exists but is not a git checkout."
    else
        run_logged_timeout 600 git clone "$repo_url" "/usr/src/$dir_name" || true
    fi

    if [ -d "/usr/src/$dir_name" ]; then
        remove_dkms_module_versions 8812au
        if run_shell_logged_timeout "$DRIVER_TIMEOUT_SECONDS" "cd /usr/src/$dir_name && ./install-driver.sh NoPrompt"; then
            cat >/etc/modprobe.d/ghostlink-rtl8812au.conf <<'CONF'
# Prefer morrownr 8812au for RTL8812AU uplink (monitor mode may not be fully supported)
blacklist rtw_8812au
blacklist rtw88_8812au
blacklist rtl8xxxu
options 8812au rtw_led_ctrl=0
CONF
            run_logged modprobe 8812au || true
            if module_available 8812au; then
                log "[+] RTL8812AU fallback driver installed successfully (morrownr/8812au)."
                log "[+] RTL8812AU driver path prepared. Plug in RTL8812AU adapter to activate."
                return 0
            fi
        fi
    fi

    log "[!] Both pentest/fallback drivers failed. Falling back to rtw88/rtl8xxxu kernel modules."
    log "[!] RTL8812AU driver path could not be fully prepared. Run 'sudo ./setup.sh --update' after resolving kernel headers."
    return 1
}

install_rtw88_driver() {
    local dir_name="rtw88"
    local repo_url="https://github.com/lwfinger/rtw88.git"
    local release dkms_name dkms_version
    release="$(uname -r)"

    if rtl88x2bu_ready; then
        log "[+] RTL88x2BU driver module is already available. Skipping rtw88 install."
        return
    fi

    if ! kernel_headers_available; then
        log "[-] Kernel headers for $release are missing; cannot build required RTL88x2BU rtw88 driver."
        return 1
    fi

    log "[+] Installing RTL88x2BU via lwfinger/rtw88..."
    mkdir -p /usr/src

    if [ -d "/usr/src/$dir_name/.git" ]; then
        run_logged_timeout 300 git -C "/usr/src/$dir_name" pull --ff-only || return 1
    elif [ -e "/usr/src/$dir_name" ]; then
        log "[-] /usr/src/$dir_name exists but is not a git checkout. Move it aside and rerun setup."
        return 1
    else
        run_logged_timeout 600 git clone "$repo_url" "/usr/src/$dir_name" || return 1
    fi

    dkms_name="$(awk -F= '/^PACKAGE_NAME=/ {gsub(/"/, "", $2); print $2; exit}' "/usr/src/$dir_name/dkms.conf")"
    dkms_version="$(awk -F= '/^PACKAGE_VERSION=/ {gsub(/"/, "", $2); print $2; exit}' "/usr/src/$dir_name/dkms.conf")"
    dkms_name="${dkms_name:-rtw88}"
    dkms_version="${dkms_version:-0.6}"

    if dkms status "$dkms_name/$dkms_version" -k "$release" 2>/dev/null | grep -q "installed"; then
        log "[+] DKMS module $dkms_name/$dkms_version is already installed for $release."
    else
        run_shell_logged_timeout "$DRIVER_TIMEOUT_SECONDS" "cd /usr/src/$dir_name && dkms install \"\$PWD\"" || return 1
    fi

    run_shell_logged_timeout 300 "cd /usr/src/$dir_name && make install_fw" || return 1
    install -m 0644 "/usr/src/$dir_name/rtw88.conf" /etc/modprobe.d/rtw88.conf || return 1

    rtl88x2bu_ready || {
        log "[-] rtw88 install completed, but RTL88x2BU module is not available."
        return 1
    }
    if ! rtl8812au_ready; then
        log "[!] Note: no RTL8812AU module visible via rtw88 fallback. This is expected when 88XXau is the primary driver."
    fi
    log "[+] RTL88x2BU driver path prepared. Plug in RTL88x2BU adapter to activate."
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
    (cd /usr/src/rtl8188eus && make && make install) >>"$SETUP_LOG" 2>&1 || return 1
    run_logged modprobe 8188eu || log "[!] modprobe 8188eu returned non-zero (normal if RTL8188EUS adapter is not plugged in yet)."
    log "[+] RTL8188EUS driver path prepared. Plug in RTL8188EUS adapter to activate."
}

setup_mt7612u() {
    log "[+] Checking MT7612U (MediaTek mt76 in-kernel stack) support..."

    if modinfo mt76x2u >/dev/null 2>&1; then
        log "[+] mt76x2u module is available in this kernel."
        log "[+] Loading mt76x2u..."
        run_logged modprobe mt76x2u || log "[!] modprobe mt76x2u returned non-zero (normal if no MT7612U device is plugged in yet)."
    else
        log "[!] mt76x2u is not available in this kernel build. MT7612U will not get a wireless interface."
    fi

    if apt_package_available firmware-misc-nonfree; then
        if dpkg -l firmware-misc-nonfree 2>/dev/null | grep -q "^ii"; then
            log "[+] firmware-misc-nonfree is already installed (MT7612U firmware covered)."
        else
            log "[+] Installing firmware-misc-nonfree for MT7612U firmware support..."
            run_logged apt-get install -y firmware-misc-nonfree || log "[!] Could not install firmware-misc-nonfree. MT7612U firmware may be missing."
        fi
    else
        log "[!] firmware-misc-nonfree is not available from apt on this system."
        log "[!] If MT7612U shows no interface after plug-in, check: dmesg | grep mt76 and lsmod | grep mt76"
    fi

    log "[+] MT7612U check complete. Plug in MT7612U adapter if not already connected, then run 'ghostlink -diag'."
    return 0
}

configure_zram() {
    log "[+] Configuring 2GB ZRAM..."
    cat >/etc/default/zramswap <<'EOF'
ALGO=lz4
PERCENT=50
SIZE=2048
EOF
    run_logged systemctl restart zramswap || true
}

configure_rpi5_fan() {
    if [ -f /boot/firmware/config.txt ]; then
        if ! grep -q "fan_temp0=" /boot/firmware/config.txt; then
            log "[+] Configuring Raspberry Pi 5 Active Cooler thresholds..."
            cat >>/boot/firmware/config.txt <<'EOF'

# Ghostlink-Mini: RPi 5 Active Cooler medium-high profile
dtparam=fan_temp0=45000
dtparam=fan_temp0_speed=150
dtparam=fan_temp1=55000
dtparam=fan_temp1_speed=200
dtparam=fan_temp2=65000
dtparam=fan_temp2_speed=255
EOF
        fi
    fi
}

configure_rpi5_pcie() {
    if [ -f /boot/firmware/config.txt ]; then
        if ! grep -q "pciex1_gen=3" /boot/firmware/config.txt; then
            log "[+] Enabling PCIe Gen 3 for M.2 SSD..."
            cat >>/boot/firmware/config.txt <<'EOF'

# Ghostlink-Mini: Enable PCIe Gen 3 for M.2 SSD speed boost
dtparam=pciex1_gen=3
EOF
        fi
    fi
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
DEPENDENCIES=(git rsync dkms build-essential bc libelf-dev aircrack-ng hostapd dnsmasq iw rfkill iproute2 iptables wireless-tools python3 python3-pip network-manager nmap zram-tools)
run_logged apt-get install -y "${DEPENDENCIES[@]}" || { log "[-] Failed to install dependencies. See $SETUP_LOG"; exit 1; }

PYTHONDONTWRITEBYTECODE=1 python3 "$INSTALL_DIR/$SRC_ENTRY" -db >>"$SETUP_LOG" 2>&1 || log "[!] Database initialization/status check reported a warning. Run ghostlink -db for details."
set_runtime_permissions

echo ""
log "--- Kernel Headers ---"
install_kernel_headers || exit 1

install_airgeddon || { log "[-] Failed to install Airgeddon. See $SETUP_LOG"; exit 1; }
install_wifite2 || { log "[-] Failed to install Wifite2. See $SETUP_LOG"; exit 1; }

configure_management_wifi || log "[!] Management Wi-Fi configuration was skipped or failed; existing network state was left alone."

echo ""
log "--- Driver Installation ---"
log "Build/install output is logged to $SETUP_LOG"
remove_dkms_module_versions rtl88x2bu
install_rtl8812au_pentest_driver || log "[!] RTL8812AU pentest driver failed; rtw88 fallback will be used if available."
install_rtw88_driver || { log "[-] Required RTL88x2BU rtw88 driver install failed. See $SETUP_LOG"; exit 1; }
install_rtl8188eus || log "[!] Optional backup driver RTL8188EUS failed. Continuing; see $SETUP_LOG"
setup_mt7612u || log "[!] MT7612U setup had warnings. MT7612U may not function until firmware/modules are resolved. See $SETUP_LOG"

echo ""
log "--- System Optimizations ---"
configure_zram
configure_rpi5_fan
configure_rpi5_pcie

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

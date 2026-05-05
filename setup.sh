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
DRY_RUN=0
PLATFORM_MODEL="Generic Debian-based SBC"
PLATFORM_PROFILE="debian_sbc"
PLATFORM_LABEL="Generic Debian-based SBC"
PLATFORM_SUPPORT="best-effort"
PLATFORM_OS_PRETTY="unknown"
PLATFORM_OS_CODENAME="unknown"
PLATFORM_ARCH="unknown"
PLATFORM_KERNEL="unknown"
PLATFORM_ZRAM_MB=1024
PLATFORM_GPU_MEM_MB=""
PLATFORM_OC_SUMMARY="not applicable"
PLATFORM_NOTES="Pi-specific boot, fan, PCIe, and raspi-config steps are skipped."

usage() {
    cat <<USAGE
Usage: sudo ./setup.sh [--update] [--dry-run] [--help]

Options:
  --update        Reinstall/update files without prompting for management Wi-Fi
  --dry-run       Detect platform and print install plan; make no changes
  -h, --help      Show this help
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --update)
            UPDATE_MODE=1
            ;;
        --dry-run)
            DRY_RUN=1
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

if [ "$DRY_RUN" -eq 0 ] && [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup.sh). Use ./setup.sh --help for options."
    echo "Tip: --dry-run does not require root."
    exit 1
fi

if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p /var/log/ghostlink
    touch "$SETUP_LOG" || {
        echo "[-] Cannot write setup log at $SETUP_LOG"
        exit 1
    }
fi

log() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "$@"
    else
        echo "$@" | tee -a "$SETUP_LOG"
    fi
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

read_first_line() {
    local path="$1"
    if [ -r "$path" ]; then
        tr -d '\000' <"$path" 2>/dev/null | head -n 1
    fi
}

set_platform_profile_defaults() {
    case "$PLATFORM_PROFILE" in
        rpi_zero_w)
            PLATFORM_LABEL="Raspberry Pi Zero W"
            PLATFORM_SUPPORT="tested/owned"
            PLATFORM_ZRAM_MB=512
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="stock-safe baseline; no automatic CPU overclock"
            PLATFORM_NOTES="armv6/low-memory profile; USB/power headroom is limited."
            ;;
        rpi_zero_2_w)
            PLATFORM_LABEL="Raspberry Pi Zero 2 W"
            PLATFORM_SUPPORT="tested/owned"
            PLATFORM_ZRAM_MB=1024
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="safe mild profile: arm_freq=1100"
            PLATFORM_NOTES="low-memory quad-core profile; keep adapter power modest."
            ;;
        rpi_1)
            PLATFORM_LABEL="Raspberry Pi 1"
            PLATFORM_SUPPORT="supported/untested"
            PLATFORM_ZRAM_MB=512
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="not applied by default"
            PLATFORM_NOTES="best with lightweight workflows; external powered USB is recommended."
            ;;
        rpi_2)
            PLATFORM_LABEL="Raspberry Pi 2"
            PLATFORM_SUPPORT="supported/untested"
            PLATFORM_ZRAM_MB=1024
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="not applied by default"
            PLATFORM_NOTES="supported but not owned/tested for Chapter 1."
            ;;
        rpi_3b)
            PLATFORM_LABEL="Raspberry Pi 3B"
            PLATFORM_SUPPORT="tested/owned"
            PLATFORM_ZRAM_MB=1024
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="safe mild profile: arm_freq=1300, core_freq=500, over_voltage=2"
            PLATFORM_NOTES="USB 2.0 and shared bus constraints apply."
            ;;
        rpi_3b_plus)
            PLATFORM_LABEL="Raspberry Pi 3 Model B+"
            PLATFORM_SUPPORT="supported/untested"
            PLATFORM_ZRAM_MB=1024
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="not applied by default (3B+ detected; set manually if desired)"
            PLATFORM_NOTES="Pi 3B+ similar to 3B; auto-OC not applied to avoid 3B+ stability regression."
            ;;
        rpi_4)
            PLATFORM_LABEL="Raspberry Pi 4"
            PLATFORM_SUPPORT="supported/untested"
            PLATFORM_ZRAM_MB=2048
            PLATFORM_GPU_MEM_MB=16
            PLATFORM_OC_SUMMARY="not applied by default"
            PLATFORM_NOTES="supported but not owned/tested for Chapter 1."
            ;;
        rpi_5)
            PLATFORM_LABEL="Raspberry Pi 5"
            PLATFORM_SUPPORT="tested/owned"
            PLATFORM_ZRAM_MB=2048
            PLATFORM_GPU_MEM_MB=""
            PLATFORM_OC_SUMMARY="safe mild profile: arm_freq=2600"
            PLATFORM_NOTES="Pi 5-only fan and PCIe tuning may be applied by setup; gpu_mem is firmware-managed."
            ;;
        unknown_rpi)
            PLATFORM_LABEL="Unknown Raspberry Pi"
            PLATFORM_SUPPORT="supported/untested"
            PLATFORM_ZRAM_MB=1024
            PLATFORM_GPU_MEM_MB=""
            PLATFORM_OC_SUMMARY="not applied by default"
            PLATFORM_NOTES="Raspberry Pi detected, but model did not match a named profile."
            ;;
        *)
            PLATFORM_PROFILE="debian_sbc"
            PLATFORM_LABEL="Generic Debian-based SBC"
            PLATFORM_SUPPORT="best-effort"
            PLATFORM_ZRAM_MB=1024
            PLATFORM_GPU_MEM_MB=""
            PLATFORM_OC_SUMMARY="not applicable"
            PLATFORM_NOTES="Pi-specific boot, fan, PCIe, and raspi-config steps are skipped."
            ;;
    esac
}

detect_platform() {
    local model cpu_model hardware lower_model
    local version_codename ubuntu_codename debian_codename

    model="$(read_first_line /proc/device-tree/model)"
    if [ -z "$model" ] && [ -r /proc/cpuinfo ]; then
        cpu_model="$(awk -F: '/^Model/ {sub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo 2>/dev/null)"
        hardware="$(awk -F: '/^Hardware/ {sub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo 2>/dev/null)"
        if [ -n "$cpu_model" ]; then
            model="$cpu_model"
        elif printf '%s' "$hardware" | grep -qi '^bcm'; then
            model="Raspberry Pi (model unknown)"
        fi
    fi
    PLATFORM_MODEL="${model:-Generic Debian-based SBC}"

    PLATFORM_ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m 2>/dev/null || echo unknown)"
    PLATFORM_KERNEL="$(uname -r 2>/dev/null || echo unknown)"

    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        version_codename="${VERSION_CODENAME:-}"
        ubuntu_codename="${UBUNTU_CODENAME:-}"
        debian_codename="${DEBIAN_CODENAME:-}"
        PLATFORM_OS_PRETTY="${PRETTY_NAME:-unknown}"
        PLATFORM_OS_CODENAME="${version_codename:-${ubuntu_codename:-${debian_codename:-unknown}}}"
    fi

    lower_model="$(printf '%s' "$PLATFORM_MODEL" | tr '[:upper:]' '[:lower:]')"
    case "$lower_model" in
        *"raspberry pi zero 2"*)
            PLATFORM_PROFILE="rpi_zero_2_w"
            ;;
        *"raspberry pi zero"*)
            PLATFORM_PROFILE="rpi_zero_w"
            ;;
        *"raspberry pi 5"*)
            PLATFORM_PROFILE="rpi_5"
            ;;
        *"raspberry pi 4"*)
            PLATFORM_PROFILE="rpi_4"
            ;;
        *"raspberry pi 3 model b plus"*|*"raspberry pi 3b+"*)
            PLATFORM_PROFILE="rpi_3b_plus"
            ;;
        *"raspberry pi 3 model b"*)
            PLATFORM_PROFILE="rpi_3b"
            ;;
        *"raspberry pi 3"*)
            PLATFORM_PROFILE="unknown_rpi"
            ;;
        *"raspberry pi 2"*)
            PLATFORM_PROFILE="rpi_2"
            ;;
        *"raspberry pi model"*|*"raspberry pi 1"*)
            PLATFORM_PROFILE="rpi_1"
            ;;
        *"raspberry pi"*)
            PLATFORM_PROFILE="unknown_rpi"
            ;;
        *)
            PLATFORM_PROFILE="debian_sbc"
            ;;
    esac

    set_platform_profile_defaults
}

is_raspberry_pi() {
    [ "$PLATFORM_PROFILE" != "debian_sbc" ]
}

log_platform_summary() {
    log "--- Platform Detection ---"
    log "[+] Model: $PLATFORM_MODEL"
    log "[+] Profile: $PLATFORM_PROFILE ($PLATFORM_SUPPORT)"
    log "[+] OS: $PLATFORM_OS_PRETTY"
    log "[+] Codename: $PLATFORM_OS_CODENAME"
    log "[+] Architecture: $PLATFORM_ARCH"
    log "[+] Kernel: $PLATFORM_KERNEL"
    log "[+] ZRAM target: ${PLATFORM_ZRAM_MB}MB"
    if [ "$PLATFORM_PROFILE" = "rpi_5" ]; then
        log "[+] GPU memory floor: skipped on Pi 5, firmware-managed"
    elif [ -n "$PLATFORM_GPU_MEM_MB" ]; then
        log "[+] GPU memory floor: ${PLATFORM_GPU_MEM_MB}MB"
    else
        log "[+] GPU memory floor: skipped"
    fi
    log "[+] Overclock policy: $PLATFORM_OC_SUMMARY"
    log "[+] Notes: $PLATFORM_NOTES"
}

log_compatibility_matrix() {
    log "--- Chapter 1 Compatibility Matrix ---"
    log "[+] rpi_zero_w: tested/owned | ZRAM 512MB | GPU 16MB | OC stock-safe | fan/storage N/A | drivers: all prepared"
    log "[+] rpi_zero_2_w: tested/owned | ZRAM 1024MB | GPU 16MB | OC arm_freq=1100 | fan/storage N/A | drivers: all prepared"
    log "[+] rpi_3b: tested/owned | ZRAM 1024MB | GPU 16MB | OC arm_freq=1300/core_freq=500 | fan/storage N/A | drivers: all prepared"
    log "[+] rpi_5: tested/owned | ZRAM 2048MB | GPU skipped/firmware-managed | OC arm_freq=2600 | fan/PCIe gated to Pi 5 | drivers: all prepared"
    log "[+] rpi_1: supported/untested | ZRAM 512MB | GPU 16MB | OC skipped | fan/storage N/A | drivers: best effort"
    log "[+] rpi_2: supported/untested | ZRAM 1024MB | GPU 16MB | OC skipped | fan/storage N/A | drivers: best effort"
    log "[+] rpi_3b_plus: supported/untested | ZRAM 1024MB | GPU 16MB | OC skipped | fan/storage N/A | drivers: best effort"
    log "[+] rpi_4: supported/untested | ZRAM 2048MB | GPU 16MB | OC skipped | fan/storage N/A | drivers: best effort"
    log "[+] debian_sbc: best-effort | ZRAM 1024MB | Pi boot/GPU/OC/fan/PCIe skipped | drivers: all prepared when headers are available"
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

header_package_candidates() {
    local release="$1"
    local arch="$2"

    printf '%s\n' "linux-headers-$release"

    if is_raspberry_pi; then
        printf '%s\n' "raspberrypi-kernel-headers"
        case "$arch" in
            arm64|aarch64)
                printf '%s\n' "linux-headers-rpi-v8"
                ;;
            armhf|armv7l)
                printf '%s\n' "linux-headers-rpi-v7"
                printf '%s\n' "linux-headers-rpi-v6"
                ;;
            armel|armv6l)
                printf '%s\n' "linux-headers-rpi-v6"
                printf '%s\n' "linux-headers-rpi-v7"
                ;;
        esac
    fi
}

install_kernel_headers() {
    local release arch checked package seen candidate
    local candidates=()
    release="$(uname -r)"
    arch="$(dpkg --print-architecture 2>/dev/null || echo unknown)"

    if kernel_headers_available; then
        log "[+] Kernel headers are available at /lib/modules/$release/build."
        return 0
    fi

    seen=""
    while IFS= read -r candidate; do
        [ -z "$candidate" ] && continue
        case " $seen " in
            *" $candidate "*)
                continue
                ;;
        esac
        candidates+=("$candidate")
        seen="$seen $candidate"
    done < <(header_package_candidates "$release" "$arch")
    checked="${candidates[*]}"

    log "[+] Kernel headers are missing for $release; checking available packages..."
    for package in "${candidates[@]}"; do
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

log_driver_compatibility_state() {
    local release arch candidate candidates module
    release="$(uname -r)"
    arch="$(dpkg --print-architecture 2>/dev/null || uname -m 2>/dev/null || echo unknown)"
    candidates=""
    while IFS= read -r candidate; do
        [ -z "$candidate" ] && continue
        case " $candidates " in
            *" $candidate "*)
                continue
                ;;
        esac
        candidates="$candidates $candidate"
    done < <(header_package_candidates "$release" "$arch")

    log "--- Driver Compatibility State ---"
    log "[+] Platform profile: $PLATFORM_PROFILE ($PLATFORM_SUPPORT)"
    log "[+] OS/codename: $PLATFORM_OS_PRETTY / $PLATFORM_OS_CODENAME"
    log "[+] Architecture: $arch"
    log "[+] Kernel: $release"
    log "[+] Header package candidates:${candidates:- none}"

    if kernel_headers_available; then
        log "[+] Kernel headers: present at /lib/modules/$release/build"
    else
        log "[!] Kernel headers: missing at /lib/modules/$release/build"
    fi

    if command -v dkms >/dev/null 2>&1; then
        log "[+] DKMS: installed"
        dkms status >>"$SETUP_LOG" 2>&1 || log "[!] DKMS status returned non-zero."
    else
        log "[!] DKMS: missing"
    fi

    for module in 88XXau 8812au rtw_8812au rtw88_8812au rtl8xxxu mt76x2u mt76_usb mt76 rtw_8822bu rtw88_8822bu 8188eu r8188eu brcmfmac; do
        if modinfo "$module" >/dev/null 2>&1; then
            log "[+] Module $module: available"
        else
            log "[!] Module $module: missing"
        fi
    done
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
    log "[+] Configuring ${PLATFORM_ZRAM_MB}MB ZRAM for $PLATFORM_PROFILE..."
    cat >/etc/default/zramswap <<EOF
ALGO=lz4
SIZE=$PLATFORM_ZRAM_MB
EOF
    run_logged systemctl restart zramswap || true
}

boot_config_path() {
    if [ -f /boot/firmware/config.txt ]; then
        echo "/boot/firmware/config.txt"
    elif [ -f /boot/config.txt ]; then
        echo "/boot/config.txt"
    else
        echo ""
    fi
}

boot_config_has_key() {
    local path="$1"
    local key="$2"
    grep -Eq "^[[:space:]]*${key}[[:space:]]*=" "$path" 2>/dev/null
}

boot_config_has_user_gpu_mem() {
    local path="$1"
    awk '
        /^[[:space:]]*# Ghostlink-Mini: GPU memory floor/ {
            ghostlink_gpu = 1
            next
        }
        /^[[:space:]]*gpu_mem[[:space:]]*=/ {
            if (ghostlink_gpu) {
                ghostlink_gpu = 0
                next
            }
            found = 1
        }
        END { exit found ? 0 : 1 }
    ' "$path" 2>/dev/null
}

expand_rpi_filesystem() {
    if ! is_raspberry_pi; then
        log "[+] Skipping Raspberry Pi filesystem expansion on generic Debian SBC."
        return
    fi
    if ! command -v raspi-config >/dev/null 2>&1; then
        log "[!] raspi-config is not available; skipping filesystem expansion."
        return
    fi

    if [ "$PLATFORM_PROFILE" = "rpi_5" ]; then
        local _root_dev _root_real _is_nvme
        _root_dev="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
        _root_real=""
        if [ -n "$_root_dev" ]; then
            _root_real="$(readlink -f "$_root_dev" 2>/dev/null || echo "$_root_dev")"
        fi
        _is_nvme=0
        if printf '%s %s' "$_root_dev" "$_root_real" | grep -qE "(nvme|nvm)"; then
            _is_nvme=1
        elif [ -n "$_root_real" ] && command -v lsblk >/dev/null 2>&1; then
            if lsblk -no TRAN "$_root_real" 2>/dev/null | head -1 | grep -q "nvme"; then
                _is_nvme=1
            fi
        fi
        if [ "$_is_nvme" -eq 1 ]; then
            log "[+] Root is on NVMe ($PLATFORM_PROFILE); skipping raspi-config expansion."
            return
        fi
        if [ -z "$_root_dev" ]; then
            log "[!] Pi 5: cannot determine root device reliably; skipping raspi-config expansion to avoid risk."
            return
        fi
    fi

    log "[+] Requesting Raspberry Pi root filesystem expansion via raspi-config..."
    run_logged raspi-config nonint do_expand_rootfs || log "[!] raspi-config do_expand_rootfs returned non-zero; continuing."
}

configure_rpi_gpu_memory() {
    local config_path
    if ! is_raspberry_pi; then
        log "[+] Skipping Raspberry Pi GPU memory tuning on generic Debian SBC."
        return
    fi
    if [ "$PLATFORM_PROFILE" = "rpi_5" ]; then
        log "[+] Raspberry Pi 5 detected; skipping gpu_mem because Pi 5 GPU memory is firmware-managed."
        return
    fi
    if [ -z "$PLATFORM_GPU_MEM_MB" ]; then
        log "[+] No GPU memory floor defined for $PLATFORM_PROFILE; skipping."
        return
    fi

    config_path="$(boot_config_path)"
    if [ -z "$config_path" ]; then
        log "[!] Raspberry Pi boot config was not found; cannot set gpu_mem."
        return
    fi
    if boot_config_has_user_gpu_mem "$config_path"; then
        log "[+] Existing user gpu_mem setting found in $config_path; leaving user value unchanged."
        return
    fi
    if boot_config_has_key "$config_path" "gpu_mem"; then
        log "[+] Existing Ghostlink-managed gpu_mem setting found in $config_path; leaving value unchanged."
        return
    fi

    log "[+] Setting Raspberry Pi GPU memory floor to ${PLATFORM_GPU_MEM_MB}MB in $config_path..."
    {
        echo ""
        echo "[all]"
        echo "# Ghostlink-Mini: GPU memory floor for $PLATFORM_LABEL"
        echo "gpu_mem=$PLATFORM_GPU_MEM_MB"
    } >>"$config_path"
}

configure_rpi_overclock() {
    local config_path
    if ! is_raspberry_pi; then
        log "[+] Skipping Raspberry Pi overclock tuning on generic Debian SBC."
        return
    fi
    if [ "${GHOSTLINK_DISABLE_RPI_OC:-0}" = "1" ]; then
        log "[+] GHOSTLINK_DISABLE_RPI_OC=1; skipping Raspberry Pi overclock tuning."
        return
    fi

    config_path="$(boot_config_path)"
    if [ -z "$config_path" ]; then
        log "[!] Raspberry Pi boot config was not found; cannot apply profile overclock."
        return
    fi
    if boot_config_has_key "$config_path" "arm_freq" || boot_config_has_key "$config_path" "over_voltage" || boot_config_has_key "$config_path" "over_voltage_delta"; then
        log "[+] Existing overclock/voltage settings found in $config_path; leaving user values unchanged."
        return
    fi

    case "$PLATFORM_PROFILE" in
        rpi_zero_2_w)
            log "[+] Applying safe Raspberry Pi Zero 2 W CPU profile in $config_path..."
            cat >>"$config_path" <<'EOF'

[all]
# Ghostlink-Mini: safe CPU profile for Raspberry Pi Zero 2 W
arm_freq=1100
EOF
            ;;
        rpi_3b)
            log "[+] Applying safe Raspberry Pi 3B CPU profile in $config_path..."
            cat >>"$config_path" <<'EOF'

[all]
# Ghostlink-Mini: safe CPU profile for Raspberry Pi 3B
arm_freq=1300
core_freq=500
over_voltage=2
EOF
            ;;
        rpi_5)
            log "[+] Applying safe Raspberry Pi 5 CPU profile in $config_path..."
            cat >>"$config_path" <<'EOF'

[all]
# Ghostlink-Mini: safe CPU profile for Raspberry Pi 5
arm_freq=2600
EOF
            ;;
        *)
            log "[+] No default overclock is applied for $PLATFORM_PROFILE ($PLATFORM_SUPPORT)."
            ;;
    esac
}

configure_rpi5_fan() {
    local config_path
    if [ "$PLATFORM_PROFILE" != "rpi_5" ]; then
        log "[+] Skipping Raspberry Pi 5 fan tuning for $PLATFORM_PROFILE."
        return
    fi

    config_path="$(boot_config_path)"
    if [ -z "$config_path" ]; then
        log "[!] Raspberry Pi boot config was not found; cannot set Pi 5 fan thresholds."
        return
    fi

    if ! grep -q "fan_temp0=" "$config_path"; then
        log "[+] Configuring Raspberry Pi 5 Active Cooler thresholds..."
        cat >>"$config_path" <<'EOF'

[all]
# Ghostlink-Mini: RPi 5 Active Cooler medium-high profile
dtparam=fan_temp0=45000
dtparam=fan_temp0_speed=150
dtparam=fan_temp1=55000
dtparam=fan_temp1_speed=200
dtparam=fan_temp2=65000
dtparam=fan_temp2_speed=255
EOF
    else
        log "[+] Existing Raspberry Pi 5 fan thresholds found in $config_path; leaving user values unchanged."
    fi
}

configure_rpi5_pcie() {
    local config_path
    if [ "$PLATFORM_PROFILE" != "rpi_5" ]; then
        log "[+] Skipping Raspberry Pi 5 PCIe tuning for $PLATFORM_PROFILE."
        return
    fi

    config_path="$(boot_config_path)"
    if [ -z "$config_path" ]; then
        log "[!] Raspberry Pi boot config was not found; cannot set Pi 5 PCIe mode."
        return
    fi

    if grep -Eq "^[[:space:]]*(dtparam=)?pciex1_gen=" "$config_path"; then
        log "[+] Existing pciex1_gen setting found in $config_path; preserving user PCIe configuration."
        return
    fi
    log "[+] Enabling PCIe Gen 3 for M.2 SSD..."
    cat >>"$config_path" <<'EOF'

[all]
# Ghostlink-Mini: Enable PCIe Gen 3 for M.2 SSD speed boost
dtparam=pciex1_gen=3
EOF
}

echo "======================================"
echo "    Ghostlink-Mini Setup Script"
echo "======================================"
[ "$UPDATE_MODE" -eq 1 ] && log "Running in UPDATE mode..."
detect_platform
log_platform_summary
log_compatibility_matrix

if [ "$DRY_RUN" -eq 1 ]; then
    echo ""
    echo "======================================"
    echo "    Dry Run — Install Plan"
    echo "======================================"
    echo "  Platform : $PLATFORM_MODEL"
    echo "  Profile  : $PLATFORM_PROFILE ($PLATFORM_SUPPORT)"
    echo "  OS       : $PLATFORM_OS_PRETTY ($PLATFORM_OS_CODENAME)"
    echo "  Arch     : $PLATFORM_ARCH"
    echo "  Kernel   : $PLATFORM_KERNEL"
    echo "  ZRAM     : ${PLATFORM_ZRAM_MB}MB"
    if is_raspberry_pi; then
        _boot_cfg="$(boot_config_path)"
        echo "  Boot cfg : ${_boot_cfg:-not found}"
        if [ "$PLATFORM_PROFILE" = "rpi_5" ]; then
            echo "  GPU mem  : skipped on Pi 5, firmware-managed"
        elif [ -n "$PLATFORM_GPU_MEM_MB" ]; then
            echo "  GPU mem  : ${PLATFORM_GPU_MEM_MB}MB floor"
        else
            echo "  GPU mem  : skipped"
        fi
        if [ "${GHOSTLINK_DISABLE_RPI_OC:-0}" = "1" ]; then
            echo "  OC       : disabled (GHOSTLINK_DISABLE_RPI_OC=1)"
        else
            echo "  OC       : $PLATFORM_OC_SUMMARY"
        fi
        if [ "$PLATFORM_PROFILE" = "rpi_5" ]; then
            echo "  Pi 5 fan : Active Cooler thresholds will be applied"
            echo "  Pi 5 PCIe: Gen 3 will be enabled"
        fi
    else
        echo "  GPU mem  : skipped"
        echo "  Pi-specific boot/fan/PCIe steps: skipped (not Raspberry Pi)"
    fi
    echo ""
    echo "  Drivers to prepare: RTL8812AU, MT7612U, RTL88x2BU, RTL8188EUS"
    echo "  Tools to install  : Wifite2, Airgeddon, aircrack-ng, nmap, hostapd, dnsmasq"
    echo ""
    echo "  No changes made (--dry-run)."
    echo "======================================"
    exit 0
fi

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
log_driver_compatibility_state
HEADERS_OK=0
if install_kernel_headers; then
    HEADERS_OK=1
else
    log "[!] Kernel headers are missing or could not be installed."
    log "[!] DKMS-based drivers (RTL8812AU, RTL88x2BU, RTL8188EUS) will be skipped."
    log "[!] MT7612U (in-kernel mt76) setup will still proceed."
fi
log_driver_compatibility_state

install_airgeddon || log "[!] Failed to install Airgeddon. Run 'sudo ./setup.sh --update' to retry. See $SETUP_LOG"
install_wifite2 || log "[!] Failed to install Wifite2. Run 'sudo ./setup.sh --update' to retry. See $SETUP_LOG"

configure_management_wifi || log "[!] Management Wi-Fi configuration was skipped or failed; existing network state was left alone."

echo ""
log "--- Driver Installation ---"
log "Build/install output is logged to $SETUP_LOG"
_DRIVER_FAILURES=""

if [ "$HEADERS_OK" -eq 1 ]; then
    remove_dkms_module_versions rtl88x2bu
    install_rtl8812au_pentest_driver || { log "[!] RTL8812AU pentest driver failed; see $SETUP_LOG"; _DRIVER_FAILURES="${_DRIVER_FAILURES} RTL8812AU"; }
    install_rtw88_driver || { log "[!] RTL88x2BU rtw88 driver failed; see $SETUP_LOG"; _DRIVER_FAILURES="${_DRIVER_FAILURES} RTL88x2BU"; }
    install_rtl8188eus || { log "[!] RTL8188EUS driver failed; see $SETUP_LOG"; _DRIVER_FAILURES="${_DRIVER_FAILURES} RTL8188EUS"; }
else
    log "[!] Skipping RTL8812AU, RTL88x2BU, RTL8188EUS driver installs (kernel headers missing)."
    _DRIVER_FAILURES="${_DRIVER_FAILURES} RTL8812AU RTL88x2BU RTL8188EUS"
fi

setup_mt7612u || { log "[!] MT7612U setup had warnings; see $SETUP_LOG"; _DRIVER_FAILURES="${_DRIVER_FAILURES} MT7612U"; }

if [ -n "$_DRIVER_FAILURES" ]; then
    log "[!] Driver install summary — failures:${_DRIVER_FAILURES}"
    log "[!] Run 'sudo ./setup.sh --update' after resolving kernel headers to retry."
else
    log "[+] All driver install steps completed."
fi

echo ""
log "--- System Optimizations ---"
configure_zram
expand_rpi_filesystem
configure_rpi_gpu_memory
configure_rpi_overclock
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

#!/bin/bash

# Ghostlink-Mini Setup Script

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (sudo ./setup.sh)"
  exit 1
fi

UPDATE_MODE=0
if [ "$1" == "--update" ]; then
    UPDATE_MODE=1
    echo "Running in UPDATE mode..."
fi

echo "======================================"
echo "    Ghostlink-Mini Setup Script"
echo "======================================"

if [ $UPDATE_MODE -eq 0 ]; then
    echo "This script will configure your Raspberry Pi 5 for Ghostlink-Mini."
    echo "It requires internet access to download dependencies."
    echo ""
    read -p "Press Enter to continue or Ctrl+C to abort..."
fi

# 1. Update APT
echo "[+] Updating apt repositories..."
apt-get update -y || { echo "[-] Failed to update apt"; exit 1; }

# 2. Install dependencies
echo "[+] Installing system dependencies..."
DEPENDENCIES="git dkms build-essential bc libelf-dev raspberrypi-kernel-headers aircrack-ng hostapd dnsmasq iw rfkill iproute2 wireless-tools python3 python3-pip wifite network-manager"
apt-get install -y $DEPENDENCIES || { echo "[-] Failed to install some dependencies. Please check logs."; exit 1; }

# Install airgeddon (often not in standard repos or outdated)
if ! command -v airgeddon >/dev/null 2>&1; then
    echo "[+] Installing Airgeddon..."
    git clone --depth 1 https://github.com/v1s1t0r1sh3r3/airgeddon.git /opt/airgeddon
    ln -sf /opt/airgeddon/airgeddon.sh /usr/local/bin/airgeddon
else
    echo "[+] Airgeddon is already installed."
fi

# 3. Create directories
echo "[+] Creating Ghostlink-Mini directories..."
mkdir -p /etc/ghostlink
mkdir -p /var/lib/ghostlink
mkdir -p /var/log/ghostlink
chmod -R 700 /etc/ghostlink /var/lib/ghostlink /var/log/ghostlink

# 4. Install Global Command
echo "[+] Installing global command 'ghostlink'..."
# Assuming we are running this from the cloned dir
if [ -f "$(pwd)/src/ghostlink.py" ]; then
    chmod +x $(pwd)/src/ghostlink.py
    ln -sf $(pwd)/src/ghostlink.py /usr/local/bin/ghostlink
    # Also, we should probably symlink the whole repo to /opt/ghostlink-mini if it's not there
    if [ "$(pwd)" != "/opt/ghostlink-mini" ]; then
        echo "[+] Copying project to /opt/ghostlink-mini..."
        cp -r $(pwd) /opt/ghostlink-mini_tmp
        rm -rf /opt/ghostlink-mini
        mv /opt/ghostlink-mini_tmp /opt/ghostlink-mini
        ln -sf /opt/ghostlink-mini/src/ghostlink.py /usr/local/bin/ghostlink
    fi
fi

# 5. Management Network Configuration
if [ $UPDATE_MODE -eq 0 ]; then
    echo ""
    echo "--- Management Network Configuration ---"
    echo "Please enter details for your Management Wi-Fi."
    echo "The onboard Raspberry Pi Wi-Fi will connect to this."
    read -p "SSID: " MGMT_SSID
    read -s -p "Password: " MGMT_PASS
    echo ""
    read -p "Static IP (e.g. 192.168.1.100/24): " MGMT_IP
    read -p "Gateway (e.g. 192.168.1.1): " MGMT_GW
    read -p "DNS (e.g. 8.8.8.8): " MGMT_DNS

    # Identify onboard wifi (assume wlan0 or mmc/brcm)
    ONBOARD_IFACE=$(iw dev | grep -B 10 -i "brcm" | grep Interface | awk '{print $2}' | head -n 1)
    if [ -z "$ONBOARD_IFACE" ]; then
        ONBOARD_IFACE="wlan0" # fallback
    fi

    echo "[+] Configuring $ONBOARD_IFACE for management via NetworkManager..."
    nmcli connection delete "$MGMT_SSID" 2>/dev/null
    nmcli device disconnect $ONBOARD_IFACE 2>/dev/null
    nmcli connection add type wifi ifname $ONBOARD_IFACE con-name "$MGMT_SSID" ssid "$MGMT_SSID"
    nmcli connection modify "$MGMT_SSID" wifi-sec.key-mgmt wpa-psk
    nmcli connection modify "$MGMT_SSID" wifi-sec.psk "$MGMT_PASS"
    nmcli connection modify "$MGMT_SSID" ipv4.addresses "$MGMT_IP"
    nmcli connection modify "$MGMT_SSID" ipv4.gateway "$MGMT_GW"
    nmcli connection modify "$MGMT_SSID" ipv4.dns "$MGMT_DNS"
    nmcli connection modify "$MGMT_SSID" ipv4.method manual
    nmcli connection up "$MGMT_SSID"

    # Save mapping early
    echo "{\"management\": \"$ONBOARD_IFACE\"}" > /etc/ghostlink/adapters.json
fi

# 6. Driver Installations
echo ""
echo "--- Driver Installation ---"
echo "This will take a significant amount of time."

# Helper function for installing drivers
install_driver() {
    local name=$1
    local repo_url=$2
    local dir_name=$3
    local check_module=$4

    if lsmod | grep -q "$check_module" || modinfo "$check_module" >/dev/null 2>&1; then
        echo "[+] Driver $name ($check_module) already installed."
    else
        echo "[+] Installing $name..."
        cd /usr/src
        git clone "$repo_url" "$dir_name"
        cd "$dir_name"
        ./install-driver.sh || { echo "[-] Failed to install $name. Check logs."; exit 1; }
    fi
}

# RTL8812AU
install_driver "RTL8812AU" "https://github.com/morrownr/8812au-20210820.git" "8812au" "8812au"

# RTL88x2BU
install_driver "RTL88x2BU" "https://github.com/morrownr/88x2bu-20210702.git" "88x2bu" "88x2bu"

# RTL8188EUS
install_driver "RTL8188EUS" "https://github.com/aircrack-ng/rtl8188eus.git" "rtl8188eus" "8188eu"
# Aircrack repo usually requires manual make / dkms build
if [ -d "/usr/src/rtl8188eus" ] && ! modinfo 8188eu >/dev/null 2>&1; then
    cd /usr/src/rtl8188eus
    echo "blacklist r8188eu" > /etc/modprobe.d/realtek.conf
    make && make install
    modprobe 8188eu
fi

# 7. Verification
echo ""
echo "--- Verification ---"
if command -v ghostlink >/dev/null 2>&1; then
    echo "[+] 'ghostlink' command installed successfully."
else
    echo "[-] 'ghostlink' command failed to install."
fi

# 8. Cleanup
echo "[+] Cleaning up..."
apt-get autoremove -y
apt-get clean

echo "======================================"
echo "    Setup Complete!"
echo "    Run 'ghostlink' to start."
echo "======================================"

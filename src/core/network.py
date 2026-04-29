import subprocess
import os
import re
import time
from .config import load_adapter_map, save_adapter_map

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()

def run_cmd_no_check(cmd):
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip(), result.returncode

def get_interfaces():
    # Returns a list of wireless interfaces
    out = run_cmd("iw dev | grep Interface | awk '{print $2}'")
    if out:
        return out.split('\n')
    return []

def get_driver(iface):
    # Try to find the driver for a given interface
    try:
        out = run_cmd(f"readlink /sys/class/net/{iface}/device/driver")
        return os.path.basename(out)
    except Exception:
        return "Unknown"

def detect_adapters():
    ifaces = get_interfaces()
    adapters = {
        "management": None,
        "rtl8812au": None,
        "rtl88x2bu": None,
        "rtl8188eus": None
    }
    
    # Try to load existing map first
    saved_map = load_adapter_map()
    
    for iface in ifaces:
        driver = get_driver(iface)
        # Identify based on driver
        if driver == "8812au":
            adapters["rtl8812au"] = iface
        elif driver == "88x2bu":
            adapters["rtl88x2bu"] = iface
        elif driver in ["r8188eu", "8188eu"]:
            adapters["rtl8188eus"] = iface
        elif driver in ["brcmfmac", "brcmsmac"]: # Onboard pi wifi usually uses broadcom
            adapters["management"] = iface
            
    # If management isn't found by driver, check saved map or default to wlan0 if others are found
    if not adapters["management"]:
        if "management" in saved_map and saved_map["management"] in ifaces:
            adapters["management"] = saved_map["management"]
            
    save_adapter_map(adapters)
    return adapters

def get_management_ip(iface):
    out = run_cmd(f"ip -4 addr show {iface} | grep inet | awk '{{print $2}}'")
    if out:
        return out.split('/')[0]
    return "Disconnected"

def scan_networks(iface):
    if not iface:
        return []
    
    # Put interface up just in case
    run_cmd(f"ip link set {iface} up")
    
    # Use iwlist or nmcli for scanning (nmcli is easier to parse if NetworkManager is running)
    out, code = run_cmd_no_check(f"nmcli -t -f SSID,BSSID,CHAN,SIGNAL,SECURITY dev wifi list ifname {iface}")
    networks = []
    if code == 0 and out:
        for line in out.split('\n'):
            parts = line.split(':')
            if len(parts) >= 5:
                # Handle escaping in nmcli output
                ssid = parts[0].replace('\\:', ':')
                bssid = parts[1] + ":" + parts[2] + ":" + parts[3] + ":" + parts[4] + ":" + parts[5] + ":" + parts[6]
                bssid = bssid.replace('\\', '')
                try:
                    chan = int(parts[7])
                    signal = int(parts[8])
                    enc = parts[9]
                except (IndexError, ValueError):
                    continue
                if ssid: # Ignore hidden networks for now
                    networks.append({
                        "ssid": ssid,
                        "bssid": bssid,
                        "channel": chan,
                        "signal": signal,
                        "encryption": enc,
                        "interface": iface
                    })
    return networks

def connect_network(iface, ssid, password):
    # Clean previous connections for this iface to prevent conflicts
    run_cmd(f"nmcli device disconnect {iface}")
    
    cmd = f"nmcli device wifi connect '{ssid}' password '{password}' ifname {iface}"
    out, code = run_cmd_no_check(cmd)
    
    if code == 0:
        return True
    return False

def check_internet():
    # Simple ping check to see if we have internet routing
    out, code = run_cmd_no_check("ping -c 1 -W 2 8.8.8.8")
    return code == 0

def start_ap(ap_iface, uplink_iface):
    # 1. Stop NM from managing AP interface
    run_cmd(f"nmcli device set {ap_iface} managed no")
    run_cmd(f"ip link set {ap_iface} up")
    run_cmd(f"ip addr add 10.0.0.1/24 dev {ap_iface}")
    
    # 2. Configure dnsmasq
    dnsmasq_conf = f"""
interface={ap_iface}
dhcp-range=10.0.0.10,10.0.0.100,255.255.255.0,24h
dhcp-option=option:router,10.0.0.1
dhcp-option=option:dns-server,8.8.8.8,8.8.4.4
"""
    with open("/tmp/ghostlink_dnsmasq.conf", "w") as f:
        f.write(dnsmasq_conf)
        
    # 3. Configure hostapd
    hostapd_conf = f"""
interface={ap_iface}
driver=nl80211
ssid=Ghostlink-AP
hw_mode=g
channel=6
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=Ghostlink123*
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
"""
    with open("/tmp/ghostlink_hostapd.conf", "w") as f:
        f.write(hostapd_conf)
        
    # 4. Enable NAT
    run_cmd("sysctl -w net.ipv4.ip_forward=1")
    run_cmd(f"iptables -t nat -A POSTROUTING -o {uplink_iface} -j MASQUERADE")
    run_cmd(f"iptables -A FORWARD -i {uplink_iface} -o {ap_iface} -m state --state RELATED,ESTABLISHED -j ACCEPT")
    run_cmd(f"iptables -A FORWARD -i {ap_iface} -o {uplink_iface} -j ACCEPT")
    
    # 5. Start services
    run_cmd("killall hostapd dnsmasq") # Clean up old ones
    time.sleep(1)
    run_cmd("dnsmasq -C /tmp/ghostlink_dnsmasq.conf")
    run_cmd("hostapd -B /tmp/ghostlink_hostapd.conf")
    
    return True

def stop_ap(ap_iface, uplink_iface):
    # Kill services
    run_cmd("killall hostapd dnsmasq")
    
    # Remove NAT rules
    run_cmd(f"iptables -t nat -D POSTROUTING -o {uplink_iface} -j MASQUERADE")
    run_cmd(f"iptables -D FORWARD -i {uplink_iface} -o {ap_iface} -m state --state RELATED,ESTABLISHED -j ACCEPT")
    run_cmd(f"iptables -D FORWARD -i {ap_iface} -o {uplink_iface} -j ACCEPT")
    
    # Reset interface
    run_cmd(f"ip addr flush dev {ap_iface}")
    run_cmd(f"nmcli device set {ap_iface} managed yes")
    
def restart_networking():
    # Restart NM and networking
    run_cmd("systemctl restart NetworkManager")
    time.sleep(2)
    return True

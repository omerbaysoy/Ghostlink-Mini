import subprocess
import os
import time
import json
import shlex
from .config import load_adapter_map, save_adapter_map

RUNTIME_DIR = "/run/ghostlink"
HOSTAPD_CONF = os.path.join(RUNTIME_DIR, "hostapd.conf")
DNSMASQ_CONF = os.path.join(RUNTIME_DIR, "dnsmasq.conf")
HOSTAPD_PID = os.path.join(RUNTIME_DIR, "hostapd.pid")
DNSMASQ_PID = os.path.join(RUNTIME_DIR, "dnsmasq.pid")
AP_STATE = os.path.join(RUNTIME_DIR, "ap_state.json")
IPTABLES_COMMENT = "ghostlink-mini"

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return (e.stdout or e.stderr or "").strip()

def run_cmd_no_check(cmd):
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip(), result.returncode

def get_interfaces():
    out, code = run_cmd_no_check("iw dev")
    if code != 0 or not out:
        return []
    return [line.split()[1] for line in out.splitlines() if line.strip().startswith("Interface ")]

def interface_exists(iface):
    if not iface:
        return False
    return os.path.exists(f"/sys/class/net/{os.path.basename(iface)}")

def get_driver(iface):
    safe_iface = os.path.basename(iface)
    path = f"/sys/class/net/{safe_iface}/device/driver"
    target = os.path.realpath(path) if os.path.exists(path) else ""
    return os.path.basename(target) if target else "Unknown"

def get_connected_ssid(iface):
    if not interface_exists(iface):
        return "Unknown"
    out, code = run_cmd_no_check(f"iw dev {shlex.quote(iface)} link")
    if code != 0:
        return "Unknown"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            return line.split("SSID:", 1)[1].strip() or "Unknown"
    return "Unknown"

def _nm_active_wifi_interfaces():
    out, code = run_cmd_no_check("nmcli -t -f DEVICE,TYPE,STATE device status")
    if code != 0:
        return []
    active = []
    for line in out.splitlines():
        parts = _split_nmcli_line(line)
        if len(parts) >= 3 and parts[1] == "wifi" and parts[2] == "connected":
            active.append(parts[0])
    return active

def detect_adapters():
    ifaces = get_interfaces()
    adapters = {
        "management": None,
        "rtl8812au": None,
        "rtl88x2bu": None,
        "rtl8188eus": None
    }
    
    saved_map = load_adapter_map()
    saved_management = saved_map.get("management")
    if saved_management in ifaces:
        adapters["management"] = saved_management
    
    for iface in ifaces:
        if iface == adapters["management"]:
            continue
        driver = get_driver(iface)
        if driver in ["8812au", "rtw_8812au"]:
            adapters["rtl8812au"] = iface
        elif driver in ["88x2bu", "rtw_8822bu"]:
            adapters["rtl88x2bu"] = iface
        elif driver in ["r8188eu", "8188eu"]:
            adapters["rtl8188eus"] = iface
        elif driver in ["brcmfmac", "brcmsmac"]: # Onboard pi wifi usually uses broadcom
            adapters["management"] = iface

    if not adapters["management"]:
        for iface in _nm_active_wifi_interfaces():
            if iface in ifaces and iface not in [adapters["rtl8812au"], adapters["rtl88x2bu"], adapters["rtl8188eus"]]:
                adapters["management"] = iface
                break

    save_adapter_map(adapters)
    return adapters

def get_management_ip(iface):
    if not interface_exists(iface):
        return "Disconnected"
    out = run_cmd(f"ip -4 addr show {shlex.quote(iface)} | awk '/inet / {{print $2}}'")
    if out:
        return out.split('/')[0]
    return "Disconnected"

def _split_nmcli_line(line):
    parts = []
    current = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts

def scan_networks(iface):
    if not interface_exists(iface):
        return []
    
    run_cmd(f"ip link set {shlex.quote(iface)} up")
    
    out, code = run_cmd_no_check(f"nmcli -t -f SSID,BSSID,CHAN,SIGNAL,SECURITY dev wifi list ifname {shlex.quote(iface)} --rescan yes")
    networks = []
    if code == 0 and out:
        for line in out.split('\n'):
            parts = _split_nmcli_line(line)
            if len(parts) >= 5:
                ssid, bssid = parts[0], parts[1]
                try:
                    chan = int(parts[2])
                    signal = int(parts[3])
                    enc = parts[4]
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
    if not interface_exists(iface):
        return False

    run_cmd(f"nmcli device disconnect {shlex.quote(iface)}")

    cmd = (
        "nmcli device wifi connect "
        f"{shlex.quote(ssid)} password {shlex.quote(password)} ifname {shlex.quote(iface)}"
    )
    out, code = run_cmd_no_check(cmd)
    
    if code == 0:
        return True
    return False

def check_internet():
    # Simple ping check to see if we have internet routing
    out, code = run_cmd_no_check("ping -c 1 -W 2 8.8.8.8")
    return code == 0

def require_root(action):
    if os.geteuid() != 0:
        print(f"Error: {action} requires root. Run with sudo.")
        return False
    return True

def _ensure_runtime_dir():
    os.makedirs(RUNTIME_DIR, exist_ok=True)

def _pid_matches(pid_path, expected):
    try:
        with open(pid_path, "r") as f:
            pid = int(f.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().decode(errors="ignore").replace("\x00", " ")
        return pid, expected in cmdline
    except Exception:
        return None, False

def _stop_pid(pid_path, expected):
    pid, matches = _pid_matches(pid_path, expected)
    if pid and matches:
        run_cmd_no_check(f"kill {pid}")
        time.sleep(1)
        run_cmd_no_check(f"kill -0 {pid} && kill -9 {pid}")
    if os.path.exists(pid_path):
        try:
            os.remove(pid_path)
        except OSError:
            pass

def is_ghostlink_ap_running():
    _, hostapd_ok = _pid_matches(HOSTAPD_PID, HOSTAPD_CONF)
    _, dnsmasq_ok = _pid_matches(DNSMASQ_PID, DNSMASQ_CONF)
    return hostapd_ok and dnsmasq_ok

def _iptables_check(table, rule):
    table_arg = f"-t {table} " if table else ""
    _, code = run_cmd_no_check(f"iptables {table_arg}-C {rule}")
    return code == 0

def _iptables_add(table, rule):
    table_arg = f"-t {table} " if table else ""
    if not _iptables_check(table, rule):
        run_cmd(f"iptables {table_arg}-A {rule}")

def _iptables_delete_all(table, rule):
    table_arg = f"-t {table} " if table else ""
    while _iptables_check(table, rule):
        run_cmd_no_check(f"iptables {table_arg}-D {rule}")

def _ap_rules(ap_iface, uplink_iface):
    ap = shlex.quote(ap_iface)
    up = shlex.quote(uplink_iface)
    comment = shlex.quote(IPTABLES_COMMENT)
    return [
        ("nat", f"POSTROUTING -o {up} -m comment --comment {comment} -j MASQUERADE"),
        ("", f"FORWARD -i {up} -o {ap} -m state --state RELATED,ESTABLISHED -m comment --comment {comment} -j ACCEPT"),
        ("", f"FORWARD -i {ap} -o {up} -m comment --comment {comment} -j ACCEPT"),
    ]

def start_ap(ap_iface, uplink_iface):
    if not require_root("Starting Ghostlink-AP"):
        return False
    if not interface_exists(ap_iface):
        print(f"Error: AP interface {ap_iface} does not exist.")
        return False
    if not interface_exists(uplink_iface):
        print(f"Error: Uplink interface {uplink_iface} does not exist.")
        return False

    _ensure_runtime_dir()
    stop_ap(ap_iface, uplink_iface)

    run_cmd(f"nmcli device set {shlex.quote(ap_iface)} managed no")
    run_cmd(f"ip link set {shlex.quote(ap_iface)} up")
    run_cmd_no_check(f"ip addr flush dev {shlex.quote(ap_iface)}")
    run_cmd(f"ip addr add 10.0.0.1/24 dev {shlex.quote(ap_iface)}")
    
    dnsmasq_conf = f"""
interface={ap_iface}
dhcp-range=10.0.0.10,10.0.0.100,255.255.255.0,24h
dhcp-option=option:router,10.0.0.1
dhcp-option=option:dns-server,8.8.8.8,8.8.4.4
"""
    with open(DNSMASQ_CONF, "w") as f:
        f.write(dnsmasq_conf)
        
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
    with open(HOSTAPD_CONF, "w") as f:
        f.write(hostapd_conf)
        
    run_cmd("sysctl -w net.ipv4.ip_forward=1")
    for table, rule in _ap_rules(ap_iface, uplink_iface):
        _iptables_add(table, rule)

    with open(AP_STATE, "w") as f:
        json.dump({"ap_iface": ap_iface, "uplink_iface": uplink_iface}, f)

    run_cmd(
        "dnsmasq "
        f"--conf-file={shlex.quote(DNSMASQ_CONF)} "
        f"--pid-file={shlex.quote(DNSMASQ_PID)}"
    )
    time.sleep(1)
    run_cmd(f"hostapd -B -P {shlex.quote(HOSTAPD_PID)} {shlex.quote(HOSTAPD_CONF)}")
    
    return True

def stop_ap(ap_iface, uplink_iface):
    if not require_root("Stopping Ghostlink-AP"):
        return False

    if (not ap_iface or not uplink_iface) and os.path.exists(AP_STATE):
        try:
            with open(AP_STATE, "r") as f:
                state = json.load(f)
            ap_iface = ap_iface or state.get("ap_iface")
            uplink_iface = uplink_iface or state.get("uplink_iface")
        except Exception:
            pass

    _stop_pid(HOSTAPD_PID, HOSTAPD_CONF)
    _stop_pid(DNSMASQ_PID, DNSMASQ_CONF)

    if ap_iface and uplink_iface:
        for table, rule in _ap_rules(ap_iface, uplink_iface):
            _iptables_delete_all(table, rule)

    if ap_iface:
        run_cmd_no_check(f"ip addr flush dev {shlex.quote(ap_iface)}")
        run_cmd_no_check(f"nmcli device set {shlex.quote(ap_iface)} managed yes")

    for path in [AP_STATE, HOSTAPD_CONF, DNSMASQ_CONF]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    return True
    
def restart_networking():
    if not require_root("Restarting networking"):
        return False
    run_cmd("systemctl restart NetworkManager")
    time.sleep(2)
    return True

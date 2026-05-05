import subprocess
import os
import time
import json
import shlex
import re
from .config import (
    GHOSTLINK_LOG_DIR, load_adapter_map, save_adapter_map,
    RTL8812AU_USB_IDS, RTL88X2BU_USB_IDS, RTL8188EUS_USB_IDS, MT7612U_USB_IDS,
)

RUNTIME_DIR = "/run/ghostlink"
HOSTAPD_CONF = os.path.join(RUNTIME_DIR, "hostapd.conf")
DNSMASQ_CONF = os.path.join(RUNTIME_DIR, "dnsmasq.conf")
HOSTAPD_PID = os.path.join(RUNTIME_DIR, "hostapd.pid")
DNSMASQ_PID = os.path.join(RUNTIME_DIR, "dnsmasq.pid")
AP_STATE = os.path.join(RUNTIME_DIR, "ap_state.json")
AP_LOG = os.path.join(GHOSTLINK_LOG_DIR, "ap.log")
IPTABLES_COMMENT = "ghostlink"
LEGACY_IPTABLES_COMMENT = "ghostlink" + "-mini"

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return (e.stdout or e.stderr or "").strip()

def run_cmd_no_check(cmd):
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    output = "\n".join(part for part in [stdout, stderr] if part)
    return output, result.returncode

def get_interfaces():
    out, code = run_cmd_no_check("iw dev")
    if code != 0 or not out:
        return []
    return [line.split()[1] for line in out.splitlines() if line.strip().startswith("Interface ")]

def interface_exists(iface):
    if not iface:
        return False
    return os.path.exists(f"/sys/class/net/{os.path.basename(iface)}")

def is_wireless_interface(iface):
    if not interface_exists(iface):
        return False
    safe_iface = os.path.basename(iface)
    return safe_iface in get_interfaces() or os.path.exists(f"/sys/class/net/{safe_iface}/wireless")

def get_operstate(iface):
    if not interface_exists(iface):
        return "missing"
    safe_iface = os.path.basename(iface)
    try:
        with open(f"/sys/class/net/{safe_iface}/operstate", "r") as f:
            return f.read().strip()
    except OSError:
        return "unknown"

def get_driver(iface):
    safe_iface = os.path.basename(iface)
    path = f"/sys/class/net/{safe_iface}/device/driver"
    target = os.path.realpath(path) if os.path.exists(path) else ""
    return os.path.basename(target) if target else "Unknown"

def get_modalias(iface):
    safe_iface = os.path.basename(iface)
    path = f"/sys/class/net/{safe_iface}/device/modalias"
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return ""

def get_usb_id(iface):
    safe_iface = os.path.basename(iface)
    
    device_path = f"/sys/class/net/{safe_iface}/device"
    current = device_path
    for _ in range(3):
        if os.path.exists(os.path.join(current, "idVendor")) and os.path.exists(os.path.join(current, "idProduct")):
            try:
                with open(os.path.join(current, "idVendor")) as f:
                    vendor = f.read().strip()
                with open(os.path.join(current, "idProduct")) as f:
                    product = f.read().strip()
                return f"{vendor}:{product}"
            except OSError:
                pass
        current = os.path.dirname(os.path.realpath(current))

    uevent_path = f"/sys/class/net/{safe_iface}/device/uevent"
    if os.path.exists(uevent_path):
        try:
            with open(uevent_path, "r") as f:
                for line in f:
                    if line.startswith("PRODUCT="):
                        parts = line.strip().split('=')[1].split('/')
                        if len(parts) >= 2:
                            return f"{int(parts[0], 16):04x}:{int(parts[1], 16):04x}"
        except OSError:
            pass
            
    modalias_path = f"/sys/class/net/{safe_iface}/device/modalias"
    if os.path.exists(modalias_path):
        try:
            with open(modalias_path, "r") as f:
                modalias = f.read().strip()
                if modalias.startswith("usb:v"):
                    import re
                    m = re.search(r"v([0-9A-Fa-f]{4})p([0-9A-Fa-f]{4})", modalias)
                    if m:
                        return f"{m.group(1).lower()}:{m.group(2).lower()}"
        except OSError:
            pass
            
    return None

def mt7612u_usb_present():
    for usb_id in MT7612U_USB_IDS:
        out, code = run_cmd_no_check(f"lsusb -d {usb_id}")
        if code == 0 and out.strip():
            return True
    return False

def list_usb_wifi_devices():
    out, code = run_cmd_no_check("lsusb")
    if code != 0 or not out:
        return []

    known_ids = (
        RTL8812AU_USB_IDS
        | RTL88X2BU_USB_IDS
        | RTL8188EUS_USB_IDS
        | MT7612U_USB_IDS
    )
    wifi_keywords = [
        "802.11", "wireless", "wi-fi", "wifi", "wlan",
        "realtek", "mediatek", "ralink", "alfa", "tp-link",
        "edimax", "d-link", "asus", "linksys", "mt7612",
        "rtl8812", "rtl8188", "rtl88",
    ]

    devices = []
    for line in out.splitlines():
        usb_id = None
        match = re.search(r"\bID\s+([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})\b", line)
        if match:
            usb_id = match.group(1).lower()

        lower_line = line.lower()
        if usb_id in known_ids or any(keyword in lower_line for keyword in wifi_keywords):
            devices.append({
                "usb_id": usb_id or "unknown",
                "description": line.strip(),
            })
    return devices

def get_default_route_iface():
    for cmd in ["ip route get 1.1.1.1", "ip route show default"]:
        out, code = run_cmd_no_check(cmd)
        if code != 0 or not out:
            continue
        parts = out.split()
        if "dev" in parts:
            idx = parts.index("dev") + 1
            if idx < len(parts):
                return parts[idx]
    return None

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

def _known_external_role(iface):
    driver = get_driver(iface)
    usb_id = get_usb_id(iface)
    modalias = get_modalias(iface).lower()

    if usb_id in RTL8812AU_USB_IDS:
        return "rtl8812au"
    if usb_id in RTL88X2BU_USB_IDS:
        return "rtl88x2bu"
    if usb_id in RTL8188EUS_USB_IDS:
        return "rtl8188eus"
    if usb_id in MT7612U_USB_IDS:
        return "mt7612u"
    if driver in ["8812au", "88XXau", "rtw_8812au", "rtw88_8812au"]:
        return "rtl8812au"
    if driver in ["88x2bu", "rtw_8822bu", "rtw88_8822bu"]:
        return "rtl88x2bu"
    if driver in ["r8188eu", "8188eu"]:
        return "rtl8188eus"
    if driver == "rtl8xxxu" and any(chip in modalias for chip in ["v2357p010c", "v0bdap8179"]):
        return "rtl8188eus"
    if driver in ["mt76x2u", "mt76usb"]:
        return "mt7612u"
    return None

def detect_adapters():
    ifaces = get_interfaces()
    adapters = {
        "management": None,
        "rtl8812au": None,
        "mt7612u": None,
        "rtl88x2bu": None,
        "rtl8188eus": None,
    }

    # Priority 1: saved management interface (must be wireless and not a known active-role adapter)
    saved_map = load_adapter_map()
    saved_management = saved_map.get("management")
    if (saved_management
            and interface_exists(saved_management)
            and is_wireless_interface(saved_management)
            and not _known_external_role(saved_management)):
        adapters["management"] = saved_management

    # Priority 2: detect all known external USB/driver adapters
    for iface in ifaces:
        driver = get_driver(iface)
        role = _known_external_role(iface)
        if role and not adapters[role]:
            adapters[role] = iface
        elif driver in ["brcmfmac", "brcmsmac"]:
            # Onboard Broadcom: strong management candidate; only set if not already saved
            if not adapters["management"] or adapters["management"] != saved_management:
                adapters["management"] = iface

    # Priority 3: NM active Wi-Fi (excluding already-assigned external roles)
    if not adapters["management"]:
        active_ifaces = {adapters["rtl8812au"], adapters["mt7612u"],
                         adapters["rtl88x2bu"], adapters["rtl8188eus"]}
        for iface in _nm_active_wifi_interfaces():
            if iface in ifaces and iface not in active_ifaces:
                adapters["management"] = iface
                break

    # Priority 4: default route as last resort — wireless only, never ethernet
    if not adapters["management"]:
        default_iface = get_default_route_iface()
        active_ifaces = {adapters["rtl8812au"], adapters["mt7612u"],
                         adapters["rtl88x2bu"], adapters["rtl8188eus"]}
        if (default_iface
                and interface_exists(default_iface)
                and is_wireless_interface(default_iface)
                and default_iface not in active_ifaces):
            adapters["management"] = default_iface

    # Deduplication guard: management must not appear in any active role
    mgmt = adapters["management"]
    if mgmt:
        for role in ["rtl8812au", "mt7612u", "rtl88x2bu", "rtl8188eus"]:
            if adapters[role] == mgmt:
                adapters[role] = None

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
    if not is_wireless_interface(iface):
        return []
    
    _, up_code = run_cmd_no_check(f"ip link set {shlex.quote(iface)} up")
    if up_code != 0 and get_operstate(iface) == "down":
        return []
    
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
    if not is_wireless_interface(iface):
        return False

    run_cmd_no_check(f"nmcli device set {shlex.quote(iface)} managed yes")
    run_cmd_no_check(f"ip link set {shlex.quote(iface)} up")
    run_cmd(f"nmcli device disconnect {shlex.quote(iface)}")

    cmd = (
        "nmcli device wifi connect "
        f"{shlex.quote(ssid)} password {shlex.quote(password)} ifname {shlex.quote(iface)}"
    )
    out, code = run_cmd_no_check(cmd)
    
    if code == 0:
        return True
    return False

def check_internet(iface=None):
    # Simple ping check to see if we have internet routing
    if iface:
        out, code = run_cmd_no_check(f"ping -I {shlex.quote(iface)} -c 1 -W 2 8.8.8.8")
    else:
        out, code = run_cmd_no_check("ping -c 1 -W 2 8.8.8.8")
    return code == 0

def require_root(action):
    if os.geteuid() != 0:
        print(f"Error: {action} requires root. Run with sudo.")
        return False
    return True

def _ensure_runtime_dir():
    os.makedirs(RUNTIME_DIR, exist_ok=True)

def _write_ap_log(label, output):
    try:
        os.makedirs(GHOSTLINK_LOG_DIR, exist_ok=True)
        with open(AP_LOG, "a") as f:
            f.write(f"\n--- {label} ---\n")
            if output:
                f.write(output)
                f.write("\n")
    except OSError:
        pass

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

def _ap_rules(ap_iface, uplink_iface, comment_value=IPTABLES_COMMENT):
    ap = shlex.quote(ap_iface)
    up = shlex.quote(uplink_iface)
    comment = shlex.quote(comment_value)
    return [
        ("nat", f"POSTROUTING -o {up} -m comment --comment {comment} -j MASQUERADE"),
        ("", f"FORWARD -i {up} -o {ap} -m state --state RELATED,ESTABLISHED -m comment --comment {comment} -j ACCEPT"),
        ("", f"FORWARD -i {ap} -o {up} -m comment --comment {comment} -j ACCEPT"),
    ]

def _ap_cleanup_rules(ap_iface, uplink_iface):
    comments = [IPTABLES_COMMENT]
    if LEGACY_IPTABLES_COMMENT not in comments:
        comments.append(LEGACY_IPTABLES_COMMENT)
    rules = []
    for comment in comments:
        rules.extend(_ap_rules(ap_iface, uplink_iface, comment))
    return rules


# ---------------------------------------------------------------------------
# VPN Gateway Phase 1
# ---------------------------------------------------------------------------

AP_KILLSWITCH_COMMENT = "ghostlink-ap-killswitch"
AP_SUBNET = "10.0.0.0/24"
VPN_IFACE_PREFIXES = ("wg", "tun", "tailscale", "ppp", "gpd", "proton", "nordlynx", "mullvad")


def _all_link_interfaces():
    """Return list of all interface names known to the kernel via /sys/class/net."""
    try:
        return [name for name in os.listdir("/sys/class/net") if name != "lo"]
    except OSError:
        return []


def _iface_is_up(iface):
    return get_operstate(iface) == "up"


def _iface_has_address(iface):
    out, code = run_cmd_no_check(f"ip -4 -o addr show dev {shlex.quote(iface)}")
    return code == 0 and out.strip() != ""


def list_uplink_candidates(adapters):
    """Return list of dicts describing valid uplink candidates for Direct NAT mode.

    Each entry: {"iface": <name>, "kind": <label>, "state": "up"|"down", "default_route": bool}.
    Excludes the AP adapter itself and tunnel interfaces (those are VPN-mode candidates).
    """
    ap_iface = adapters.get("rtl88x2bu")
    role_label = {
        "rtl8812au": "RTL8812AU pentest/uplink",
        "mt7612u": "MT7612U pentest/uplink",
        "rtl8188eus": "RTL8188EUS backup",
    }
    results = []
    seen = set()
    default_iface = get_default_route_iface()

    # Management onboard Wi-Fi (allowed to be selected as uplink intentionally)
    mgmt = adapters.get("management")
    if mgmt and mgmt != ap_iface and mgmt not in seen:
        seen.add(mgmt)
        results.append({
            "iface": mgmt,
            "kind": "management Wi-Fi",
            "state": "up" if _iface_is_up(mgmt) else "down",
            "default_route": (mgmt == default_iface),
        })

    # External pentest adapters as uplink (not AP, not tunnel)
    for role in ("rtl8812au", "mt7612u", "rtl8188eus"):
        iface = adapters.get(role)
        if not iface or iface == ap_iface or iface in seen:
            continue
        seen.add(iface)
        results.append({
            "iface": iface,
            "kind": role_label.get(role, role),
            "state": "up" if _iface_is_up(iface) else "down",
            "default_route": (iface == default_iface),
        })

    # Wired and other non-tunnel interfaces (eth0, usb0, etc.)
    for iface in _all_link_interfaces():
        if iface in seen or iface == ap_iface:
            continue
        if iface.startswith(VPN_IFACE_PREFIXES):
            continue
        # Skip if it's another wlan we already covered
        if iface.startswith("wlan") and iface in seen:
            continue
        kind = "wired" if iface.startswith(("eth", "en")) else "other"
        results.append({
            "iface": iface,
            "kind": kind,
            "state": "up" if _iface_is_up(iface) else "down",
            "default_route": (iface == default_iface),
        })
        seen.add(iface)

    return results


def list_vpn_interfaces():
    """Return list of detected tunnel/VPN interface dicts: {"iface", "state", "has_address"}."""
    results = []
    for iface in _all_link_interfaces():
        if not iface.startswith(VPN_IFACE_PREFIXES):
            continue
        results.append({
            "iface": iface,
            "state": "up" if _iface_is_up(iface) else "down",
            "has_address": _iface_has_address(iface),
        })
    return results


def _killswitch_rules(ap_iface, vpn_iface):
    """Drop AP-subnet egress on every non-VPN interface; allow only via vpn_iface.

    We anchor on AP_SUBNET so Pi host traffic (other source IPs) is not affected.
    Rules are returned as (table, rule_string) tuples to plug into _iptables_add /
    _iptables_delete_all. Order: ACCEPT-on-VPN inserted first, generic DROP after.
    """
    ap_q = shlex.quote(ap_iface)
    vpn_q = shlex.quote(vpn_iface)
    subnet_q = shlex.quote(AP_SUBNET)
    comment = shlex.quote(AP_KILLSWITCH_COMMENT)
    return [
        # Permit AP subnet egress only via the chosen VPN interface
        ("", f"FORWARD -i {ap_q} -s {subnet_q} -o {vpn_q} -m comment --comment {comment} -j ACCEPT"),
        # Deny AP subnet egress through anything else
        ("", f"FORWARD -i {ap_q} -s {subnet_q} ! -o {vpn_q} -m comment --comment {comment} -j DROP"),
    ]


def get_ap_state():
    """Return the current AP state dict, or None if no AP is configured/running."""
    if not os.path.exists(AP_STATE):
        return None
    try:
        with open(AP_STATE, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def get_killswitch_status():
    """Return killswitch summary string for the current AP state."""
    state = get_ap_state()
    if not state:
        return "not applicable (AP inactive)"
    if state.get("mode") != "vpn":
        return "not applicable (Direct NAT mode)"
    vpn_iface = state.get("vpn_iface")
    if not vpn_iface:
        return "not applicable (no VPN interface recorded)"
    # Check whether our killswitch rules are present
    comment = shlex.quote(AP_KILLSWITCH_COMMENT)
    out, code = run_cmd_no_check(f"iptables -S FORWARD")
    if code != 0:
        return "unknown"
    if AP_KILLSWITCH_COMMENT in out:
        return f"active (allow via {vpn_iface}, drop via others)"
    return "inactive (rules missing)"

def start_ap(ap_iface, uplink_iface, mode="direct", vpn_iface=None):
    """Start Ghostlink-AP.

    mode="direct": NAT AP traffic out via uplink_iface (legacy behavior).
    mode="vpn":    NAT AP traffic out via vpn_iface; install kill-switch so AP-subnet
                   traffic cannot leak through any other interface.
    """
    if not require_root("Starting Ghostlink-AP"):
        return False
    if not interface_exists(ap_iface):
        print(f"Error: AP interface {ap_iface} does not exist.")
        return False

    if mode == "vpn":
        if not vpn_iface:
            print("Error: VPN Gateway mode requires a VPN interface.")
            return False
        if not interface_exists(vpn_iface):
            print(f"Error: VPN interface {vpn_iface} does not exist. Bring it up before starting AP.")
            return False
        if not _iface_is_up(vpn_iface):
            print(f"Error: VPN interface {vpn_iface} is not up. AP will not start (fail closed).")
            return False
        if vpn_iface == ap_iface:
            print(f"Error: VPN interface {vpn_iface} cannot equal AP interface.")
            return False
        # Egress nominally happens via the VPN interface
        egress_iface = vpn_iface
    else:
        if not uplink_iface:
            print("Error: Direct NAT mode requires an uplink interface.")
            return False
        if not interface_exists(uplink_iface):
            print(f"Error: Uplink interface {uplink_iface} does not exist.")
            return False
        if uplink_iface == ap_iface:
            print(f"Error: Uplink interface cannot equal AP interface ({ap_iface}).")
            return False
        egress_iface = uplink_iface

    _ensure_runtime_dir()
    # Stop only this AP's prior instance (state file knows previous egress)
    prev_state = get_ap_state()
    prev_egress = (prev_state or {}).get("uplink_iface") or (prev_state or {}).get("vpn_iface") or egress_iface
    stop_ap(ap_iface, prev_egress)

    run_cmd(f"nmcli device set {shlex.quote(ap_iface)} managed no")
    run_cmd(f"ip link set {shlex.quote(ap_iface)} up")
    run_cmd_no_check(f"ip addr flush dev {shlex.quote(ap_iface)}")
    run_cmd(f"ip addr add 10.0.0.1/24 dev {shlex.quote(ap_iface)}")

    dnsmasq_conf = f"""
interface={ap_iface}
bind-interfaces
port=0
dhcp-authoritative
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

    # NAT/forwarding rules toward the egress interface
    for table, rule in _ap_rules(ap_iface, egress_iface):
        _iptables_add(table, rule)

    # VPN mode: install kill-switch (allow AP subnet via vpn_iface, drop elsewhere)
    if mode == "vpn":
        for table, rule in _killswitch_rules(ap_iface, vpn_iface):
            _iptables_add(table, rule)

    state = {
        "ap_iface": ap_iface,
        "mode": mode,
        "uplink_iface": uplink_iface if mode == "direct" else None,
        "vpn_iface": vpn_iface if mode == "vpn" else None,
        "ap_subnet": AP_SUBNET,
        "last_started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(AP_STATE, "w") as f:
        json.dump(state, f)

    dnsmasq_out, dnsmasq_code = run_cmd_no_check(
        "dnsmasq "
        f"--conf-file={shlex.quote(DNSMASQ_CONF)} "
        f"--pid-file={shlex.quote(DNSMASQ_PID)}"
    )
    _write_ap_log("dnsmasq", dnsmasq_out)
    time.sleep(1)
    _, dnsmasq_ok = _pid_matches(DNSMASQ_PID, DNSMASQ_CONF)
    if dnsmasq_code != 0 or not dnsmasq_ok:
        print(f"Error: dnsmasq failed to start. See {AP_LOG}")
        stop_ap(ap_iface, egress_iface)
        return False

    hostapd_out, hostapd_code = run_cmd_no_check(
        f"hostapd -B -P {shlex.quote(HOSTAPD_PID)} {shlex.quote(HOSTAPD_CONF)}"
    )
    _write_ap_log("hostapd", hostapd_out)
    time.sleep(1)
    _, hostapd_ok = _pid_matches(HOSTAPD_PID, HOSTAPD_CONF)
    if hostapd_code != 0 or not hostapd_ok:
        print(f"Error: hostapd failed to start. See {AP_LOG}")
        stop_ap(ap_iface, egress_iface)
        return False

    return True

def stop_ap(ap_iface, uplink_iface):
    if not require_root("Stopping Ghostlink-AP"):
        return False

    state = get_ap_state() or {}
    if not ap_iface:
        ap_iface = state.get("ap_iface")
    if not uplink_iface:
        uplink_iface = state.get("uplink_iface") or state.get("vpn_iface")
    state_vpn_iface = state.get("vpn_iface")

    _stop_pid(HOSTAPD_PID, HOSTAPD_CONF)
    _stop_pid(DNSMASQ_PID, DNSMASQ_CONF)

    if ap_iface and uplink_iface:
        for table, rule in _ap_cleanup_rules(ap_iface, uplink_iface):
            _iptables_delete_all(table, rule)

    # VPN mode kill-switch cleanup (state-driven so it survives blank arg calls)
    if ap_iface and state_vpn_iface:
        for table, rule in _killswitch_rules(ap_iface, state_vpn_iface):
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

#!/usr/bin/env python3
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from core.database import (
    get_db_stats, get_credentials, save_scan_result, save_pentest_job,
    save_credential, update_connection_status,
    get_network_scan_jobs, get_network_scan_hosts, get_network_scan_ports
)
from core.network import (
    detect_adapters, get_management_ip, scan_networks, connect_network,
    check_internet, start_ap, stop_ap, restart_networking, run_cmd_no_check,
    is_ghostlink_ap_running, interface_exists, get_connected_ssid,
    list_uplink_candidates, list_vpn_interfaces, get_ap_state, get_killswitch_status,
    is_wireless_interface, get_driver, get_operstate, get_default_route_iface,
    mt7612u_usb_present, list_usb_wifi_devices,
)
from core.pentest import start_pentest, check_monitor_mode
from core.platform import (
    detect_platform, get_driver_compatibility_warnings, get_fan_config_status,
    get_gpu_memory_status, get_overclock_status, get_zram_status,
)
from core.updater import update_ghostlink
from core.scanner import run_nmap_scan

def print_banner():
    print(r"""
██████╗ ██╗  ██╗ ██████╗ ███████╗████████╗██╗     ██╗███╗   ██╗██╗  ██╗
██╔════╝ ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝██║     ██║████╗  ██║██║ ██╔╝
██║  ███╗███████║██║   ██║███████╗   ██║   ██║     ██║██╔██╗ ██║█████╔╝ 
██║   ██║██╔══██║██║   ██║╚════██║   ██║   ██║     ██║██║╚██╗██║██╔═██╗ 
╚██████╔╝██║  ██║╚██████╔╝███████║   ██║   ███████╗██║██║ ╚████║██║  ██╗
 ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝
""")

def print_platform_overview(show_driver_warnings=False):
    platform_info = detect_platform()
    print(f"\n[+] Platform:              {platform_info['model']}")
    print(f"[+] Profile:               {platform_info['profile']} ({platform_info['support']})")
    print(
        f"[+] OS/Arch/Kernel:        {platform_info['pretty_name']} "
        f"({platform_info['codename']}) | {platform_info['architecture']} | {platform_info['kernel']}"
    )
    print(f"[+] ZRAM:                  {get_zram_status()}")
    print(f"[+] Overclock:             {get_overclock_status(platform_info)}")
    print(f"[+] GPU Memory:            {get_gpu_memory_status(platform_info)}")

    warnings = get_driver_compatibility_warnings(platform_info)
    if warnings:
        if show_driver_warnings:
            print("[!] Driver Compatibility:")
            for warning in warnings:
                print(f"    - {warning}")
        else:
            print(f"[!] Driver Compatibility: {len(warnings)} warning(s); run 'ghostlink -diag' for details.")
    else:
        print("[+] Driver Compatibility: No warnings detected.")
    return platform_info

def print_status_overview():
    print_platform_overview()
    adapters = detect_adapters()
    mgmt_iface = adapters.get("management")
    rtl8812au_iface = adapters.get("rtl8812au")
    mt7612u_iface = adapters.get("mt7612u")
    rtl88x2bu_iface = adapters.get("rtl88x2bu")
    rtl8188eus_iface = adapters.get("rtl8188eus")

    mgmt_ip = get_management_ip(mgmt_iface) if mgmt_iface else "Not found"
    mgmt_ssid = "Unknown"
    if mgmt_iface:
        mgmt_ssid = get_connected_ssid(mgmt_iface)

    internet_status = "Connected" if check_internet() else "Disconnected"
    ap_running = is_ghostlink_ap_running()
    ap_status = "Active" if ap_running else "Inactive"
    ap_state = get_ap_state() or {}
    ap_mode = ap_state.get("mode") if ap_running else "inactive"
    ap_egress = ap_state.get("vpn_iface") if ap_mode == "vpn" else ap_state.get("uplink_iface")

    rtl8812au_status = 'Missing (USB Not Found)'
    if rtl8812au_iface:
        rtl8812au_status = f"{rtl8812au_iface} ({get_driver(rtl8812au_iface)}, ready)"
    else:
        out, code = run_cmd_no_check("lsusb -d 0bda:8812")
        if code == 0 and out.strip():
            rtl8812au_status = 'Missing (USB Present, No Interface)'

    mt7612u_status = 'Missing (USB Not Found)'
    if mt7612u_iface:
        mt7612u_status = f"{mt7612u_iface} ({get_driver(mt7612u_iface)}, ready)"
    elif mt7612u_usb_present():
        mt7612u_status = 'Missing (USB Present, No Interface)'

    rtl88x2bu_status = 'Missing'
    if rtl88x2bu_iface:
        rtl88x2bu_status = f"{rtl88x2bu_iface} ({get_driver(rtl88x2bu_iface)})"

    rtl8188eus_status = 'Missing'
    if rtl8188eus_iface:
        rtl8188eus_status = f"{rtl8188eus_iface} ({get_driver(rtl8188eus_iface)})"

    print(f"\n[+] Management Network:    {mgmt_ssid}")
    print(f"[+] Management Interface:  {mgmt_iface}")
    print(f"[+] Management IP:         {mgmt_ip}")
    print(f"[-] RTL8812AU Status:      {rtl8812au_status}")
    print(f"[-] MT7612U Status:        {mt7612u_status}")
    print(f"[-] RTL88x2BU Status:      {rtl88x2bu_status}")
    print(f"[-] RTL8188EUS Status:     {rtl8188eus_status}")
    print(f"[-] Ghostlink-AP Status:   {ap_status}")
    if ap_running:
        ap_iface_now = ap_state.get("ap_iface", "unknown")
        ap_subnet_now = ap_state.get("ap_subnet", "10.0.0.0/24")
        mode_label = {"direct": "Direct NAT", "vpn": "VPN Gateway"}.get(ap_mode, ap_mode or "unknown")
        print(f"[-] AP Interface:          {ap_iface_now}  Subnet: {ap_subnet_now}")
        print(f"[-] AP Routing Mode:       {mode_label} -> {ap_egress or 'unknown'}")
        if ap_mode == "vpn":
            print(f"[-] AP Kill-switch:        {get_killswitch_status()}")
    print(f"[-] Internet Uplink:       {internet_status}\n")
    return adapters

def _external_role_ifaces(adapters, roles):
    seen = set()
    selected = []
    for role in roles:
        iface = adapters.get(role)
        if not iface or _is_management_iface(adapters, iface) or iface in seen:
            continue
        seen.add(iface)
        selected.append((role, iface))
    return selected

def _is_management_iface(adapters, iface):
    if not iface:
        return False
    if iface == adapters.get("management"):
        return True
    return get_driver(iface) in ["brcmfmac", "brcmsmac"]

def _tool_path(name):
    return shutil.which(name)

def _wifite_command():
    """Return the system-wide wifite command path, preferring 'wifite', falling back to 'wifite2'."""
    return _tool_path("wifite") or _tool_path("wifite2")

def _is_headless_env():
    return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")

def cmd_status():
    print_banner()
    print_status_overview()
    print("--- Detailed Status ---")
    print(f"DHCP/NAT Status: {'Active' if is_ghostlink_ap_running() else 'Inactive'}")
    creds = get_credentials()
    if creds:
        latest = creds[0]
        print(f"Latest Credential: {latest['ssid']} (BSSID: {latest['bssid']}) - Password: [HIDDEN]")
    else:
        print("Latest Credential: None")

def cmd_db():
    stats = get_db_stats()
    print("\n--- Database Status ---")
    print(f"Database Path: {stats.get('path', '/var/lib/ghostlink/ghostlink.db')}")
    print(f"Database Health: {stats['health']}")
    if stats.get("message"):
        print(f"Message: {stats['message']}")
    print(f"Total Saved Credentials: {stats['total_creds']}")
    print(f"Total Scan Records: {stats['total_networks']}")
    print(f"Total Pentest Jobs: {stats['total_pentests']}")
    print("\nLatest Pentest Jobs:")
    for job in stats['latest_pentests']:
        print(f"- {job['timestamp']} | Target: {job['target_ssid']} | Tool: {job['tool_used']} | Status: {job['result_status']}")

def cmd_creds():
    creds = get_credentials()
    if not creds:
        print("No saved credentials.")
        return
    print("\n--- Saved Credentials ---")
    for i, cred in enumerate(creds):
        print(f"{i+1}. {cred['ssid']} | BSSID: {cred['bssid']} | Adapter: {cred['adapter']} | Timestamp: {cred['timestamp']}")
        print(f"   Conn Status: {cred['connection_status']} | AP Status: {cred['ap_status']}")
    
    choice = input("\nEnter credential number to reveal password (or press Enter to exit): ")
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(creds):
            confirm = input(f"Are you sure you want to reveal the password for {creds[idx]['ssid']}? (y/n): ")
            if confirm.lower() == 'y':
                print(f"Password: {creds[idx]['password']}")
            else:
                print("Cancelled.")

def cmd_scan(iface=None):
    adapters = detect_adapters()
    scan_roles = ["rtl8812au", "mt7612u", "rtl8188eus", "rtl88x2bu"]
    candidates = [iface] if iface else [iface for _, iface in _external_role_ifaces(adapters, scan_roles)]
    candidates = [i for i in candidates if i]

    if not candidates:
        print("Error: No suitable adapter found for scanning.")
        if not adapters.get("rtl8812au"):
            out, code = run_cmd_no_check("lsusb -d 0bda:8812")
            if code == 0 and out.strip():
                print("Warning: RTL8812AU is physically connected but has no wireless interface. Check 'ghostlink -diag'.")
        if not adapters.get("mt7612u") and mt7612u_usb_present():
            print("Warning: MT7612U is physically connected but has no wireless interface. Check 'ghostlink -diag'.")
        return

    networks = []
    seen_bssids = set()
    attempted = []
    for candidate in candidates:
        if candidate in attempted:
            continue
        attempted.append(candidate)
        if not interface_exists(candidate):
            print(f"Warning: Interface {candidate} does not exist.")
            continue
        if not is_wireless_interface(candidate):
            print(f"Warning: Interface {candidate} is not a wireless interface.")
            continue
        if _is_management_iface(adapters, candidate):
            print(f"Warning: Interface {candidate} is configured for management. Skipping scan on it.")
            continue
        if os.geteuid() != 0 and get_operstate(candidate) == "down":
            print(f"Warning: Interface {candidate} is down. Run with sudo to let Ghostlink bring it up for scanning.")
            continue

        print(f"Scanning on interface {candidate}...")
        for network in scan_networks(candidate):
            bssid = network.get("bssid")
            if bssid and bssid in seen_bssids:
                continue
            if bssid:
                seen_bssids.add(bssid)
            networks.append(network)

        if iface:
            break
    
    if not networks:
        print("No networks found.")
        return
        
    print(f"\nFound {len(networks)} networks:")
    print(f"{'SSID':<25} {'BSSID':<20} {'CH':<4} {'SIG':<4} {'ENC'}")
    print("-" * 65)
    for n in networks:
        print(f"{n['ssid']:<25} {n['bssid']:<20} {n['channel']:<4} {n['signal']:<4} {n['encryption']}")
        try:
            save_scan_result(n['ssid'], n['bssid'], n['channel'], n['signal'], n['encryption'], n['interface'])
        except RuntimeError as e:
            print(f"\nWarning: scan results were not saved: {e}")
            return
    print("\nResults saved to database.")

def _find_target_network(iface, ssid, bssid=None):
    target_bssid = bssid.lower() if bssid else None
    matches = []
    for network in scan_networks(iface):
        if network.get("ssid") != ssid:
            continue
        if target_bssid and network.get("bssid", "").lower() != target_bssid:
            continue
        matches.append(network)
    if not matches:
        return None
    matches.sort(key=lambda n: n.get("signal", 0), reverse=True)
    return matches[0]

def cmd_pentest(ssid, iface=None, bssid=None):
    adapters = detect_adapters()
    if not iface:
        candidates = _external_role_ifaces(adapters, ["rtl8812au", "mt7612u", "rtl8188eus", "rtl88x2bu"])
        iface = candidates[0][1] if candidates else None

    if not iface:
        print("Error: No suitable adapter found for pentest.")
        if not adapters.get("rtl8812au"):
            out, code = run_cmd_no_check("lsusb -d 0bda:8812")
            if code == 0 and out.strip():
                print("Warning: RTL8812AU is physically connected but has no wireless interface. Check 'ghostlink -diag'.")
        if not adapters.get("mt7612u") and mt7612u_usb_present():
            print("Warning: MT7612U is physically connected but has no wireless interface. Check 'ghostlink -diag'.")
        return
    if not interface_exists(iface):
        print(f"Error: Interface {iface} does not exist.")
        return
    if not is_wireless_interface(iface):
        print(f"Error: Interface {iface} is not a wireless interface.")
        return

    if _is_management_iface(adapters, iface):
        print(f"Error: Interface {iface} is configured for management. Pentesting is blocked on this interface.")
        return
    if os.geteuid() != 0:
        print("Error: Pentesting requires root. Run with sudo.")
        return
    if not check_monitor_mode(iface):
        print(f"Error: Interface {iface} does not advertise monitor mode support.")
        return
    driver = get_driver(iface)
    if driver == "88XXau":
        print(f"[+] {iface} uses {driver} (primary Realtek pentest driver; full injection support).")
    elif driver == "8812au":
        print(f"[+] {iface} uses {driver} (RTL8812AU fallback driver; uplink OK, injection may vary).")
    elif driver in ["mt76x2u", "mt76usb"]:
        print(f"[+] {iface} uses {driver} (MediaTek mt76 main pentest driver).")
    elif driver.startswith("rtw"):
        print(f"Warning: {iface} uses {driver}. Monitor mode available, but injection/deauth quality depends on kernel driver support.")

    print(f"Preparing to attack '{ssid}' using {iface}...")
    confirm = input("This tool is for authorized/lab use only. Confirm target is authorized? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted.")
        return

    target = _find_target_network(iface, ssid, bssid)
    target_bssid = bssid
    target_channel = None
    if target:
        target_bssid = target.get("bssid") or bssid
        target_channel = target.get("channel")
        print(f"Target seen: BSSID {target_bssid}, channel {target_channel}, signal {target.get('signal')}")
    else:
        print("Warning: target was not visible in a preflight scan. Wifite will still try to find it.")
        
    print("Launching Wifite (this may take a while)...")
    result = start_pentest(iface, ssid, target_bssid, target_channel)
    
    if result["status"] == "success":
        print(f"\n[+] SUCCESS: Recovered key for {ssid}")
        try:
            result_bssid = result.get("bssid", target_bssid)
            pentest_id = save_pentest_job(ssid, result_bssid, iface, "wifite", "success", result.get("log_path", ""))
            save_credential(pentest_id, ssid, result_bssid, result["password"], iface)
            print("Credentials saved to database.")
        except RuntimeError as e:
            print(f"Warning: credentials were not saved: {e}")
        
        # Post-success flow
        conn = input(f"Do you want to connect {iface} to '{ssid}' now? (y/n): ")
        if conn.lower() == 'y':
            do_connect(ssid, result["password"], iface)
            ap = input("Do you want to start Ghostlink-AP now? (y/n): ")
            if ap.lower() == 'y':
                cmd_ap_start()
    else:
        print(f"\n[-] FAILED: {result.get('message')}")
        print(f"Log saved to: {result.get('log_path')}")
        try:
            save_pentest_job(ssid, target_bssid, iface, "wifite", "failed", result.get("log_path", ""))
        except RuntimeError as e:
            print(f"Warning: pentest result was not saved: {e}")

def do_connect(ssid, password, iface=None):
    adapters = detect_adapters()
    if not iface:
        candidates = _external_role_ifaces(adapters, ["rtl8812au", "mt7612u"])
        iface = candidates[0][1] if candidates else None
    if not iface:
        print("Error: No uplink adapter (RTL8812AU or MT7612U) detected.")
        return
    
    print(f"Connecting {iface} to {ssid}...")
    success = connect_network(iface, ssid, password)
    if success:
        print("Connection command sent. Checking internet through the target adapter...")
        time.sleep(5)
        if check_internet(iface):
            print("[+] Connected and internet is reachable through the target adapter.")
        else:
            print("[-] Connected, but internet is NOT reachable through the target adapter.")
    else:
        print("[-] Failed to connect.")

def cmd_connect():
    creds = get_credentials()
    if not creds:
        print("No saved credentials.")
        return
    print("\n--- Select Network to Connect ---")
    for i, cred in enumerate(creds):
        print(f"{i+1}. {cred['ssid']}")
    
    choice = input("\nEnter number (or press Enter to exit): ")
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(creds):
            do_connect(creds[idx]['ssid'], creds[idx]['password'])
            try:
                update_connection_status(creds[idx]['id'], 'Connected')
            except RuntimeError as e:
                print(f"Warning: connection status was not saved: {e}")

def _select_ap_iface(adapters):
    """Prompt user to pick AP adapter. Excludes management. Defaults to RTL88x2BU."""
    ap_candidates = _external_role_ifaces(adapters, ["rtl88x2bu", "rtl8812au", "mt7612u", "rtl8188eus"])
    ap_candidates = [(role, iface) for role, iface in ap_candidates if not _is_management_iface(adapters, iface)]
    if not ap_candidates:
        print("Error: No AP-capable adapter detected (RTL88x2BU preferred).")
        return None

    print("\n--- Select AP adapter ---")
    role_label = {
        "rtl88x2bu": "RTL88x2BU (recommended for AP)",
        "rtl8812au": "RTL8812AU (fallback)",
        "mt7612u": "MT7612U (fallback)",
        "rtl8188eus": "RTL8188EUS (fallback)",
    }
    for i, (role, iface) in enumerate(ap_candidates, 1):
        driver = get_driver(iface)
        print(f"  {i}. {iface}  driver={driver}  role={role_label.get(role, role)}")

    default_idx = 1  # First candidate is highest-priority by role order
    choice = input(f"\nSelect adapter (1-{len(ap_candidates)}, Enter for default {ap_candidates[0][1]}): ").strip()
    if not choice:
        idx = default_idx - 1
    elif choice.isdigit():
        idx = int(choice) - 1
    else:
        print("Cancelled: invalid input.")
        return None
    if not (0 <= idx < len(ap_candidates)):
        print("Cancelled: invalid selection.")
        return None
    return ap_candidates[idx][1]


def _select_routing_mode():
    print("\n--- Select routing mode ---")
    print("  1. Direct NAT       (AP traffic NAT'd through a chosen uplink)")
    print("  2. VPN Gateway      (AP traffic NAT'd only through an existing VPN/tunnel iface)")
    choice = input("Select mode (1-2, Enter to cancel): ").strip()
    if choice == "1":
        return "direct"
    if choice == "2":
        return "vpn"
    print("Cancelled: no routing mode selected.")
    return None


def _select_uplink(adapters, ap_iface):
    candidates = list_uplink_candidates(adapters)
    candidates = [c for c in candidates if c["iface"] != ap_iface]
    if not candidates:
        print("Error: No uplink interface found.")
        return None

    print("\n--- Select uplink interface (Direct NAT) ---")
    for i, c in enumerate(candidates, 1):
        flag = " [default route]" if c["default_route"] else ""
        print(f"  {i}. {c['iface']:<10} kind={c['kind']:<25} state={c['state']}{flag}")

    choice = input(f"Select uplink (1-{len(candidates)}, Enter to cancel): ").strip()
    if not choice.isdigit():
        print("Cancelled: no uplink selected.")
        return None
    idx = int(choice) - 1
    if not (0 <= idx < len(candidates)):
        print("Cancelled: invalid selection.")
        return None
    selected = candidates[idx]["iface"]
    if selected == ap_iface:
        print("Error: Uplink cannot equal AP interface.")
        return None
    return selected


def _select_vpn_iface(ap_iface):
    candidates = list_vpn_interfaces()
    up_candidates = [c for c in candidates if c["state"] == "up"]
    if not up_candidates:
        print("Error: No VPN/tunnel interface is up.")
        if candidates:
            print("       Detected but down: " + ", ".join(c["iface"] for c in candidates))
        print("       Bring up your VPN (WireGuard / OpenVPN / Tailscale) first, then retry.")
        print("       Ghostlink does not configure VPN providers in Phase 1.")
        return None

    print("\n--- Select VPN/tunnel interface (VPN Gateway) ---")
    for i, c in enumerate(up_candidates, 1):
        addr_str = "has-address" if c["has_address"] else "no-address"
        print(f"  {i}. {c['iface']:<14} state={c['state']:<5} {addr_str}")

    choice = input(f"Select VPN interface (1-{len(up_candidates)}, Enter to cancel): ").strip()
    if not choice.isdigit():
        print("Cancelled: no VPN interface selected.")
        return None
    idx = int(choice) - 1
    if not (0 <= idx < len(up_candidates)):
        print("Cancelled: invalid selection.")
        return None
    selected = up_candidates[idx]["iface"]
    if selected == ap_iface:
        print("Error: VPN interface cannot equal AP interface.")
        return None
    return selected


def cmd_ap_start():
    adapters = detect_adapters()

    ap_iface = _select_ap_iface(adapters)
    if not ap_iface:
        return
    if _is_management_iface(adapters, ap_iface):
        print(f"Error: AP interface {ap_iface} is the management interface. Refusing.")
        return

    mode = _select_routing_mode()
    if not mode:
        return

    uplink_iface = None
    vpn_iface = None
    if mode == "direct":
        uplink_iface = _select_uplink(adapters, ap_iface)
        if not uplink_iface:
            return
        print(f"\nStarting Ghostlink-AP on {ap_iface} (Direct NAT via {uplink_iface})...")
        ok = start_ap(ap_iface, uplink_iface, mode="direct")
    else:
        vpn_iface = _select_vpn_iface(ap_iface)
        if not vpn_iface:
            return
        print(f"\nStarting Ghostlink-AP on {ap_iface} (VPN Gateway via {vpn_iface}) with kill-switch...")
        ok = start_ap(ap_iface, uplink_iface=None, mode="vpn", vpn_iface=vpn_iface)

    if not ok:
        return

    print("Checking services...")
    time.sleep(2)
    if is_ghostlink_ap_running():
        print("[+] Ghostlink-AP is running (SSID: Ghostlink-AP, Password: Ghostlink123*)")
        if mode == "vpn":
            print(f"[+] AP-client traffic is restricted to {vpn_iface}. Kill-switch is active.")
        else:
            print(f"[+] AP-client traffic is NAT'd through {uplink_iface}.")
    else:
        print("[-] Failed to start AP services. Run 'ghostlink -diag' for more info.")

def cmd_ap_stop():
    adapters = detect_adapters()
    ap_iface = adapters.get("rtl88x2bu")
    uplink_iface = adapters.get("rtl8812au") or adapters.get("mt7612u")
    if not ap_iface or not uplink_iface:
        print("Cannot determine live interfaces. Stopping Ghostlink-created AP state only...")
        if not stop_ap(ap_iface, uplink_iface):
            return
    else:
        if not stop_ap(ap_iface, uplink_iface):
            return
    print("Ghostlink-AP stopped.")

def _iface_current_mode(iface):
    out, _ = run_cmd_no_check(f"iw dev {shlex.quote(iface)} info")
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("type "):
            return stripped.split()[1]
    return "unknown"


def _print_usb_wifi_devices():
    print("\nDetected USB Wi-Fi Devices:")
    devices = list_usb_wifi_devices()
    if not devices:
        print("- None reported by lsusb")
        return
    for device in devices:
        print(f"- {device['description']}")


def _print_mt7612u_diagnostics(adapters):
    mt_iface = adapters.get("mt7612u")
    mt_present = mt7612u_usb_present()

    print("\nMT7612U Diagnostics:")
    print(f"- Physical USB presence: {'Yes' if mt_present else 'No'}")
    print(f"- Mapped interface: {mt_iface if mt_iface else 'Missing'}")

    if mt_iface:
        driver = get_driver(mt_iface)
        support = "Yes" if check_monitor_mode(mt_iface) else "No"
        print(f"- Driver binding: {driver}")
        print(f"- Monitor mode support: {support}")
        if driver not in ["mt76x2u", "mt76usb"]:
            print("[!] WARNING: MT7612U is mapped by USB ID but is not bound to the mt76x2u/mt76usb stack.")
    elif mt_present:
        print("[!] WARNING: MT7612U USB device present but no network interface is bound")

    lsmod_out, _ = run_cmd_no_check("lsmod | grep mt76")
    loaded_mods = [line.split()[0] for line in lsmod_out.splitlines() if line.strip()]
    print(f"- Loaded mt76 modules: {', '.join(loaded_mods) if loaded_mods else 'None'}")

    _, mi_code = run_cmd_no_check("modinfo mt76x2u")
    if mi_code == 0:
        print("- mt76x2u module: Available in kernel")
        if mt_present and not mt_iface:
            print("- Next action: Try 'sudo modprobe mt76x2u'. Replug adapter.")
    else:
        print("- mt76x2u module: Missing from this kernel build")
        if mt_present and not mt_iface:
            print("- Next action: Check 'sudo apt-get install firmware-misc-nonfree'. Replug adapter.")


def cmd_diag():
    print("\n--- Diagnostics ---")
    platform_info = print_platform_overview(show_driver_warnings=True)
    print(f"[+] Platform Notes:        {platform_info['notes']}")
    print(f"[+] Pi 5 Fan Config:       {get_fan_config_status(platform_info)}")

    df_out, _ = run_cmd_no_check("df -h /")
    root_line = df_out.splitlines()[1] if df_out and len(df_out.splitlines()) >= 2 else "unavailable"
    print(f"[+] Root Filesystem:       {root_line}")
    print(f"[+] Active Default Route:  {get_default_route_iface()}")

    # Ghostlink-AP routing snapshot
    _ap_state = get_ap_state() or {}
    _ap_running = is_ghostlink_ap_running()
    _ap_mode = _ap_state.get("mode") if _ap_running else "inactive"
    _mode_label = {"direct": "Direct NAT", "vpn": "VPN Gateway", "inactive": "inactive"}.get(_ap_mode, _ap_mode or "inactive")
    print(f"[+] Ghostlink-AP:          {'Active' if _ap_running else 'Inactive'} (mode: {_mode_label})")
    if _ap_running:
        print(f"    AP Interface:        {_ap_state.get('ap_iface', 'unknown')}  Subnet: {_ap_state.get('ap_subnet', '10.0.0.0/24')}")
        if _ap_mode == "vpn":
            print(f"    VPN Interface:       {_ap_state.get('vpn_iface', 'unknown')}  state={get_operstate(_ap_state.get('vpn_iface', '')) or 'unknown'}")
            print(f"    Kill-switch:         {get_killswitch_status()}")
        else:
            print(f"    Uplink Interface:    {_ap_state.get('uplink_iface', 'unknown')}")
            print(f"    Kill-switch:         not applicable (Direct NAT mode)")

    adapters = detect_adapters()
    mgmt = adapters.get("management")
    mgmt_label = mgmt if mgmt else "not detected"
    print(f"\n[+] Management Protection: {mgmt_label} is excluded from scan/pentest/AP/monitor/attack")

    print("\nAdapter Map:")
    for role, iface in adapters.items():
        print(f"- {role}: {iface if iface else 'Missing'}")
        if iface:
            print(f"  Driver: {get_driver(iface)}")
            support = "Yes" if check_monitor_mode(iface) else "No"
            print(f"  Monitor mode support: {support}")
            print(f"  Current mode: {_iface_current_mode(iface)}")

    _print_usb_wifi_devices()
    _print_mt7612u_diagnostics(adapters)

    if not adapters.get("rtl8812au"):
        out, code = run_cmd_no_check("lsusb -d 0bda:8812")
        if code == 0 and out.strip():
            print("\n[!] WARNING: RTL8812AU USB device present but no network interface is bound")
            print("  - USB ID: 0bda:8812")
            print("  - Candidate modules: 88XXau, 8812au, rtw_8812au")

            lsmod_out, _ = run_cmd_no_check("lsmod | grep -E '8812|88XXau'")
            loaded_mods = [line.split()[0] for line in lsmod_out.splitlines() if line.strip()]
            print(f"  - Loaded modules: {', '.join(loaded_mods) if loaded_mods else 'None'}")

            dkms_out, _ = run_cmd_no_check("dkms status")
            print("  - DKMS Status:\n      " + "\n      ".join(dkms_out.splitlines() if dkms_out else ["None"]))

            dmesg_out, _ = run_cmd_no_check("dmesg | grep -Ei '8812|0bda:8812|88XXau' | tail -n 5")
            if dmesg_out:
                print("  - dmesg hint:\n      " + "\n      ".join(dmesg_out.splitlines()))

            print("  - Next action: Try 'sudo modprobe 88XXau' or 'sudo modprobe 8812au'. Replug adapter. Consider 'sudo ./setup.sh --update'.")

    print("\nDependencies:")
    # Wifite has two acceptable system-wide names
    for tool in ['wifite', 'wifite2']:
        path = _tool_path(tool)
        if path:
            v_out, v_code = run_cmd_no_check(f"{shlex.quote(path)} --version 2>/dev/null | head -n 1")
            version = f" ({v_out.strip()})" if v_code == 0 and v_out.strip() else ""
            print(f"- {tool}: Installed at {path}{version}")
        else:
            print(f"- {tool}: Missing")
    extended_tools = [
        'airgeddon', 'tmux', 'aircrack-ng', 'hostapd', 'dnsmasq', 'iw', 'nmcli', 'nmap',
        'tshark', 'hashcat', 'hcxdumptool', 'hcxpcapngtool',
        'reaver', 'bully', 'cowpatty', 'macchanger', 'sensors',
    ]
    for tool in extended_tools:
        path = _tool_path(tool)
        if path:
            version = ""
            if tool == 'nmap':
                v_out, _ = run_cmd_no_check(f"{shlex.quote(path)} -V | head -n 1")
                version = f" ({v_out.strip()})"
            elif tool == 'tmux':
                v_out, _ = run_cmd_no_check(f"{shlex.quote(path)} -V")
                version = f" ({v_out.strip()})"
            print(f"- {tool}: Installed ({path}){version}")
        else:
            print(f"- {tool}: Missing")

    # Headless / Airgeddon readiness
    headless = _is_headless_env()
    tmux_ok = _tool_path("tmux") is not None
    if headless:
        if tmux_ok:
            print("- Headless environment: Yes (no DISPLAY/WAYLAND_DISPLAY); tmux available — Airgeddon can run in headless tmux mode.")
        else:
            print("- Headless environment: Yes (no DISPLAY/WAYLAND_DISPLAY); tmux MISSING — Airgeddon will not run interactively.")
    else:
        print("- Headless environment: No (DISPLAY or WAYLAND_DISPLAY is set).")

    print("\nDriver Modules:")
    for module in ['88XXau', 'rtw_8812au', 'rtw88_8812au', 'mt76x2u', 'mt76_usb', 'mt76', 'rtw_8822bu', 'rtw88_8822bu', '8188eu', 'rtl8xxxu', 'brcmfmac']:
        _, code = run_cmd_no_check(f"modinfo {shlex.quote(module)}")
        print(f"- {module}: {'Available' if code == 0 else 'Missing'}")
        
    print("\nInternet Routing:")
    print(f"- Ping 8.8.8.8: {'Success' if check_internet() else 'Failed'}")
    
    print("\nDatabase Health:")
    stats = get_db_stats()
    print(f"- Path: {stats.get('path', '/var/lib/ghostlink/ghostlink.db')}")
    print(f"- Status: {stats['health']}")
    if stats.get("message"):
        print(f"- Message: {stats['message']}")
    
def cmd_restart_net():
    print("Restarting networking services...")
    if restart_networking():
        print("Restart command sent.")

def cmd_update():
    print("Updating Ghostlink...")
    res = update_ghostlink()
    if res['status'] == 'success':
        print("[+] Update successful.")
    else:
        print(f"[-] Update failed: {res['message']}")
        if 'log' in res:
            print(f"Log: {res['log']}")

def cmd_network_scan(args_target=None, args_type=None, args_last=False, args_list=False, args_show=None):
    if args_list:
        jobs = get_network_scan_jobs()
        if not jobs:
            print("No network scans found.")
            return
        print("\n--- Nmap Scans ---")
        for job in jobs:
            print(f"ID: {job['id']:<4} | {job['timestamp']} | Type: {job['scan_type']:<10} | Target: {job['target']:<15} | Status: {job['status']}")
        return

    if args_last or args_show:
        jobs = get_network_scan_jobs()
        if not jobs:
            print("No network scans found.")
            return
            
        job = None
        if args_last:
            job = jobs[0]
        else:
            for j in jobs:
                if str(j['id']) == str(args_show):
                    job = j
                    break
        if not job:
            print("Scan not found.")
            return
            
        print(f"\n--- Scan {job['id']} Details ---")
        print(f"Target: {job['target']}")
        print(f"Type: {job['scan_type']}")
        print(f"Time: {job['timestamp']}")
        print(f"Command: {job['command_used']}")
        print(f"Log: {job['log_path']}")
        
        hosts = get_network_scan_hosts(job['id'])
        if not hosts:
            print("\nNo hosts found.")
            return
            
        print(f"\nHosts Found: {len(hosts)}")
        for host in hosts:
            print(f"\n[+] {host['ip_address']} ({host['hostname'] or 'Unknown'}) - {host['mac_address'] or 'No MAC'}")
            ports = get_network_scan_ports(host['id'])
            if ports:
                print(f"    {'PORT':<10} {'STATE':<10} {'SERVICE':<15} {'VERSION'}")
                print(f"    {'-'*60}")
                for port in ports:
                    p = f"{port['port']}/{port['protocol']}"
                    print(f"    {p:<10} {port['state']:<10} {port['service']:<15} {port['version']}")
            else:
                print("    No open ports recorded.")
        return

    # Preflight: refuse to proceed if nmap is not installed
    if not _tool_path("nmap"):
        print("[-] Nmap is not installed. Run sudo ./setup.sh --update")
        return

    # Interactive mode logic if parameters are missing
    if not args_target:
        args_target = input("Enter target (e.g., 192.168.1.0/24) or Enter to cancel: ").strip()
        if not args_target:
            print("Cancelled: no Nmap target provided.")
            return

    if not args_type:
        print("\nScan Types:")
        print("1. discovery")
        print("2. quick")
        print("3. services")
        print("4. full")
        t_choice = input("Select type (1-4 or name) or Enter to cancel: ").strip()
        if not t_choice:
            print("Cancelled: no Nmap scan type provided.")
            return
            
        type_map = {
            "1": "discovery",
            "2": "quick",
            "3": "services",
            "4": "full"
        }
        args_type = type_map.get(t_choice, t_choice)
            
    override_auth = False
    override_large = False
    
    confirm = input(f"Are you authorized to scan {args_target}? (y/n/I AM AUTHORIZED): ")
    if confirm == "I AM AUTHORIZED":
        override_auth = True
    elif confirm.lower() != 'y':
        print("Aborted.")
        return
        
    print("Launching Nmap scan...")
    job_id = run_nmap_scan(args_type, args_target, override_large, override_auth)
    if job_id:
        print(f"Scan complete. Run 'ghostlink network-scan --show {job_id}' to view details.")

def cmd_adapter_roles():
    adapters = detect_adapters()
    role_labels = {
        "management": "Management (onboard — never used for scan/pentest/AP/monitor)",
        "rtl8812au":  "Pentest/uplink #1 (RTL8812AU)",
        "mt7612u":    "Pentest/uplink #2 (MT7612U)",
        "rtl88x2bu":  "AP adapter (RTL88x2BU)",
        "rtl8188eus": "Backup pentest (RTL8188EUS)",
    }
    print("\n--- Adapter Role Map (read-only view) ---")
    print("  Roles are assigned automatically by USB ID at runtime.")
    print("  Management interface is permanently excluded from all active roles.")
    for role, iface in adapters.items():
        label = role_labels.get(role, role)
        if iface:
            driver = get_driver(iface)
            mon = "monitor-capable" if check_monitor_mode(iface) else "managed only"
            mode = _iface_current_mode(iface)
            print(f"[+] {label}")
            print(f"    Interface: {iface}  Driver: {driver}  Mode: {mode}  ({mon})")
        else:
            print(f"[-] {label}")
            print(f"    Interface: not detected")


def cmd_monitor_mode():
    adapters = detect_adapters()
    candidates = _external_role_ifaces(adapters, ["rtl8812au", "mt7612u", "rtl8188eus", "rtl88x2bu"])
    if not candidates:
        print("No non-management wireless adapters detected.")
        return

    iface_list = [iface for _, iface in candidates]
    print("\n--- Monitor Mode Toggle ---")
    for i, iface in enumerate(iface_list, 1):
        driver = get_driver(iface)
        mon_cap = check_monitor_mode(iface)
        out, _ = run_cmd_no_check(f"iw dev {shlex.quote(iface)} info")
        current_type = "unknown"
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("type "):
                current_type = line.split()[1]
                break
        cap_str = "monitor-capable" if mon_cap else "no monitor support"
        print(f"  {i}. {iface} ({driver}, {cap_str}, current: {current_type})")

    choice = input("\nSelect adapter (1-{}) or Enter to cancel: ".format(len(iface_list))).strip()
    if not choice.isdigit():
        print("Cancelled.")
        return
    idx = int(choice) - 1
    if not (0 <= idx < len(iface_list)):
        print("Invalid selection.")
        return

    selected = iface_list[idx]
    if not check_monitor_mode(selected):
        print(f"[!] {selected} does not advertise monitor mode support. Cannot toggle.")
        return

    action = input("  Enable (e) or disable (d) monitor mode? ").strip().lower()
    if action == 'e':
        if os.geteuid() != 0:
            print("Error: root required to change interface mode. Run with sudo.")
            return
        run_cmd_no_check(f"ip link set {shlex.quote(selected)} down")
        out2, code2 = run_cmd_no_check(f"iw dev {shlex.quote(selected)} set type monitor")
        run_cmd_no_check(f"ip link set {shlex.quote(selected)} up")
        if code2 == 0:
            print(f"[+] {selected} is now in monitor mode.")
        else:
            print(f"[-] Failed to set monitor mode on {selected}: {out2}")
    elif action == 'd':
        if os.geteuid() != 0:
            print("Error: root required to change interface mode. Run with sudo.")
            return
        run_cmd_no_check(f"ip link set {shlex.quote(selected)} down")
        out2, code2 = run_cmd_no_check(f"iw dev {shlex.quote(selected)} set type managed")
        run_cmd_no_check(f"ip link set {shlex.quote(selected)} up")
        if code2 == 0:
            print(f"[+] {selected} is back in managed mode.")
        else:
            print(f"[-] Failed to set managed mode on {selected}: {out2}")
    else:
        print("Cancelled.")


def cmd_airgeddon():
    adapters = detect_adapters()
    candidates = _external_role_ifaces(adapters, ["rtl8812au", "mt7612u", "rtl8188eus", "rtl88x2bu"])
    if not candidates:
        print("No non-management wireless adapters detected for Airgeddon.")
        return

    iface_list = [iface for _, iface in candidates]
    print("\n--- Launch Airgeddon ---")
    for i, iface in enumerate(iface_list, 1):
        driver = get_driver(iface)
        print(f"  {i}. {iface} ({driver})")

    choice = input("\nSelect adapter for Airgeddon (1-{}) or Enter to cancel: ".format(len(iface_list))).strip()
    if not choice.isdigit():
        print("Cancelled.")
        return
    idx = int(choice) - 1
    if not (0 <= idx < len(iface_list)):
        print("Invalid selection.")
        return

    selected = iface_list[idx]

    airgeddon_paths = ["/usr/local/bin/airgeddon", "/opt/airgeddon/airgeddon.sh"]
    airgeddon_bin = None
    for path in airgeddon_paths:
        if os.path.isfile(path):
            airgeddon_bin = path
            break

    if not airgeddon_bin:
        print("[-] Airgeddon is not installed. Run 'sudo ./setup.sh --update' to install it.")
        return

    if os.geteuid() != 0:
        print("Error: Airgeddon requires root. Run with sudo.")
        return

    headless = _is_headless_env()
    tmux_available = _tool_path("tmux") is not None

    if headless and not tmux_available:
        print("[-] Headless environment detected (no DISPLAY/WAYLAND_DISPLAY) and tmux is not installed.")
        print("    Airgeddon needs tmux to run on a headless Raspberry Pi.")
        print("    Install tmux and rerun: sudo apt-get install -y tmux")
        print("    Or run: sudo ./setup.sh --update")
        return

    env = os.environ.copy()
    env["AIRGEDDON_AUTO_UPDATE"] = "false"
    env["IFACE"] = selected
    print(f"[+] Ghostlink validated {selected} as your external adapter.")
    print(f"    Airgeddon may prompt you to select an interface - choose: {selected}")
    print(f"    Do NOT select the management interface inside Airgeddon.")
    if headless:
        print("[+] Headless environment detected; tmux is installed.")
        print("    If Airgeddon reports 'no graphics system detected', open its Options menu")
        print("    and enable headless/tmux mode, then return to the main menu.")
    print(f"[+] Launching Airgeddon...")
    try:
        subprocess.run(["bash", airgeddon_bin], env=env, check=False)
    except FileNotFoundError:
        print("[-] bash not found. Cannot launch Airgeddon.")


def cmd_wifite_launcher():
    """Interactive Wifite launcher: pick adapter, then optional SSID/BSSID, then run Wifite system-wide."""
    wifite_bin = _wifite_command()
    if not wifite_bin:
        print("[-] Wifite is not installed system-wide. Run sudo ./setup.sh --update")
        return

    adapters = detect_adapters()
    candidates = _external_role_ifaces(
        adapters, ["rtl8812au", "mt7612u", "rtl8188eus", "rtl88x2bu"]
    )
    if not candidates:
        print("No non-management wireless adapters detected for Wifite.")
        return

    role_labels = {
        "rtl8812au": "Pentest/uplink #1 (RTL8812AU)",
        "mt7612u": "Pentest/uplink #2 (MT7612U)",
        "rtl8188eus": "Backup pentest (RTL8188EUS)",
        "rtl88x2bu": "AP adapter (RTL88x2BU) - last resort for pentest",
    }

    print("\n--- Start Wifite ---")
    for i, (role, iface) in enumerate(candidates, 1):
        driver = get_driver(iface)
        mon = "monitor-capable" if check_monitor_mode(iface) else "no monitor support"
        label = role_labels.get(role, role)
        print(f"  {i}. {iface}  driver={driver}  role={label}  ({mon})")

    choice = input(f"\nSelect adapter (1-{len(candidates)}) or Enter to cancel: ").strip()
    if not choice.isdigit():
        print("Cancelled: no adapter selected.")
        return
    idx = int(choice) - 1
    if not (0 <= idx < len(candidates)):
        print("Invalid selection.")
        return
    selected_role, selected_iface = candidates[idx]

    if _is_management_iface(adapters, selected_iface):
        print(f"Error: {selected_iface} is the management interface. Refusing to launch Wifite.")
        return
    if not check_monitor_mode(selected_iface):
        print(f"Warning: {selected_iface} does not advertise monitor mode support.")
        print("         Wifite may fail to put it into monitor mode.")

    ssid = input("Optional target SSID (Enter to let Wifite pick interactively): ").strip()
    bssid = ""
    if ssid:
        bssid = input("Optional target BSSID (Enter to skip): ").strip()
        confirm = input(
            "This tool is for authorized/lab use only. Confirm target is authorized? (y/n): "
        ).strip().lower()
        if confirm != "y":
            print("Aborted.")
            return
        # Targeted run uses Ghostlink's existing pentest pipeline (DB logging, post-flow)
        cmd_pentest(ssid, iface=selected_iface, bssid=bssid or None)
        return

    if os.geteuid() != 0:
        print("Error: Wifite requires root. Run with sudo.")
        return

    print(f"[+] Launching Wifite interactively on {selected_iface}...")
    print(f"    Wifite will let you select targets from a scan.")
    print(f"    Do NOT select the management network inside Wifite.")
    try:
        subprocess.run([wifite_bin, "-i", selected_iface], check=False)
    except FileNotFoundError:
        print(f"[-] Wifite binary not found at {wifite_bin}.")


def interactive_menu():
    while True:
        try:
            print_banner()
            print_status_overview()
            
            print("1.  Status")
            print("2.  Start Wifite")
            print("3.  Start Airgeddon")
            print("4.  Start Nmap")
            print("5.  Show saved credentials")
            print("6.  Connect to saved network")
            print("7.  Start Ghostlink-AP on RTL88x2BU")
            print("8.  Stop Ghostlink-AP")
            print("9.  Restart networking services")
            print("10. Run diagnostics")
            print("11. Update Ghostlink")
            print("12. Adapter roles")
            print("13. Monitor mode toggle")
            print("14. Exit")

            choice = input("\nSelect option: ")

            if choice == '1':
                cmd_status()
            elif choice == '2':
                cmd_wifite_launcher()
            elif choice == '3':
                cmd_airgeddon()
            elif choice == '4':
                cmd_network_scan()
            elif choice == '5':
                cmd_creds()
            elif choice == '6':
                cmd_connect()
            elif choice == '7':
                cmd_ap_start()
            elif choice == '8':
                cmd_ap_stop()
            elif choice == '9':
                cmd_restart_net()
            elif choice == '10':
                cmd_diag()
            elif choice == '11':
                cmd_update()
            elif choice == '12':
                cmd_adapter_roles()
            elif choice == '13':
                cmd_monitor_mode()
            elif choice == '14':
                break
            else:
                print("Invalid option.")
                
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            print("\nExiting Ghostlink.")
            break

def main():
    parser = argparse.ArgumentParser(description="Ghostlink")
    parser.add_argument('-status', action='store_true', help="Show status")
    parser.add_argument('-db', action='store_true', help="Show database status")
    parser.add_argument('-creds', action='store_true', help="Show saved credentials")
    parser.add_argument('-connect', action='store_true', help="Connect to saved network")
    parser.add_argument('-ap-start', action='store_true', help="Start AP")
    parser.add_argument('-ap-stop', action='store_true', help="Stop AP")
    parser.add_argument('-diag', action='store_true', help="Run diagnostics")
    parser.add_argument('-restart-net', action='store_true', help="Restart networking")
    parser.add_argument('-update', action='store_true', help="Update tool")
    
    subparsers = parser.add_subparsers(dest='command')
    
    # scan command
    scan_parser = subparsers.add_parser('scan', help='Scan networks')
    scan_parser.add_argument('--iface', help='Interface to use')
    
    # pentest command
    pentest_parser = subparsers.add_parser('pentest', help='Start Wifite workflow')
    pentest_parser.add_argument('--iface', help='Interface to use')
    pentest_parser.add_argument('--ssid', required=True, help='Target SSID')
    pentest_parser.add_argument('--bssid', help='Target BSSID')
    # network-scan command
    nscan_parser = subparsers.add_parser('network-scan', help='Run nmap network scan')
    nscan_parser.add_argument('--target', help='Target IP or CIDR')
    nscan_parser.add_argument('--type', help='Scan type (discovery, quick, services, etc)')
    nscan_parser.add_argument('--last', action='store_true', help='Show last scan results')
    nscan_parser.add_argument('--list', action='store_true', help='List all scans')
    nscan_parser.add_argument('--show', help='Show details for specific scan ID')
    
    args = parser.parse_args()
    
    # Handle direct commands
    if args.status:
        cmd_status()
    elif args.db:
        cmd_db()
    elif args.creds:
        cmd_creds()
    elif args.connect:
        cmd_connect()
    elif args.ap_start:
        cmd_ap_start()
    elif args.ap_stop:
        cmd_ap_stop()
    elif args.diag:
        cmd_diag()
    elif args.restart_net:
        cmd_restart_net()
    elif args.update:
        cmd_update()
    elif args.command == 'scan':
        cmd_scan(args.iface)
    elif args.command == 'pentest':
        cmd_pentest(args.ssid, args.iface, args.bssid)
    elif args.command == 'network-scan':
        cmd_network_scan(args.target, args.type, args.last, args.list, args.show)
    else:
        # No args, show interactive menu
        interactive_menu()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting Ghostlink.")
        sys.exit(0)

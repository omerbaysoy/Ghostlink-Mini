#!/usr/bin/env python3
import argparse
import os
import time
import shlex
import sys
from core.database import (
    get_db_stats, get_credentials, save_scan_result, save_pentest_job,
    save_credential, update_connection_status,
    get_network_scan_jobs, get_network_scan_hosts, get_network_scan_ports
)
from core.network import (
    detect_adapters, get_management_ip, scan_networks, connect_network,
    check_internet, start_ap, stop_ap, restart_networking, run_cmd_no_check,
    is_ghostlink_ap_running, interface_exists, get_connected_ssid,
    is_wireless_interface, get_driver, get_operstate, get_default_route_iface
)
from core.pentest import start_pentest, check_monitor_mode
from core.updater import update_ghostlink
from core.scanner import run_nmap_scan

def print_banner():
    print(r"""
========================================
              GHOSTLINK-MINI
           signal ops :: cli
========================================
""")

def print_status_overview():
    adapters = detect_adapters()
    mgmt_iface = adapters.get("management")
    rtl8812au_iface = adapters.get("rtl8812au")
    rtl88x2bu_iface = adapters.get("rtl88x2bu")
    rtl8188eus_iface = adapters.get("rtl8188eus")
    
    mgmt_ip = get_management_ip(mgmt_iface) if mgmt_iface else "Not found"
    # Get current mgmt SSID
    mgmt_ssid = "Unknown"
    if mgmt_iface:
        mgmt_ssid = get_connected_ssid(mgmt_iface)
            
    # Check internet via RTL8812AU (or generally)
    internet_status = "Connected" if check_internet() else "Disconnected"
    
    # Check AP status
    ap_status = "Active" if is_ghostlink_ap_running() else "Inactive"

    rtl8812au_status = 'Missing (USB Not Found)'
    if rtl8812au_iface:
        rtl8812au_status = f"{rtl8812au_iface} ({get_driver(rtl8812au_iface)}, ready)"
    else:
        out, code = run_cmd_no_check("lsusb -d 0bda:8812")
        if code == 0 and out.strip():
            rtl8812au_status = 'Missing (USB Present, No Interface)'
            
    rtl88x2bu_status = 'Missing'
    if rtl88x2bu_iface:
        rtl88x2bu_status = f"{rtl88x2bu_iface} ({get_driver(rtl88x2bu_iface)})"
        
    rtl8188eus_status = 'Missing'
    if rtl8188eus_iface:
        rtl8188eus_status = f"{rtl8188eus_iface} ({get_driver(rtl8188eus_iface)})"

    print(f"\n[+] Management Network: {mgmt_ssid}")
    print(f"[+] Management Interface: {mgmt_iface}")
    print(f"[+] Management IP: {mgmt_ip}")
    print(f"[-] RTL8812AU Status: {rtl8812au_status}")
    print(f"[-] RTL88x2BU Status: {rtl88x2bu_status}")
    print(f"[-] RTL8188EUS Status: {rtl8188eus_status}")
    print(f"[-] Ghostlink-AP Status: {ap_status}")
    print(f"[-] Internet Uplink: {internet_status}\n")
    return adapters

def cmd_status():
    print_banner()
    adapters = print_status_overview()
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
    candidates = [iface] if iface else [
        adapters.get("rtl8812au"),
        adapters.get("rtl8188eus"),
        adapters.get("rtl88x2bu"),
    ]
    candidates = [i for i in candidates if i]
    
    if not candidates:
        print("Error: No suitable adapter found for scanning.")
        if not adapters.get("rtl8812au"):
            out, code = run_cmd_no_check("lsusb -d 0bda:8812")
            if code == 0 and out.strip():
                print("Warning: RTL8812AU is physically connected but has no wireless interface. Check 'ghostlink -diag'.")
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
        if candidate == adapters.get("management"):
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
        iface = adapters.get("rtl8812au") or adapters.get("rtl8188eus") or adapters.get("rtl88x2bu")
        
    if not iface:
        print("Error: No suitable adapter found for pentest.")
        if not adapters.get("rtl8812au"):
            out, code = run_cmd_no_check("lsusb -d 0bda:8812")
            if code == 0 and out.strip():
                print("Warning: RTL8812AU is physically connected but has no wireless interface. Check 'ghostlink -diag'.")
        return
    if not interface_exists(iface):
        print(f"Error: Interface {iface} does not exist.")
        return
    if not is_wireless_interface(iface):
        print(f"Error: Interface {iface} is not a wireless interface.")
        return
        
    if iface == adapters.get("management"):
        print(f"Error: Interface {iface} is configured for management. Pentesting is blocked on this interface.")
        return
    if os.geteuid() != 0:
        print("Error: Pentesting requires root. Run with sudo.")
        return
    if not check_monitor_mode(iface):
        print(f"Error: Interface {iface} does not advertise monitor mode support.")
        return
    driver = get_driver(iface)
    if driver.startswith("rtw"):
        print(f"Warning: {iface} uses {driver}. Monitor mode is available, but injection/deauth quality depends on kernel driver support.")
        
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
        conn = input(f"Do you want to connect RTL8812AU to '{ssid}' now? (y/n): ")
        if conn.lower() == 'y':
            do_connect(ssid, result["password"])
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

def do_connect(ssid, password):
    adapters = detect_adapters()
    iface = adapters.get("rtl8812au")
    if not iface:
        print("Error: RTL8812AU is not connected or detected.")
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

def cmd_ap_start():
    adapters = detect_adapters()
    ap_iface = adapters.get("rtl88x2bu")
    uplink_iface = adapters.get("rtl8812au")
    
    if not ap_iface:
        print("Error: RTL88x2BU adapter not detected for AP.")
        return
    if not uplink_iface:
        print("Error: RTL8812AU uplink adapter not detected.")
        return
        
    print(f"Starting Ghostlink-AP on {ap_iface} shared via {uplink_iface}...")
    if not start_ap(ap_iface, uplink_iface):
        return
    
    print("Checking services...")
    time.sleep(2)
    if is_ghostlink_ap_running():
        print("[+] Ghostlink-AP is running (SSID: Ghostlink-AP, Password: Ghostlink123*)")
    else:
        print("[-] Failed to start AP services. Run 'ghostlink -diag' for more info.")

def cmd_ap_stop():
    adapters = detect_adapters()
    ap_iface = adapters.get("rtl88x2bu")
    uplink_iface = adapters.get("rtl8812au")
    if not ap_iface or not uplink_iface:
        print("Cannot determine live interfaces. Stopping Ghostlink-created AP state only...")
        if not stop_ap(ap_iface, uplink_iface):
            return
    else:
        if not stop_ap(ap_iface, uplink_iface):
            return
    print("Ghostlink-AP stopped.")

def cmd_diag():
    print("\n--- Diagnostics ---")
    out, _ = run_cmd_no_check("cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2")
    print(f"OS Version: {out.strip('\"')}")
    out, _ = run_cmd_no_check("uname -r")
    print(f"Kernel Version: {out}")
    print(f"Active Default Route: {get_default_route_iface()}")
    
    adapters = detect_adapters()
    print(f"\nAdapter Map:")
    for role, iface in adapters.items():
        print(f"- {role}: {iface if iface else 'Missing'}")
        if iface:
            print(f"  Driver: {get_driver(iface)}")
            support = "Yes" if check_monitor_mode(iface) else "No"
            print(f"  Monitor mode support: {support}")
            
    if not adapters.get("rtl8812au"):
        out, code = run_cmd_no_check("lsusb -d 0bda:8812")
        if code == 0 and out.strip():
            print("\n[!] WARNING: RTL8812AU USB device present but no network interface is bound")
            print("  - USB ID: 0bda:8812")
            print("  - Candidate modules: 88XXau, 8812au, rtw_8812au")
            
            lsmod_out, _ = run_cmd_no_check("lsmod | egrep '8812|88XXau'")
            loaded_mods = [line.split()[0] for line in lsmod_out.splitlines() if line.strip()]
            print(f"  - Loaded modules: {', '.join(loaded_mods) if loaded_mods else 'None'}")
            
            dkms_out, _ = run_cmd_no_check("dkms status")
            print(f"  - DKMS Status:\n      " + "\n      ".join(dkms_out.splitlines() if dkms_out else ["None"]))
            
            dmesg_out, _ = run_cmd_no_check("dmesg | egrep -i '8812|0bda:8812|88XXau' | tail -n 5")
            if dmesg_out:
                print(f"  - dmesg hint:\n      " + "\n      ".join(dmesg_out.splitlines()))
                
            print("  - Next action: Try 'sudo modprobe 88XXau' or 'sudo modprobe 8812au'. Replug adapter. Consider 'sudo ./setup.sh --update'.")
            
    print("\nDependencies:")
    for tool in ['wifite', 'airgeddon', 'aircrack-ng', 'hostapd', 'dnsmasq', 'iw', 'nmcli', 'nmap']:
        out, code = run_cmd_no_check(f"which {tool}")
        if code == 0:
            version = ""
            if tool == 'nmap':
                v_out, _ = run_cmd_no_check(f"{tool} -V | head -n 1")
                version = f" ({v_out})"
            elif tool == 'wifite':
                v_out, _ = run_cmd_no_check(f"{tool} --version 2>/dev/null | head -n 1")
                version = f" ({v_out.strip()})"
            print(f"- {tool}: Installed{version}")
        else:
            print(f"- {tool}: Missing")

    print("\nDriver Modules:")
    for module in ['88XXau', 'rtw_8812au', 'rtw88_8812au', 'rtw_8822bu', 'rtw88_8822bu', '8188eu', 'rtl8xxxu', 'brcmfmac']:
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
    print("Updating Ghostlink-Mini...")
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
        print("\n--- Network Scans ---")
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

    # Interactive mode logic if parameters are missing
    if not args_target:
        args_target = input("Enter target (e.g., 192.168.1.0/24): ")
        if not args_target:
            return
            
    if not args_type:
        print("\nScan Types:")
        print("1. discovery")
        print("2. quick")
        print("3. services")
        print("4. full")
        t_choice = input("Select type (name): ")
        args_type = t_choice.strip()
        if not args_type:
            return
            
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

def interactive_menu():
    while True:
        try:
            print_banner()
            print_status_overview()
            
            print("1. Status")
            print("2. Scan Wi-Fi networks")
            print("3. Start pentest with RTL8812AU")
            print("4. Show saved credentials")
            print("5. Connect RTL8812AU to saved network")
            print("6. Start Ghostlink-AP on RTL88x2BU")
            print("7. Stop Ghostlink-AP")
            print("8. Network Scan")
            print("9. Restart networking services")
            print("10. Run diagnostics")
            print("11. Update Ghostlink-Mini")
            print("12. Exit")
            
            choice = input("\nSelect option: ")
            
            if choice == '1':
                cmd_status()
            elif choice == '2':
                cmd_scan()
            elif choice == '3':
                ssid = input("Target SSID: ")
                if ssid:
                    cmd_pentest(ssid)
            elif choice == '4':
                cmd_creds()
            elif choice == '5':
                cmd_connect()
            elif choice == '6':
                cmd_ap_start()
            elif choice == '7':
                cmd_ap_stop()
            elif choice == '8':
                cmd_network_scan()
            elif choice == '9':
                cmd_restart_net()
            elif choice == '10':
                cmd_diag()
            elif choice == '11':
                cmd_update()
            elif choice == '12':
                break
            else:
                print("Invalid option.")
                
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            print("\nExiting Ghostlink-Mini.")
            break

def main():
    parser = argparse.ArgumentParser(description="Ghostlink-Mini")
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
    pentest_parser = subparsers.add_parser('pentest', help='Start pentest')
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
        print("\nExiting Ghostlink-Mini.")
        sys.exit(0)

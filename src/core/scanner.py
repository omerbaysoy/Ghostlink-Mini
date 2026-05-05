import os
import subprocess
import shlex
import xml.etree.ElementTree as ET
from datetime import datetime
from .config import GHOSTLINK_LOG_DIR
from .database import save_network_scan_job, save_network_scan_host, save_network_scan_port

SCAN_LOG_DIR = os.path.join(GHOSTLINK_LOG_DIR, "network_scans")

def _ensure_log_dir():
    os.makedirs(SCAN_LOG_DIR, exist_ok=True)

def _is_private_ip(target):
    # Basic check for private ranges
    # Matches 10.x.x.x, 172.16-31.x.x, 192.168.x.x
    import ipaddress
    try:
        # If it's a network
        net = ipaddress.ip_network(target, strict=False)
        return net.is_private
    except ValueError:
        pass
    try:
        # If it's a single host
        ip = ipaddress.ip_address(target)
        return ip.is_private
    except ValueError:
        pass
    return False

def _check_safety(target, override_large=False, override_auth=False):
    try:
        import ipaddress
        net = ipaddress.ip_network(target, strict=False)
        if net.prefixlen < 9:
            if not override_large:
                print(f"Error: Target {target} is too large. Requires explicit 'OVERRIDE LARGE SCAN' to proceed.")
                return False
    except ValueError:
        pass

    if not _is_private_ip(target):
        if not override_auth:
            print(f"Warning: Target {target} appears to be a public IP or non-private range.")
            print("To scan this target, you must explicitly confirm 'I AM AUTHORIZED'.")
            return False
            
    return True

def run_nmap_scan(scan_type, target, override_large=False, override_auth=False):
    if not _check_safety(target, override_large, override_auth):
        return None

    import shutil
    if not shutil.which("nmap"):
        print("Error: nmap is not installed. Run 'sudo apt-get install nmap' or 'sudo ./setup.sh --update'.")
        return None

    _ensure_log_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_prefix = os.path.join(SCAN_LOG_DIR, f"scan_{scan_type}_{timestamp}")
    
    is_root = os.geteuid() == 0
    sudo = "sudo " if not is_root else ""
    
    cmd_map = {
        "discovery": "nmap -sn",
        "arp": f"{sudo}nmap -PR -sn",
        "quick": "nmap -F",
        "ports": f"{sudo}nmap -sS --top-ports 1000" if is_root else "nmap -sT --top-ports 1000",
        "full": f"{sudo}nmap -sS -p- --min-rate 1000",
        "services": "nmap -sV -sC",
        "os": f"{sudo}nmap -O",
        "udp-top": f"{sudo}nmap -sU --top-ports 50",
        "traceroute": "nmap --traceroute",
        "safe-scripts": "nmap --script default,safe"
    }
    
    base_cmd = cmd_map.get(scan_type)
    if not base_cmd:
        print(f"Error: Unknown scan type '{scan_type}'")
        return None
        
    # We use -oX to parse later, and -oN to save a readable copy
    full_cmd = f"{base_cmd} -oX {shlex.quote(out_prefix + '.xml')} -oN {shlex.quote(out_prefix + '.txt')} {shlex.quote(target)}"
    
    print(f"Running: {full_cmd}")
    
    # Save job as pending
    job_id = save_network_scan_job(scan_type, target, full_cmd, "running", out_prefix + ".txt")
    
    try:
        subprocess.run(full_cmd, shell=True, check=True)
        status = "success"
    except subprocess.CalledProcessError:
        status = "failed"
        
    # Update DB status (we don't have update_job, so we just run a raw query)
    from .database import get_connection, _ensure_writable_database
    _ensure_writable_database()
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE network_scan_jobs SET status = ? WHERE id = ?', (status, job_id))
    conn.commit()
    conn.close()
    
    # Parse XML and populate DB
    xml_path = out_prefix + ".xml"
    if os.path.exists(xml_path):
        _parse_nmap_xml(xml_path, job_id)
        
    return job_id

def _parse_nmap_xml(xml_path, job_id):
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        for host in root.findall('host'):
            state_elem = host.find('status')
            if state_elem is None or state_elem.get('state') != 'up':
                continue
                
            ip_address = ""
            mac_address = ""
            for addr in host.findall('address'):
                if addr.get('addrtype') == 'ipv4' or addr.get('addrtype') == 'ipv6':
                    ip_address = addr.get('addr')
                elif addr.get('addrtype') == 'mac':
                    mac_address = addr.get('addr')
                    
            hostname = ""
            hostnames = host.find('hostnames')
            if hostnames is not None:
                hn = hostnames.find('hostname')
                if hn is not None:
                    hostname = hn.get('name', '')
                    
            state = state_elem.get('state')
            host_id = save_network_scan_host(job_id, ip_address, hostname, state, mac_address)
            
            ports = host.find('ports')
            if ports is not None:
                for port in ports.findall('port'):
                    port_id = port.get('portid')
                    protocol = port.get('protocol')
                    state_elem = port.find('state')
                    port_state = state_elem.get('state') if state_elem is not None else ""
                    
                    service_elem = port.find('service')
                    service_name = ""
                    version_info = ""
                    if service_elem is not None:
                        service_name = service_elem.get('name', '')
                        product = service_elem.get('product', '')
                        version = service_elem.get('version', '')
                        extrainfo = service_elem.get('extrainfo', '')
                        version_info = f"{product} {version} {extrainfo}".strip()
                        
                    save_network_scan_port(host_id, port_id, protocol, port_state, service_name, version_info)
    except Exception as e:
        print(f"Warning: Failed to parse nmap xml: {e}")

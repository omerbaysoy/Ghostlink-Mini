import os
import json
from pathlib import Path

# Base Paths
GHOSTLINK_DIR = "/etc/ghostlink"

# Known USB vendor:product IDs for adapter identification
RTL8812AU_USB_IDS = frozenset({"0bda:8812"})
RTL88X2BU_USB_IDS = frozenset({"0bda:b812"})
RTL8188EUS_USB_IDS = frozenset({"2357:010c"})
MT7612U_USB_IDS = frozenset({
    "0e8d:7612",   # MediaTek MT7612U reference design (Alfa AWUS036ACM, etc.)
    "0e8d:761a",   # MediaTek MT7662U (uses same mt76x2u driver)
    "2001:3a02",   # D-Link DWA-182 rev D
    "0b05:17d1",   # ASUS USB-AC55
    "148f:7612",   # Ralink/MediaTek MT7612U OEM
    "13b1:003e",   # Linksys WUSB6300 v2
})
GHOSTLINK_LIB_DIR = "/var/lib/ghostlink"
GHOSTLINK_LOG_DIR = "/var/log/ghostlink"

DB_PATH = os.path.join(GHOSTLINK_LIB_DIR, "ghostlink.db")
CONFIG_PATH = os.path.join(GHOSTLINK_DIR, "config.json")
ADAPTER_MAP_PATH = os.path.join(GHOSTLINK_DIR, "adapters.json")

def ensure_paths():
    errors = []
    for p in [GHOSTLINK_DIR, GHOSTLINK_LIB_DIR, GHOSTLINK_LOG_DIR]:
        try:
            os.makedirs(p, exist_ok=True)
        except OSError as e:
            errors.append(f"{p}: {e}")
    return errors

def path_status(path):
    p = Path(path)
    return {
        "path": str(p),
        "exists": p.exists(),
        "readable": os.access(path, os.R_OK) if p.exists() else False,
        "writable": os.access(path, os.W_OK) if p.exists() else False,
    }

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
            f.write("\n")
    except Exception as e:
        print(f"Error saving config: {e}")

def load_adapter_map():
    if not os.path.exists(ADAPTER_MAP_PATH):
        return {}
    try:
        with open(ADAPTER_MAP_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_adapter_map(adapter_map):
    try:
        os.makedirs(os.path.dirname(ADAPTER_MAP_PATH), exist_ok=True)
        with open(ADAPTER_MAP_PATH, "w") as f:
            json.dump(adapter_map, f, indent=4)
            f.write("\n")
        return True
    except Exception as e:
        return False

ensure_paths()
